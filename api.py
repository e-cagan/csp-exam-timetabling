"""
FastAPI backend for the University Exam Timetabling System.

Architecture (v4 — Universal Import + Benchmarks):
    The API now supports three distinct data paths:

    ┌─────────────────────────────────────────────────────────┐
    │  GENERIC PATH (production)                              │
    │                                                         │
    │  POST /solve                                            │
    │    Frontend sends full instance payload (exams,         │
    │    rooms, timeslots, instructors) → API hydrates        │
    │    domain objects → passes to cp_solver → returns       │
    │    solution. Zero data generation. Zero scaling.        │
    │    The API is a pure, stateless conduit.                │
    └─────────────────────────────────────────────────────────┘

    ┌─────────────────────────────────────────────────────────┐
    │  UPLOAD PATH (Universal Import)                         │
    │                                                         │
    │  POST /upload                                           │
    │    Accepts .xlsx files in the standard template format, │
    │    parses using standard_parser.py, and returns the     │
    │    parsed instance as JSON for the frontend.            │
    └─────────────────────────────────────────────────────────┘

    ┌─────────────────────────────────────────────────────────┐
    │  BENCHMARK PATHS (testing only)                         │
    │                                                         │
    │  POST /benchmark/carter/parse | /benchmark/carter/solve │
    │    Reads Carter .crs/.stu files with synthetic scaling. │
    │                                                         │
    │  POST /benchmark/okan/parse | /benchmark/okan/solve     │
    │    Reads the Okan University dataset from the standard  │
    │    Excel template (okan_benchmark.xlsx).                │
    └─────────────────────────────────────────────────────────┘

Start with:
    uvicorn api:app --reload --port 8000
"""

from __future__ import annotations

import math
import os
import time
import traceback
import tempfile
from pathlib import Path
from typing import Optional

from fastapi.responses import FileResponse
from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from src.solvers.cp_solver import solve as cp_solve
from src.models.domain import (
    Exam, TimeSlot, Room, Instructor, ProblemInstance,
)


# ══════════════════════════════════════════════════════════════
#  APP SETUP
# ══════════════════════════════════════════════════════════════

