"""
FastAPI backend for the University Exam Timetabling System.

Architecture (v3 — decoupled):
    The API has two distinct data paths that share ZERO logic:

    ┌─────────────────────────────────────────────────────┐
    │  GENERIC PATH (production)                          │
    │                                                     │
    │  POST /solve                                        │
    │    Frontend sends full instance payload (exams,     │
    │    rooms, timeslots, instructors) → API hydrates    │
    │    domain objects → passes to cp_solver → returns   │
    │    solution. Zero data generation. Zero scaling.    │
    │    The API is a pure, stateless conduit.            │
    └─────────────────────────────────────────────────────┘

    ┌─────────────────────────────────────────────────────┐
    │  BENCHMARK PATH (testing only)                      │
    │                                                     │
    │  POST /benchmark/parse                              │
    │  POST /benchmark/solve                              │
    │    Reads Carter .crs/.stu files, auto-scales        │
    │    synthetic rooms/timeslots/instructors, and        │
    │    feeds the generated ProblemInstance to the same   │
    │    solver. This path exists solely for academic      │
    │    benchmark testing and will not be used once       │
    │    real Excel uploads are implemented.               │
    └─────────────────────────────────────────────────────┘

    Both paths share:
    - The same SolveResponse schema
    - The same serialize_instance() output format
    - The same run_solver() helper that wraps cp_solver.solve()

Start with:
    uvicorn api:app --reload --port 8000
"""

from __future__ import annotations

import math
import time
import traceback
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
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
    version="3.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ══════════════════════════════════════════════════════════════
#  SHARED SCHEMAS (used by both paths)
# ══════════════════════════════════════════════════════════════

class SolverConfig(BaseModel):
    """Solver tuning knobs — shared by generic and benchmark paths."""
    w1: int = 1
    w2: int = 5
    w3: int = 2
    w4: int = 3
    enable_s3: bool = True
    enable_s4: bool = True
    time_limit: int = 120


class SolveResponse(BaseModel):
    """Shared response format — identical for both paths."""
    status: str
    message: str
    instance: Optional[dict] = None
    solution: Optional[dict] = None
    stats: Optional[dict] = None


# ══════════════════════════════════════════════════════════════
#  GENERIC PATH — Pydantic schemas that mirror domain.py
#
#  These are the frontend's contract. When a user uploads an
#  Excel file, the frontend parses it into these exact shapes
#  and POSTs them to /solve. The API trusts this data blindly.
# ══════════════════════════════════════════════════════════════

class ExamPayload(BaseModel):
    id: int
    student_ids: list[int]
    lecturer_id: int
    required_invigilators: int = 1

    # Optional display fields (passed through to response, not used by solver)
    code: Optional[str] = None
    name: Optional[str] = None


class TimeslotPayload(BaseModel):
    id: int
    day: int
    period: int

    # Optional display labels (passed through to response)
    dayLabel: Optional[str] = None
    periodLabel: Optional[str] = None


class RoomPayload(BaseModel):
    id: int
    capacity: int

    # Optional display label
    label: Optional[str] = None


class InstructorPayload(BaseModel):
    id: int
    is_phd: bool
    preferences: dict[int, bool]    # timeslot_id → available?

    # Optional display name
    name: Optional[str] = None


class InstancePayload(BaseModel):
    """
    Complete problem instance from the frontend.
    Maps 1:1 to domain.py's ProblemInstance, but as JSON.
    """
    exams: list[ExamPayload]
    timeslots: list[TimeslotPayload]
    rooms: list[RoomPayload]
    instructors: list[InstructorPayload]


class GenericSolveRequest(BaseModel):
    """
    The primary /solve endpoint payload.
    Contains the full instance + solver configuration.
    """
    instance: InstancePayload
    config: SolverConfig = SolverConfig()


# ══════════════════════════════════════════════════════════════
#  HYDRATION — JSON payloads → domain.py dataclass objects
#
#  This is the only translation layer. It converts Pydantic
#  models into the exact types cp_solver.py expects.
#  If domain.py's __post_init__ validation fails, the error
#  propagates as a 422 to the frontend — no silent swallowing.
# ══════════════════════════════════════════════════════════════

