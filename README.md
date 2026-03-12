# University Exam Timetabling System (CSP)

A Constraint Satisfaction Problem (CSP) based system that schedules university exams into timeslots and rooms without conflicts, while considering soft preferences like instructor workload fairness and time preferences.

## Problem Definition

Scheduling university exams is a real-world combinatorial optimization problem. Given a set of exams, timeslots, rooms, and instructors, the goal is to find an assignment that satisfies all hard constraints and minimizes penalties from soft constraints.

### CSP Formulation

The problem is formally defined as **CSP = (X, D, C)** where:

- **Variables (X):** Each exam `e` has three decision variables:
  - `X_e ∈ T` → timeslot assignment
  - `Y_e ∈ R` → room assignment  
  - `Z_{e,i} ∈ {0,1}` → invigilator assignment

- **Domains (D):** All available timeslots, rooms, and instructors.

- **Constraints (C):** Six hard constraints (must be satisfied) and three soft constraints (optimization goals).

### Hard Constraints

| ID | Constraint | Formula | Description |
|----|-----------|---------|-------------|
| H1 | No Student Time Conflict | `students(e_a) ∩ students(e_b) ≠ ∅ → X_ea ≠ X_eb` | Two exams sharing a student cannot be in the same timeslot |
| H2 | Room Capacity | `\|students(e)\| ≤ capacity(Y_e)` | Exam's student count must fit in the assigned room |
| H3 | No Room Clash | `Y_ea = Y_eb → X_ea ≠ X_eb` | Same room cannot host two exams at the same timeslot |
| H4 | Lecturer Conflict | `lecturer(e) = i → Z_{e',i} = 0 if X_{e'} = X_e` | PhD instructor's own exam and invigilation cannot overlap |
| H5 | No Double Invigilation | `Σ_{e:X_e=t} Z_{e,i} ≤ 1` | An instructor cannot invigilate two exams in the same slot |
| H6 | Minimum Invigilators | `Σ_i Z_{e,i} ≥ required(e)` | Each exam must have the required number of invigilators |

### Soft Constraints

| ID | Constraint | Description |
|----|-----------|-------------|
| S1 | Instructor Time Preference | Minimize assignments to unwanted timeslots |
| S2 | Workload Fairness | Minimize variance in invigilation load across instructors |
| S3 | Avoid Consecutive Invigilation | Penalize back-to-back invigilation assignments |

### Multi-Objective Function

`F = w1 * penalty1 + w2 * penalty2 + w3 * penalty3`

Where `w1`, `w2`, `w3` are tunable weights for each soft constraint.

## Project Structure

```
csp-exam-timetabling/
├── data/
│   ├── generators/
│   │   └── synthetic.py        # Synthetic instance generator
│   └── instances/              # Generated test instances (JSON)
│
├── src/
│   ├── models/
│   │   ├── domain.py           # Exam, TimeSlot, Room, Instructor, ProblemInstance
│   │   └── solution.py         # Solution dataclass with serialization
│   │
│   ├── constraints/
│   │   ├── hard.py             # H1-H6 independent constraint validators
│   │   └── soft.py             # S1-S3 penalty functions (planned)
│   │
│   ├── solvers/
│   │   ├── backtracking.py     # Baseline: manual backtracking (Week 2)
│   │   └── cp_solver.py        # Production: OR-Tools CP-SAT solver (Week 3-4)
│   │
│   └── utils/
│       ├── conflict_graph.py   # Student-based exam conflict graph builder
│       └── io.py               # JSON serialization helpers (planned)
│
├── tests/                      # Unit tests
├── experiments/                # Benchmark results and analysis (Week 8)
├── main.py                     # Entry point — generate, solve, display
├── requirements.txt
└── README.md
```

## Two Solver Approach

This project implements two solvers to demonstrate the progression from fundamental CSP algorithms to production-grade constraint programming:

### 1. Manual Backtracking (`src/solvers/backtracking.py`)

A recursive depth-first search written from scratch — no libraries, no black boxes. This serves as both a learning exercise and a baseline for performance comparison.

How it works:
1. Pick the next unassigned exam (by index order)
2. Try every (timeslot, room) pair
3. Run H1, H2, H3 partial checks — if any fails, skip this pair
4. If all pass, commit the assignment and recurse to the next exam
5. If recursion fails, undo the assignment (backtrack) and try the next pair

Limitations: exponential worst-case complexity, no propagation, no heuristics. Dense conflict graphs cause the solver to time out. Handles H1-H3 only (timeslot and room assignment).

### 2. OR-Tools CP-SAT (`src/solvers/cp_solver.py`)

A declarative constraint programming solver using Google OR-Tools. Instead of writing the search algorithm, we declare variables and constraints, and the solver handles search strategy, constraint propagation (AC-3, forward checking), and adaptive heuristics (MRV, domain ordering) internally.

How constraints are modeled:
- **H1** — conflict graph edges become pairwise `!=` constraints on timeslot variables
- **H2** — `add_allowed_assignments` restricts each exam's room to capacity-sufficient options
- **H3** — combined `timeslot * num_rooms + room` variable with `add_all_different`
- **H4 & H5** — reified boolean `same_slot` variables with `only_enforce_if` for conditional constraints
- **H6** — `sum(boolean_vars) >= required` on invigilator assignment variables

Handles all six hard constraints (H1-H6) including full invigilator assignment.

## Implementation Details

### Data Model (`src/models/`)

Every mathematical set in the CSP formulation maps directly to a Python dataclass:

- **Exam** → represents `E = {e1, ..., en}` with fields: `id`, `student_ids` (set for O(1) intersection), `lecturer_id`, `required_invigilators`
- **TimeSlot** → represents `T = {t1, ..., tp}` with fields: `id`, `day`, `period` (separate day/period enables consecutive-slot detection for S3)
- **Room** → represents `R = {r1, ..., rm}` with fields: `id`, `capacity`
- **Instructor** → represents `I = {i1, ..., ik}` with fields: `id`, `is_phd` (dual-role flag for H4), `preferences` (dict for S1)
- **ProblemInstance** → aggregates all sets, validates referential integrity (e.g., every exam's lecturer must exist in the instructor list)
- **Solution** → stores decision variables as dicts: `exam_time`, `exam_room`, `assigned_invigilators`

All dataclasses include `__post_init__` validation to catch invalid data early (negative capacities, empty student sets, infeasible slot/room ratios).

### Conflict Graph (`src/utils/conflict_graph.py`)

Precomputes which exam pairs share students, stored as an adjacency list (`dict[int, set[int]]`). This avoids recalculating set intersections during solving. The graph is undirected and built once in O(n² · s) time where n = number of exams, s = average student set size.

Used by both solvers: the backtracking solver uses it for H1 partial checks, and the CP-SAT solver converts its edges into pairwise inequality constraints.

### Independent Validation (`src/constraints/hard.py`)

Each hard constraint has a standalone validation function that checks a complete solution independently of the solver that produced it. This provides a second layer of correctness verification — the solver finds the solution, and the validator confirms it satisfies all constraints.

### Synthetic Data Generator (`data/generators/synthetic.py`)

Generates controlled test instances with tunable parameters:

- `n_exams`, `n_timeslots`, `n_rooms`, `n_instructors`, `n_students`
- `periods_per_day` — for realistic day/period structure
- `seed` — reproducibility for academic experiments

Student enrollment uses a student-centric approach: each student is randomly assigned to `k` exams, which naturally creates a realistic conflict structure. Edge cases are handled: exams with no students get a random assignment, and at least one PhD instructor is guaranteed.

Key insight from development: the density of the conflict graph is highly sensitive to the student-to-exam ratio. With too few exams or too many enrollments per student, the graph becomes complete (K_n), making the problem infeasible for the given number of timeslots.

## Usage

### Setup

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Run

```bash
python main.py
```

### Example Output

```
=== Solution Found ===

Exam  | Timeslot | Room | Invigilators
------+----------+------+-------------
  0   |    4     |  2   | 5
  1   |    3     |  3   | 0
  2   |    5     |  1   | 0
  3   |    4     |  3   | 0
  ...

Total exams: 20
Timeslots used: 7/10
Rooms used: 4/4
```

### Adjusting Parameters

In `main.py`, modify the `generate_instance()` call:

```python
instance = generate_instance(
    n_exams=20,        # number of exams
    n_timeslots=10,    # available timeslots
    n_rooms=4,         # available rooms
    n_instructors=8,   # teaching staff
    n_students=60,     # student population
    seed=42            # for reproducibility
)
```

## Current Status

### Completed (Weeks 1-4)
- CSP formulation with 6 hard constraints and 3 soft constraints
- Full data model with validation and serialization
- Conflict graph construction
- Synthetic data generator with reproducible seeds
- Baseline backtracking solver written from scratch (H1-H3, timeslot + room)
- Full and partial constraint checking for H1-H6
- OR-Tools CP-SAT solver with all 6 hard constraints (H1-H6)
- Complete invigilator assignment via boolean decision variables
- Reified constraints for conditional logic (same-slot detection)
- Solution display with exam, timeslot, room, and invigilator mapping

### Planned
- **Week 4 (remaining):** Large instance testing + performance benchmarks (backtracking vs CP-SAT)
- **Week 5:** Visualization (calendar/timetable view)
- **Week 6:** Soft constraints (S1-S3) as objective function in CP-SAT
- **Week 7:** Web or desktop interface
- **Week 8:** Report + analysis with experimental benchmarks
- **Week 9:** Final presentation

## Known Limitations

- **Backtracking solver** is exponential in the worst case and only handles H1-H3. Dense conflict graphs make it impractical. It exists as a baseline for comparison and to demonstrate understanding of fundamental CSP algorithms.
- **Conflict graph density** is sensitive to generator parameters. The student-to-exam ratio must be carefully chosen to produce feasible instances with realistic sparsity.
- **Soft constraints** (S1-S3) are not yet integrated into the CP-SAT solver. Currently the solver finds any feasible solution without optimization.
- **Real university data** integration is planned but not yet implemented. The system currently runs on synthetic data.

## Dependencies

- **Python 3.10+**
- **ortools** — Google OR-Tools CP-SAT constraint programming solver
- **pytest** — unit testing
- **numpy** — statistical analysis for experiments
- **matplotlib** — performance graphs and visualizations
- **networkx** — conflict graph visualization

## Research Context

This project explores a multi-objective CSP framework for university exam timetabling that balances dual-role PhD instructor conflicts with invigilator workload fairness. The novelty lies in the combination of H4 (PhD dual-role conflict) and S2 (workload fairness), which are rarely modeled together in the exam timetabling literature.

The two-solver approach (manual backtracking vs OR-Tools CP-SAT) enables direct comparison between a naive baseline and a production-grade solver, demonstrating the impact of constraint propagation and heuristics on solving performance.

## License

Academic use.