app = FastAPI(
    title="UETP Solver API",
    description="University Exam Timetabling — CP-SAT solver backend",
    version="4.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ══════════════════════════════════════════════════════════════
#  SHARED SCHEMAS (used by all paths)
# ══════════════════════════════════════════════════════════════

class SolverConfig(BaseModel):
    """Solver tuning knobs — shared by generic and benchmark paths."""
    # Added weight validation
    w1: int = Field(default=1, ge=0, le=10)
    w2: int = Field(default=5, ge=0, le=10)
    w3: int = Field(default=2, ge=0, le=10)
    w4: int = Field(default=3, ge=0, le=10)
    enable_s3: bool = True
    enable_s4: bool = True
    time_limit: int = 120


class SolveResponse(BaseModel):
    """Shared response format — identical for all paths."""
    status: str
    message: str
    instance: Optional[dict] = None
    solution: Optional[dict] = None
    stats: Optional[dict] = None


class ParseResponse(BaseModel):
    """Response format for parse endpoints."""
    status: str
    message: str
    instance: Optional[dict] = None
    metadata: Optional[dict] = None


# ══════════════════════════════════════════════════════════════
#  GENERIC PATH — Pydantic schemas that mirror domain.py
# ══════════════════════════════════════════════════════════════

class ExamPayload(BaseModel):
    id: int
    student_ids: list[int]
    lecturer_id: int
    required_invigilators: int = 1
    code: Optional[str] = None
    name: Optional[str] = None


class TimeslotPayload(BaseModel):
    id: int
    day: int
    period: int
    dayLabel: Optional[str] = None
    periodLabel: Optional[str] = None


class RoomPayload(BaseModel):
    id: int
    capacity: int
    label: Optional[str] = None


class InstructorPayload(BaseModel):
    id: int
    is_phd: bool
    preferences: dict[str, bool] = {}
    name: Optional[str] = None


class InstancePayload(BaseModel):
    """Complete problem instance from the frontend."""
    exams: list[ExamPayload]
    timeslots: list[TimeslotPayload]
    rooms: list[RoomPayload]
    instructors: list[InstructorPayload]


class GenericSolveRequest(BaseModel):
    """The primary /solve endpoint payload."""
    instance: InstancePayload
    config: SolverConfig = SolverConfig()


# ══════════════════════════════════════════════════════════════
#  HYDRATION — JSON payloads → domain.py dataclass objects
# ══════════════════════════════════════════════════════════════

def hydrate_instance(payload: InstancePayload) -> ProblemInstance:
    """Convert frontend JSON → domain.py dataclass objects."""
    exams = [
        Exam(
            id=e.id,
            student_ids=set(e.student_ids),
            lecturer_id=e.lecturer_id,
            required_invigilators=e.required_invigilators,
        )
        for e in payload.exams
    ]

    timeslots = [
        TimeSlot(id=ts.id, day=ts.day, period=ts.period)
        for ts in payload.timeslots
    ]

    rooms = [
        Room(id=r.id, capacity=r.capacity)
        for r in payload.rooms
    ]

    instructors = [
        Instructor(
            id=i.id,
            is_phd=i.is_phd,
            preferences={int(k): v for k, v in i.preferences.items()},
        )
        for i in payload.instructors
    ]

    return ProblemInstance(
        exams=exams,
        timeslots=timeslots,
        rooms=rooms,
        instructors=instructors,
    )


def serialize_from_payload(payload: InstancePayload) -> dict:
    """Serialize the frontend's own payload into the standard response format."""
    _WEEKDAY = ["Monday", "Tuesday", "Wednesday", "Thursday",
                "Friday", "Saturday", "Sunday"]
    _PSTARTS = ["08:00", "09:30", "11:00", "12:30", "14:00",
                "15:30", "17:00", "18:30", "20:00"]
    _PENDS   = ["09:30", "11:00", "12:30", "14:00", "15:30",
                "17:00", "18:30", "20:00", "21:30"]

    days_seen = sorted({ts.day for ts in payload.timeslots})
    total_weeks = (max(days_seen) // 7 + 1) if days_seen else 1
    wsuf = total_weeks > 1

    return {
        "exams": [
            {
                "id": e.id,
                "code": e.code or f"E{e.id}",
                "name": e.name or f"Exam {e.id}",
                "studentCount": len(e.student_ids),
                "lecturer_id": e.lecturer_id,
                "required_invigilators": e.required_invigilators,
            }
            for e in payload.exams
        ],
        "timeslots": [
            {
                "id": ts.id,
                "day": ts.day,
                "period": ts.period,
                "dayLabel": ts.dayLabel or (
                    f"{_WEEKDAY[ts.day % 7]} W{ts.day // 7 + 1}" if wsuf
                    else _WEEKDAY[ts.day % 7]
                ),
                "periodLabel": ts.periodLabel or (
                    f"{_PSTARTS[ts.period]} – {_PENDS[ts.period]}"
                    if ts.period < len(_PSTARTS) else f"Period {ts.period + 1}"
                ),
            }
            for ts in payload.timeslots
        ],
        "rooms": [
            {
                "id": r.id,
                "capacity": r.capacity,
                "label": r.label or f"R-{str(r.id + 1).zfill(2)}",
            }
            for r in payload.rooms
        ],
        "instructors": [
            {
                "id": i.id,
                "is_phd": i.is_phd,
                "name": i.name or f"{'Prof.' if i.is_phd else 'RA.'} {i.id}",
                "preferences": {str(k): v for k, v in i.preferences.items()},
            }
            for i in payload.instructors
        ],
    }


# ══════════════════════════════════════════════════════════════
#  SHARED SERIALIZER FOR STANDARD TEMPLATE INSTANCES
# ══════════════════════════════════════════════════════════════

def serialize_standard_instance(inst: ProblemInstance, course_codes: Optional[list[str]] = None) -> dict:
    """Serialize a ProblemInstance from standard_parser (no frontend labels)."""
    _WD = ["Monday", "Tuesday", "Wednesday", "Thursday",
           "Friday", "Saturday", "Sunday"]
    _PS = ["08:00", "09:30", "11:00", "12:30", "14:00",
           "15:30", "17:00", "18:30", "20:00"]
    _PE = ["09:30", "11:00", "12:30", "14:00", "15:30",
           "17:00", "18:30", "20:00", "21:30"]

    days = sorted({ts.day for ts in inst.timeslots})
    tw = (max(days) // 7 + 1) if days else 1
    wsuf = tw > 1

    dl = {}
    for d in days:
        n = _WD[d % 7]
        dl[d] = f"{n} W{d // 7 + 1}" if wsuf else n

    pl = {}
    for p in sorted({ts.period for ts in inst.timeslots}):
        pl[p] = (f"{_PS[p]} – {_PE[p]}" if p < len(_PS)
                 else f"Period {p + 1}")

    # Use course codes if provided
    exam_codes = course_codes if course_codes else [f"E{e.id}" for e in inst.exams]

    return {
        "exams": [
            {
                "id": e.id,
                "code": exam_codes[i] if i < len(exam_codes) else f"E{e.id}",
                "name": f"Exam {e.id}",
                "studentCount": len(e.student_ids),
                "lecturer_id": e.lecturer_id,
                "required_invigilators": e.required_invigilators,
            }
            for i, e in enumerate(inst.exams)
        ],
        "timeslots": [
            {"id": ts.id, "day": ts.day, "period": ts.period,
             "dayLabel": dl[ts.day], "periodLabel": pl[ts.period]}
            for ts in inst.timeslots
        ],
        "rooms": [
            {"id": r.id, "capacity": r.capacity,
             "label": f"R-{str(r.id + 1).zfill(2)}"}
            for r in inst.rooms
        ],
        "instructors": [
            {"id": i.id, "is_phd": i.is_phd,
             "name": f"{'Prof.' if i.is_phd else 'RA.'} {i.id}",
             "preferences": {str(k): v for k, v in i.preferences.items()}}
            for i in inst.instructors
        ],
    }


# ══════════════════════════════════════════════════════════════
#  SHARED SOLVER RUNNER
# ══════════════════════════════════════════════════════════════

def run_solver(
    instance: ProblemInstance,
    serialized: dict,
    config: SolverConfig,
) -> SolveResponse:
    """Shared logic: call cp_solver.solve() and format the response."""
    n_exams = len(instance.exams)

    print(
        f"[solve] {n_exams} exams, "
        f"{len(instance.timeslots)} timeslots, "
        f"{len(instance.rooms)} rooms, "
        f"{len(instance.instructors)} instructors | "
        f"S3={'ON' if config.enable_s3 else 'OFF'}, "
        f"S4={'ON' if config.enable_s4 else 'OFF'}, "
        f"time_limit={config.time_limit}s"
    )

    try:
        wall_start = time.perf_counter()
        solution, solver_stats = cp_solve(
            instance=instance,
            w1=config.w1,
            w2=config.w2,
            w3=config.w3,
            w4=config.w4,
            enable_s3=config.enable_s3,
            enable_s4=config.enable_s4,
            time_limit=config.time_limit,
        )
        wall_elapsed = time.perf_counter() - wall_start
    except Exception as e:
        traceback.print_exc()
        return SolveResponse(
            status="failed",
            message=f"Solver crashed: {e}",
            instance=serialized,
            stats={
                "hard_violations": 0, "soft_penalty": 0,
                "objective": None, "solve_time": None,
            },
        )

    # ── Infeasible ───────────────────────────────────────────
    if solution is None:
        return SolveResponse(
            status="infeasible",
            message=(
                f"No feasible solution found for {n_exams} exams "
                f"within {config.time_limit}s. "
                f"Allocated {len(instance.timeslots)} timeslots × "
                f"{len(instance.rooms)} rooms = "
                f"{len(instance.timeslots) * len(instance.rooms)} slots."
            ),
            instance=serialized,
            stats={
                "hard_violations": 0, "soft_penalty": 0,
                "objective": None,
                "solve_time": solver_stats.get("wall_time", wall_elapsed),
            },
        )

    # ── Success ──────────────────────────────────────────────
    solution_dict = solution.to_dict()

    s1 = solver_stats.get("s1_penalty", 0)
    s2 = solver_stats.get("s2_penalty", 0)
    s3 = solver_stats.get("s3_penalty", 0)
    s4 = solver_stats.get("s4_penalty", 0)
    weighted_soft = config.w1 * s1 + config.w2 * s2 + config.w3 * s3 + config.w4 * s4

    stats_for_frontend = {
        "hard_violations": 0,
        "soft_penalty": weighted_soft,
        "objective": solver_stats.get("objective"),
        "solve_time": solver_stats.get("wall_time", wall_elapsed),
        "solver_status": solver_stats.get("status"),
        "s1_penalty": s1,
        "s2_penalty": s2,
        "s3_penalty": s3,
        "s4_penalty": s4,
        "max_load": solver_stats.get("max_load"),
        "min_load": solver_stats.get("min_load"),
        "w1": config.w1,
        "w2": config.w2,
        "w3": config.w3,
        "w4": config.w4,
        "enable_s3": config.enable_s3,
        "enable_s4": config.enable_s4,
        "time_limit": config.time_limit,
        "num_exams": n_exams,
        "num_rooms": len(instance.rooms),
        "num_timeslots": len(instance.timeslots),
        "num_instructors": len(instance.instructors),
    }

    solver_label = solver_stats.get("status", "FEASIBLE")
    placed_count = len(solution_dict.get("exam_time", {}))

    return SolveResponse(
        status=solver_label.lower(),
        message=(
            f"{solver_label}: placed {placed_count}/{n_exams} exams "
            f"with objective {solver_stats.get('objective', '?')} "
            f"in {solver_stats.get('wall_time', wall_elapsed):.2f}s."
        ),
        instance=serialized,
        solution=solution_dict,
        stats=stats_for_frontend,
    )


# ══════════════════════════════════════════════════════════════
#  GENERIC ENDPOINTS
# ══════════════════════════════════════════════════════════════

@app.get("/health")
def health_check():
    return {"status": "ok", "solver": "cp-sat", "version": "4.0.0"}


@app.post("/solve", response_model=SolveResponse)
def solve_endpoint(req: GenericSolveRequest):
    """The primary production endpoint."""
    try:
        instance = hydrate_instance(req.instance)
    except (ValueError, TypeError) as e:
        raise HTTPException(
            status_code=422,
            detail=f"Instance validation failed: {e}",
        )

    serialized = serialize_from_payload(req.instance)
    return run_solver(instance, serialized, req.config)


# ══════════════════════════════════════════════════════════════
#  UPLOAD ENDPOINT — Universal Excel Import
# ══════════════════════════════════════════════════════════════

from data.parsers.standard_parser import parse_standard_template, get_template_metadata
import pandas as pd


@app.post("/upload", response_model=ParseResponse)
async def upload_template(file: UploadFile = File(...)):
    """
    Upload an Excel file in the standard template format.
    Parses it using standard_parser and returns the instance JSON.
    """
    # Validate file extension
    if not file.filename.lower().endswith(".xlsx"):
        raise HTTPException(
            status_code=400,
            detail="Only .xlsx files are accepted. Please upload an Excel file.",
        )

    # Save to temp file and parse
    try:
        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
            content = await file.read()
            tmp.write(content)
            tmp_path = tmp.name

        # Extract course codes for labeling
        enrollments_df = pd.read_excel(tmp_path, sheet_name="Enrollments")
        course_codes = sorted(enrollments_df["Course_Code"].unique().tolist())

        # Parse the template
        instance = parse_standard_template(tmp_path)
        metadata = get_template_metadata(tmp_path)

        # Serialize for frontend
        serialized = serialize_standard_instance(instance, course_codes)

    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=f"Template validation failed: {e}")
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Failed to parse template: {e}")
    finally:
        # Cleanup temp file
        if 'tmp_path' in locals() and os.path.exists(tmp_path):
            os.unlink(tmp_path)

    return ParseResponse(
        status="ok",
        message=(
            f"Parsed {len(instance.exams)} exams, "
            f"{len(instance.rooms)} rooms, "
            f"{len(instance.timeslots)} timeslots, "
            f"{len(instance.instructors)} instructors."
        ),
        instance=serialized,
        metadata=metadata,
    )


# ══════════════════════════════════════════════════════════════
#  OKAN BENCHMARK ENDPOINTS
# ══════════════════════════════════════════════════════════════
 
from data.parsers.okan_parser import parse_okan
 
OKAN_DATA_DIR = Path(__file__).resolve().parent / "data" / "instances" / "anonymusokan"
OKAN_STUDENT_PATH = OKAN_DATA_DIR / "ANON_Ders_Inceleme_Raporu.xlsx"
OKAN_SCHEDULE_PATH = OKAN_DATA_DIR / "ANON_Guz_Final.xlsx"
OKAN_EXAMS_SHEET = "FINAL(8-18 OCAK)"
 
 
class OkanSolveRequest(BaseModel):
    config: SolverConfig = SolverConfig()
 
 
def _parse_okan_benchmark() -> tuple[ProblemInstance, list[str]]:
    """Load and parse the Okan anonymized benchmark via the original okan_parser."""
    if not OKAN_STUDENT_PATH.exists():
        raise FileNotFoundError(
            f"Okan student file not found: {OKAN_STUDENT_PATH}. "
            f"Place ANON_Ders_Inceleme_Raporu.xlsx in data/instances/anonymusokan/"
        )
    if not OKAN_SCHEDULE_PATH.exists():
        raise FileNotFoundError(
            f"Okan schedule file not found: {OKAN_SCHEDULE_PATH}. "
            f"Place ANON_Guz_Final.xlsx in data/instances/anonymusokan/"
        )
 
    instance = parse_okan(
        student_excel_path=str(OKAN_STUDENT_PATH),
        schedule_excel_path=str(OKAN_SCHEDULE_PATH),
        exams_sheet_name=OKAN_EXAMS_SHEET,
    )
 
    # Derive course codes directly from the ProblemInstance.
    # The parser assigns sequential integer IDs; we mirror the
    # anonymized CRS-xxx naming so labels stay meaningful.
    course_codes = [f"CRS-{e.id + 1:03d}" for e in instance.exams]
 
    return instance, course_codes
 
 
@app.post("/benchmark/okan/parse", response_model=ParseResponse)
def okan_benchmark_parse():
    """Parse the Okan University anonymized benchmark dataset."""
    try:
        instance, course_codes = _parse_okan_benchmark()
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=422, detail=f"Parse failed: {e}")
 
    serialized = serialize_standard_instance(instance, course_codes)
 
    metadata = {
        "dataset": "Okan Anon Benchmark",
        "source": "Anonymized Fall Semester — Faculty of Engineering",
        "num_exams": len(instance.exams),
        "num_rooms": len(instance.rooms),
        "num_timeslots": len(instance.timeslots),
        "num_instructors": len(instance.instructors),
    }
 
    return ParseResponse(
        status="ok",
        message=(
            f"Parsed Okan benchmark: {len(instance.exams)} exams, "
            f"{len(instance.rooms)} rooms, "
            f"{len(instance.timeslots)} timeslots, "
            f"{len(instance.instructors)} instructors."
        ),
        instance=serialized,
        metadata=metadata,
    )
 
 
@app.post("/benchmark/okan/solve", response_model=SolveResponse)
def okan_benchmark_solve(req: OkanSolveRequest = OkanSolveRequest()):
    """Parse and solve the Okan University anonymized benchmark dataset."""
    try:
        instance, course_codes = _parse_okan_benchmark()
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=422, detail=f"Parse failed: {e}")
 
    serialized = serialize_standard_instance(instance, course_codes)
    return run_solver(instance, serialized, req.config)