def hydrate_instance(payload: InstancePayload) -> ProblemInstance:
    """
    Convert frontend JSON → domain.py dataclass objects.
    Raises ValueError if domain validation fails (e.g., insufficient
    room capacity, missing lecturers, etc.)
    """
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
            preferences=i.preferences,
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
    """
    Serialize the frontend's own payload into the standard response
    format, preserving any display labels the frontend provided.
    Falls back to generated labels for missing fields.
    """
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
            }
            for i in payload.instructors
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
    """
    Shared logic: call cp_solver.solve() and format the response.
    Used by both the generic and benchmark paths.
    """
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
    return {"status": "ok", "solver": "cp-sat", "version": "3.0.0"}


@app.post("/solve", response_model=SolveResponse)
def solve_endpoint(req: GenericSolveRequest):
    """
    The primary production endpoint.

    Accepts a complete problem instance from the frontend,
    hydrates it into domain objects, solves, and returns.
    No file I/O. No synthetic generation. No auto-scaling.
    The API trusts the data it receives.
    """

    # ── Hydrate JSON → domain.py objects ─────────────────────
    try:
        instance = hydrate_instance(req.instance)
    except (ValueError, TypeError) as e:
        raise HTTPException(
            status_code=422,
            detail=f"Instance validation failed: {e}",
        )

    # ── Serialize for the response (preserves frontend labels) ─
    serialized = serialize_from_payload(req.instance)

    # ── Solve ────────────────────────────────────────────────
    return run_solver(instance, serialized, req.config)


# ══════════════════════════════════════════════════════════════
#  BENCHMARK ENDPOINTS  (Carter-specific, testing only)
#
#  Everything below this line is isolated from the generic path.
#  It can be removed entirely when Carter testing is complete
#  without affecting any production functionality.
# ══════════════════════════════════════════════════════════════

from data.parsers.carter_parser import parse_carter   # noqa: E402

CARTER_DATA_DIR = Path(__file__).resolve().parent / "data" / "instances" / "carter"


class BenchmarkConfig(BaseModel):
    dataset: str = "hec-s-92-2"
    periods_per_day: int = 3
    seed: int = 42


class BenchmarkSolveRequest(BaseModel):
    dataset: str = "hec-s-92-2"
    periods_per_day: int = 3
    seed: int = 42
    config: SolverConfig = SolverConfig()


class BenchmarkParseResponse(BaseModel):
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
    """
    HARDCODED academic benchmark values for thesis consistency.
    Ensures that frontend tests use the exact same control variables 
    (rooms, instructors, timeslots) as the previous backend-only tests.
    """
    # Original 'hec-s-92' benchmark values as defined in the README:
    n_rooms = 15
    n_instructors = 30
    n_timeslots = 18  # (6 days x 3 periods)
    n_days = 6
    enable_s3 = True
    time_limit = 120

    # Safety Fallback: If a massive dataset like 'pur-s-93' (2400 exams) is 
    # selected, it physically cannot fit into the fixed 18x15=270 slots. 
    # Dynamically scale only for these extreme cases to prevent API crashes:
    if n_exams > (n_timeslots * n_rooms):
        n_rooms = 40
        n_timeslots = math.ceil(n_exams * 1.5 / 40)
        n_days = math.ceil(n_timeslots / periods_per_day)
        n_instructors = 60
        enable_s3 = False  # Disable S3 (consecutive exams) for massive datasets

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


def _parse_carter_dataset(cfg: BenchmarkConfig) -> tuple[ProblemInstance, dict]:
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


def _serialize_benchmark_instance(inst: ProblemInstance) -> dict:
    """Serialize a ProblemInstance that came from carter_parser (no frontend labels)."""
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
             "name": f"{'Prof.' if i.is_phd else 'RA.'} {i.id}"}
            for i in inst.instructors
        ],
    }


@app.post("/benchmark/parse", response_model=BenchmarkParseResponse)
def benchmark_parse(cfg: BenchmarkConfig = BenchmarkConfig()):
    """Parse a Carter dataset with auto-scaled synthetic entities."""
    try:
        instance, scaling = _parse_carter_dataset(cfg)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=422, detail=f"Parse failed: {e}")

    serialized = _serialize_benchmark_instance(instance)

    return BenchmarkParseResponse(
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


@app.post("/benchmark/solve", response_model=SolveResponse)
def benchmark_solve(req: BenchmarkSolveRequest = BenchmarkSolveRequest()):
    """Parse + auto-scale + solve a Carter benchmark dataset."""
    try:
        bcfg = BenchmarkConfig(
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

    serialized = _serialize_benchmark_instance(instance)

    # Apply auto-scaled solver knobs if not manually set
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