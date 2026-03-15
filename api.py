"""
FastAPI bridge between the React dashboard and the CP-SAT solver.

Endpoints:
    GET  /health    →  connectivity check
    POST /parse     →  parse Carter dataset → return serialized ProblemInstance
    POST /solve     →  parse + solve → return instance + solution + stats

The /parse endpoint lets the frontend hydrate its UI (stat cards, grid
headers) immediately on import, before the user clicks "Run Solver".
The /solve response also includes the full instance so the frontend's
problemData stays in sync even if config changes between calls.

Response shapes are dictated by the React frontend — see inline docs.

Start with:
    uvicorn api:app --reload --port 8000
"""

from __future__ import annotations

import time
import traceback
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from data.parsers.carter_parser import parse_carter
from src.solvers.cp_solver import solve
from src.models.domain import ProblemInstance


# ══════════════════════════════════════════════════════════════
#  APP SETUP
# ══════════════════════════════════════════════════════════════

app = FastAPI(
    title="UETP Solver API",
    description="University Exam Timetabling — CP-SAT solver backend",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:5174",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ══════════════════════════════════════════════════════════════
#  REQUEST / RESPONSE SCHEMAS
# ══════════════════════════════════════════════════════════════

class DatasetConfig(BaseModel):
    """
    Shared config for both /parse and /solve.
    Every field has a default so the frontend can POST {} and get results.
    """
    dataset: str = "hec-s-92-2"
    n_timeslots: int = 45
    periods_per_day: int = 3
    n_rooms: int = 15
    n_instructors: int = 30
    seed: int = 42


class SolveRequest(DatasetConfig):
    """Extends DatasetConfig with solver-specific knobs."""
    w1: int = 1
    w2: int = 5
    w3: int = 2
    enable_s3: bool = True
    time_limit: int = 120


class ParseResponse(BaseModel):
    status: str
    message: str
    instance: Optional[dict] = None


class SolveResponse(BaseModel):
    status: str
    message: str
    instance: Optional[dict] = None
    solution: Optional[dict] = None
    stats: Optional[dict] = None


# ══════════════════════════════════════════════════════════════
#  INSTANCE SERIALIZER
#
#  Converts a ProblemInstance (Python dataclasses with sets,
#  custom objects) into a plain JSON dict matching the exact
#  shape the React frontend expects:
#
#    instance.exams[]:       { id, code, name, studentCount, lecturer_id, required_invigilators }
#    instance.timeslots[]:   { id, day, period, dayLabel, periodLabel }
#    instance.rooms[]:       { id, capacity, label }
#    instance.instructors[]: { id, is_phd, name }
#
#  Carter datasets have only numeric IDs — we generate
#  human-readable labels here so the React UI stays clean.
# ══════════════════════════════════════════════════════════════

_DAY_NAMES = [
    "Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
    "Saturday", "Sunday",
]

_PERIOD_STARTS = [
    "08:00", "09:30", "11:00", "12:30", "14:00",
    "15:30", "17:00", "18:30", "20:00",
]
_PERIOD_ENDS = [
    "09:30", "11:00", "12:30", "14:00", "15:30",
    "17:00", "18:30", "20:00", "21:30",
]


def serialize_instance(inst: ProblemInstance) -> dict:
    """
    Single function that converts a ProblemInstance → frontend JSON.
    All sets become lists, all labels are generated, all IDs are ints.
    """

    # ── Derive unique days & periods from timeslot data ──
    days_seen = sorted({ts.day for ts in inst.timeslots})
    periods_seen = sorted({ts.period for ts in inst.timeslots})

    day_label_map = {}
    for d in days_seen:
        day_label_map[d] = _DAY_NAMES[d] if d < len(_DAY_NAMES) else f"Day {d + 1}"

    period_label_map = {}
    for p in periods_seen:
        if p < len(_PERIOD_STARTS):
            period_label_map[p] = f"{_PERIOD_STARTS[p]} – {_PERIOD_ENDS[p]}"
        else:
            period_label_map[p] = f"Period {p + 1}"

    # ── Timeslots ──
    timeslots = [
        {
            "id": ts.id,
            "day": ts.day,
            "period": ts.period,
            "dayLabel": day_label_map[ts.day],
            "periodLabel": period_label_map[ts.period],
        }
        for ts in inst.timeslots
    ]

    # ── Rooms ──
    rooms = [
        {
            "id": r.id,
            "capacity": r.capacity,
            "label": f"R-{str(r.id + 1).zfill(2)}",
        }
        for r in inst.rooms
    ]

    # ── Exams ──
    exams = [
        {
            "id": e.id,
            "code": f"E{e.id}",
            "name": f"Exam {e.id}",
            "studentCount": len(e.student_ids),
            "lecturer_id": e.lecturer_id,
            "required_invigilators": e.required_invigilators,
        }
        for e in inst.exams
    ]

    # ── Instructors ──
    instructors = [
        {
            "id": i.id,
            "is_phd": i.is_phd,
            "name": f"{'Prof.' if i.is_phd else 'RA.'} {i.id}",
        }
        for i in inst.instructors
    ]

    return {
        "exams": exams,
        "timeslots": timeslots,
        "rooms": rooms,
        "instructors": instructors,
    }


# ══════════════════════════════════════════════════════════════
#  DATASET PATH RESOLVER
# ══════════════════════════════════════════════════════════════

CARTER_DATA_DIR = Path(__file__).resolve().parent / "data" / "instances" / "carter"


def resolve_carter_paths(dataset: str) -> tuple[Path, Path]:
    crs_path = CARTER_DATA_DIR / f"{dataset}.crs"
    stu_path = CARTER_DATA_DIR / f"{dataset}.stu"

    if not crs_path.exists():
        raise FileNotFoundError(
            f"Course file not found: {crs_path}\n"
            f"Place your .crs file in {CARTER_DATA_DIR}/"
        )
    if not stu_path.exists():
        raise FileNotFoundError(
            f"Student file not found: {stu_path}\n"
            f"Place your .stu file in {CARTER_DATA_DIR}/"
        )
    return crs_path, stu_path


def parse_dataset(cfg: DatasetConfig) -> ProblemInstance:
    """Shared helper: resolve files + parse into ProblemInstance."""
    crs_path, stu_path = resolve_carter_paths(cfg.dataset)
    return parse_carter(
        crs_path=str(crs_path),
        stu_path=str(stu_path),
        n_timeslots=cfg.n_timeslots,
        periods_per_day=cfg.periods_per_day,
        n_rooms=cfg.n_rooms,
        n_instructors=cfg.n_instructors,
        seed=cfg.seed,
    )


# ══════════════════════════════════════════════════════════════
#  ENDPOINTS
# ══════════════════════════════════════════════════════════════

@app.get("/health")
def health_check():
    return {"status": "ok", "solver": "cp-sat"}


@app.post("/parse", response_model=ParseResponse)
def parse_endpoint(cfg: DatasetConfig = DatasetConfig()):
    """
    Parse a Carter dataset and return the serialized ProblemInstance.
    Called by the frontend's "Upload & Parse" button so stat cards
    and grid headers can populate before the user runs the solver.
    """
    try:
        instance = parse_dataset(cfg)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=422,
            detail=f"Failed to parse dataset '{cfg.dataset}': {e}",
        )

    serialized = serialize_instance(instance)

    return ParseResponse(
        status="ok",
        message=(
            f"Parsed {len(instance.exams)} exams, "
            f"{len(instance.rooms)} rooms, "
            f"{len(instance.timeslots)} timeslots, "
            f"{len(instance.instructors)} instructors."
        ),
        instance=serialized,
    )