# ══════════════════════════════════════════════════════════════
#  CARTER BENCHMARK ENDPOINTS (preserved from original)
# ══════════════════════════════════════════════════════════════

from data.parsers.carter_parser import parse_carter

CARTER_DATA_DIR = Path(__file__).resolve().parent / "data" / "instances" / "carter"


class CarterBenchmarkConfig(BaseModel):
    dataset: str = "hec-s-92-2"
    periods_per_day: int = 3
    seed: int = 42


class CarterSolveRequest(BaseModel):
    dataset: str = "hec-s-92-2"
    periods_per_day: int = 3
    seed: int = 42
    config: SolverConfig = SolverConfig()


class CarterParseResponse(BaseModel):
    status: str
    message: str
    instance: Optional[dict] = None
    scaling: Optional[dict] = None


def _resolve_carter(dataset: str) -> tuple[Path, Path]:
    crs = CARTER_DATA_DIR / f"{dataset}.crs"
    stu = CARTER_DATA_DIR / f"{dataset}.stu"
    if not crs.exists():
        raise FileNotFoundError(f"Course file not found: {crs}")
    if not stu.exists():
        raise FileNotFoundError(f"Student file not found: {stu}")
    return crs, stu


def _count_exams(crs_path: Path) -> int:
    count = 0
    with open(crs_path) as f:
        for line in f:
            if len(line.strip().split()) >= 2:
                count += 1
    return count


def _auto_scale(n_exams: int, periods_per_day: int) -> dict:
    """Hardcoded academic benchmark values for thesis consistency."""
    n_rooms = 15
    n_instructors = 30
    n_timeslots = 18
    n_days = 6
    enable_s3 = True
    time_limit = 120

    if n_exams > (n_timeslots * n_rooms):
        n_rooms = 40
        n_timeslots = math.ceil(n_exams * 1.5 / 40)
        n_days = math.ceil(n_timeslots / periods_per_day)
        n_instructors = 60
        enable_s3 = False

    return {
        "n_exams": n_exams,
        "n_rooms": n_rooms,
        "n_timeslots": n_timeslots,
        "n_days": n_days,
        "periods_per_day": periods_per_day,
        "slot_capacity": n_timeslots * n_rooms,
        "n_instructors": n_instructors,
        "enable_s3": enable_s3,
        "time_limit": time_limit,
    }


def _parse_carter_dataset(cfg: CarterBenchmarkConfig) -> tuple[ProblemInstance, dict]:
    crs, stu = _resolve_carter(cfg.dataset)
    n_exams = _count_exams(crs)
    scaling = _auto_scale(n_exams, cfg.periods_per_day)

    instance = parse_carter(
        crs_path=str(crs),
        stu_path=str(stu),
        n_timeslots=scaling["n_timeslots"],
        periods_per_day=cfg.periods_per_day,
        n_rooms=scaling["n_rooms"],
        n_instructors=scaling["n_instructors"],
        seed=cfg.seed,
    )
    return instance, scaling