@app.post("/solve", response_model=SolveResponse)
def solve_endpoint(req: SolveRequest = SolveRequest()):
    """
    Parse + solve. Returns the full instance alongside the solution
    so the frontend's problemData is always in sync with the solver's
    actual ProblemInstance — the single source of truth.
    """

    # ── Step 1: Parse ────────────────────────────────────────
    try:
        instance = parse_dataset(req)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=422,
            detail=f"Failed to parse dataset '{req.dataset}': {e}",
        )

    serialized_instance = serialize_instance(instance)

    # ── Step 2: Solve ────────────────────────────────────────
    try:
        wall_start = time.perf_counter()
        solution, solver_stats = solve(
            instance=instance,
            w1=req.w1,
            w2=req.w2,
            w3=req.w3,
            enable_s3=req.enable_s3,
            time_limit=req.time_limit,
        )
        wall_elapsed = time.perf_counter() - wall_start
    except Exception as e:
        traceback.print_exc()
        return SolveResponse(
            status="failed",
            message=f"Solver crashed: {e}",
            instance=serialized_instance,
            stats={
                "hard_violations": 0, "soft_penalty": 0,
                "objective": None, "solve_time": None,
            },
        )

    # ── Step 3a: Infeasible ──────────────────────────────────
    if solution is None:
        return SolveResponse(
            status="infeasible",
            message=(
                f"No feasible solution found within {req.time_limit}s. "
                "Try increasing the time limit, adding more rooms/timeslots, "
                "or relaxing constraints."
            ),
            instance=serialized_instance,
            stats={
                "hard_violations": 0, "soft_penalty": 0,
                "objective": None,
                "solve_time": solver_stats.get("wall_time", wall_elapsed),
            },
        )

    # ── Step 3b: Success ─────────────────────────────────────
    solution_dict = solution.to_dict()

    s1 = solver_stats.get("s1_penalty", 0)
    s2 = solver_stats.get("s2_penalty", 0)
    s3 = solver_stats.get("s3_penalty", 0)
    weighted_soft = req.w1 * s1 + req.w2 * s2 + req.w3 * s3

    stats_for_frontend = {
        "hard_violations": 0,
        "soft_penalty": weighted_soft,
        "objective": solver_stats.get("objective"),
        "solve_time": solver_stats.get("wall_time", wall_elapsed),
        "solver_status": solver_stats.get("status"),
        "s1_penalty": s1,
        "s2_penalty": s2,
        "s3_penalty": s3,
        "max_load": solver_stats.get("max_load"),
        "min_load": solver_stats.get("min_load"),
        "w1": req.w1,
        "w2": req.w2,
        "w3": req.w3,
        "num_exams": len(instance.exams),
        "num_rooms": len(instance.rooms),
        "num_timeslots": len(instance.timeslots),
        "num_instructors": len(instance.instructors),
    }

    solver_label = solver_stats.get("status", "FEASIBLE")
    placed_count = len(solution_dict.get("exam_time", {}))

    return SolveResponse(
        status=solver_label.lower(),
        message=(
            f"{solver_label}: placed {placed_count}/{len(instance.exams)} exams "
            f"with objective {solver_stats.get('objective', '?')} "
            f"in {solver_stats.get('wall_time', wall_elapsed):.2f}s."
        ),
        instance=serialized_instance,
        solution=solution_dict,
        stats=stats_for_frontend,
    )


# ══════════════════════════════════════════════════════════════
#  DEV ENTRYPOINT
# ══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api:app", host="0.0.0.0", port=8000, reload=True)