def _serialize_carter_instance(inst: ProblemInstance) -> dict:
    """Serialize a ProblemInstance from carter_parser."""
    _WD = ["Monday", "Tuesday", "Wednesday", "Thursday",
           "Friday", "Saturday", "Sunday"]
    _PS = ["08:00", "09:30", "11:00", "12:30", "14:00",
           "15:30", "17:00", "18:30", "20:00"]
    _PE = ["09:30", "11:00", "12:30", "14:00", "15:30",
           "17:00", "18:30", "20:00", "21:30"]

    days = sorted({ts.day for ts in inst.timeslots})
    tw = (max(days) // 7 + 1) if days else 1
    wsuf = tw > 1

    dl = {}
    for d in days:
        n = _WD[d % 7]
        dl[d] = f"{n} W{d // 7 + 1}" if wsuf else n

    pl = {}
    for p in sorted({ts.period for ts in inst.timeslots}):
        pl[p] = (f"{_PS[p]} – {_PE[p]}" if p < len(_PS)
                 else f"Period {p + 1}")

    return {
        "exams": [
            {"id": e.id, "code": f"E{e.id}", "name": f"Exam {e.id}",
             "studentCount": len(e.student_ids), "lecturer_id": e.lecturer_id,
             "required_invigilators": e.required_invigilators}
            for e in inst.exams
        ],
        "timeslots": [
            {"id": ts.id, "day": ts.day, "period": ts.period,
             "dayLabel": dl[ts.day], "periodLabel": pl[ts.period]}
            for ts in inst.timeslots
        ],
        "rooms": [
            {"id": r.id, "capacity": r.capacity,
             "label": f"R-{str(r.id + 1).zfill(2)}"}
            for r in inst.rooms
        ],
        "instructors": [
            {"id": i.id, "is_phd": i.is_phd,
             "name": f"{'Prof.' if i.is_phd else 'RA.'} {i.id}",
             "preferences": {str(k): v for k, v in i.preferences.items()}}
            for i in inst.instructors
        ],
    }


# Legacy endpoint aliases for backward compatibility
@app.post("/benchmark/parse", response_model=CarterParseResponse)
def benchmark_parse(cfg: CarterBenchmarkConfig = CarterBenchmarkConfig()):
    """Parse a Carter dataset (legacy endpoint, use /benchmark/carter/parse)."""
    return carter_benchmark_parse(cfg)


@app.post("/benchmark/solve", response_model=SolveResponse)
def benchmark_solve(req: CarterSolveRequest = CarterSolveRequest()):
    """Solve a Carter dataset (legacy endpoint, use /benchmark/carter/solve)."""
    return carter_benchmark_solve(req)


@app.post("/benchmark/carter/parse", response_model=CarterParseResponse)
def carter_benchmark_parse(cfg: CarterBenchmarkConfig = CarterBenchmarkConfig()):
    """Parse a Carter benchmark dataset with auto-scaled synthetic entities."""
    try:
        instance, scaling = _parse_carter_dataset(cfg)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=422, detail=f"Parse failed: {e}")

    serialized = _serialize_carter_instance(instance)

    return CarterParseResponse(
        status="ok",
        message=(
            f"Parsed {len(instance.exams)} exams, "
            f"{len(instance.rooms)} rooms, "
            f"{len(instance.timeslots)} timeslots, "
            f"{len(instance.instructors)} instructors (auto-scaled)."
        ),
        instance=serialized,
        scaling=scaling,
    )


@app.post("/benchmark/carter/solve", response_model=SolveResponse)
def carter_benchmark_solve(req: CarterSolveRequest = CarterSolveRequest()):
    """Parse + auto-scale + solve a Carter benchmark dataset."""
    try:
        bcfg = CarterBenchmarkConfig(
            dataset=req.dataset,
            periods_per_day=req.periods_per_day,
            seed=req.seed,
        )
        instance, scaling = _parse_carter_dataset(bcfg)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=422, detail=f"Parse failed: {e}")

    serialized = _serialize_carter_instance(instance)

    effective_config = SolverConfig(
        w1=req.config.w1,
        w2=req.config.w2,
        w3=req.config.w3,
        w4=req.config.w4,
        enable_s3=scaling["enable_s3"] if req.config.enable_s3 is True and scaling.get("enable_s3") is False else req.config.enable_s3,
        enable_s4=req.config.enable_s4,
        time_limit=req.config.time_limit,
    )

    return run_solver(instance, serialized, effective_config)


# ══════════════════════════════════════════════════════════════
#  DEV ENTRYPOINT
# ══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api:app", host="0.0.0.0", port=8000, reload=True)

# ══════════════════════════════════════════════════════════════
#  TEMPLATE DOWNLOAD ENDPOINT
# ══════════════════════════════════════════════════════════════

TEMPLATE_PATH = Path(__file__).resolve().parent / "data" / "instances" / "exam_template.xlsx"


@app.get("/template/download")
def download_template():
    """Serve the blank Excel template as a downloadable attachment."""
    if not TEMPLATE_PATH.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Template file not found on server: {TEMPLATE_PATH.name}",
        )
    return FileResponse(
        path=str(TEMPLATE_PATH),
        filename="exam_template.xlsx",
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )