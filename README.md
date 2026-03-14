# University Exam Timetabling System (CSP/CSOP)

A Constraint Satisfaction Optimization Problem (CSOP) based system that schedules university exams into timeslots and rooms without conflicts, while optimizing for instructor workload fairness, time preferences, and scheduling comfort.

## Problem Definition

Scheduling university exams is a real-world combinatorial optimization problem classified as NP-hard. Given a set of exams, timeslots, rooms, and instructors, the goal is to find an assignment that satisfies all hard constraints and minimizes penalties from soft constraints.

### CSP Formulation

The problem is formally defined as **CSP = (X, D, C)** with an optimization extension **CSOP = (X, D, C, F)** where:

- **Variables (X):** Each exam `e` has three decision variables:
  - `X_e ∈ T` → timeslot assignment
  - `Y_e ∈ R` → room assignment
  - `Z_{e,i} ∈ {0,1}` → invigilator assignment

- **Domains (D):** All available timeslots, rooms, and instructors.

- **Constraints (C):** Six hard constraints (must be satisfied) and three soft constraints (optimization goals).

- **Objective (F):** Weighted sum of soft constraint penalties to minimize.

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

| ID | Constraint | OR-Tools Technique | Description |
|----|-----------|-------------------|-------------|
| S1 | Instructor Time Preference | `add_element` + `add_min_equality` (AND gate) | Minimize assignments to unwanted timeslots |
| S2 | Workload Fairness (Min-Max) | `add_max_equality` / `add_min_equality` on loads | Minimize gap between busiest and least busy instructor |
| S3 | Avoid Consecutive Invigilation | Reified slot-activity detection + AND | Penalize back-to-back invigilation assignments |

### Multi-Objective Function

`F = w1 * penalty_S1 + w2 * penalty_S2 + w3 * penalty_S3`

Where `w1=1`, `w2=5`, `w3=2` are tunable weights. S2 has the highest weight because fairness is the primary optimization goal of this framework.

**Note on S2:** The original formulation uses variance `Σ(load(i) - L̄)²`, but CP-SAT doesn't support quadratic expressions. We use a Min-Max proxy instead: `minimize(max_load - min_load)`. This is actually a stronger fairness guarantee — it directly prevents any single instructor from being disproportionately burdened.

## Project Structure

```
csp-exam-timetabling/
├── data/
│   ├── generators/
│   │   └── synthetic.py        # Synthetic instance generator
│   ├── parsers/
│   │   └── carter_parser.py    # Carter benchmark dataset parser
│   └── instances/
│       └── carter/             # Carter benchmark files (.crs, .stu)
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
│   │   └── cp_solver.py        # Production: OR-Tools CP-SAT with H1-H6 + S1-S3
│   │
│   └── utils/
│       ├── conflict_graph.py   # Student-based exam conflict graph builder
│       └── io.py               # JSON serialization helpers
│
├── tests/                      # Unit tests
├── experiments/                # Benchmark results and analysis
├── main.py                     # Entry point — parse, solve, display, analyze
├── requirements.txt
└── README.md
```

## Two Solver Approach

### 1. Manual Backtracking — Baseline (`src/solvers/backtracking.py`)

A recursive depth-first search written from scratch to demonstrate understanding of fundamental CSP algorithms. No external libraries used for the search.

How it works:
1. Pick the next unassigned exam (by index order)
2. Try every (timeslot, room) pair
3. Run H1, H2, H3 partial checks — if any fails, skip this pair
4. If all pass, commit the assignment and recurse to the next exam
5. If recursion fails, undo the assignment (backtrack) and try the next pair

Limitations: exponential worst-case complexity, no propagation, no heuristics, handles H1-H3 only. Exists as a baseline for performance comparison.

### 2. OR-Tools CP-SAT — Production Solver (`src/solvers/cp_solver.py`)

A declarative constraint programming solver using Google OR-Tools CP-SAT. Handles all hard constraints (H1-H6) and soft constraints (S1-S3) with optimization.

OR-Tools CP-SAT internally uses:
- Constraint propagation (AC-3, forward checking) — eliminates infeasible values early
- Search heuristics (MRV, domain ordering) — picks the most constrained variable first
- Large Neighborhood Search (LNS) — for optimization after finding feasible solutions
- Branch and bound — for proving optimality

How constraints are modeled:
- **H1** — conflict graph edges → pairwise `!=` on timeslot variables
- **H2** — `add_allowed_assignments` restricts rooms to capacity-sufficient options
- **H3** — combined `timeslot * num_rooms + room` variable + `add_all_different`
- **H4 & H5** — reified `same_slot` booleans with `only_enforce_if`
- **H6** — `sum(boolean_vars) >= required`
- **S1** — `add_element` for preference lookup + `add_min_equality` as AND gate
- **S2** — `add_max_equality` / `add_min_equality` on instructor load variables
- **S3** — per-slot activity detection via reification + AND for consecutive penalty

## Benchmark Results

Tested on the Carter benchmark dataset (Toronto instances), the standard benchmark for exam timetabling research.

### hec-s-92 (80 exams, 2823 students, 18 timeslots)

| Configuration | Status | Objective | S1 | S2 (gap) | S3 | Time |
|--------------|--------|-----------|-----|----------|-----|------|
| S3 disabled  | OPTIMAL | 0 | 0 | 0 (9-9) | — | 14.3s |
| S3 enabled   | FEASIBLE | 27 | 12 | 1 (8-7) | 5 | 120s (timeout) |

**Key findings:**
- With S3 disabled, the solver achieves **perfect fairness** (all 30 instructors assigned exactly 9 exams) with zero preference violations in 14 seconds.
- S3 adds significant computational cost (8x slower) due to the large number of reified variables, but still produces near-optimal workload distribution.
- The Min-Max fairness objective successfully flattens the workload curve across all instructors.

## Carter Benchmark Dataset

The project supports the Toronto benchmark instances, the most widely used benchmark suite in exam timetabling literature.

| Instance | Exams | Students | Known Chromatic Bound |
|----------|-------|----------|-----------------------|
| hec-s-92 | 80 | 2,823 | 18 |
| sta-f-83 | 138 | 549 | 13 |
| yor-f-83 | 180 | 919 | 21 |
| ear-f-83 | 189 | 1,108 | 24 |
| uta-s-92 | 638 | 21,329 | 35 |
| pur-s-93 | 2,419 | 30,032 | 42 |

The dataset provides exam definitions (.crs) and student enrollments (.stu). Room and instructor data are synthetically generated since Carter only covers the graph coloring aspect.

## Usage

### Setup

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Run with Carter Benchmark

```bash
python main.py
```

### Example Output

```
Loaded Carter Instance: ProblemInstance(exams=80, timeslots=18, rooms=15, instructors=30)

=== Solution Found (OPTIMAL) ===

Exam  | Timeslot | Room | Invigilators
------+----------+------+-------------
  1   |    10    |  0   | 0, 5, 6, 7, 14, 16, 21, 28, 29
  2   |    17    |  0   | 0, 4, 7, 9, 11, 12, 13, 15, 21, 25, 26
  ...

Total exams: 80
Timeslots used: 18/18
Rooms used: 6/15

=== Optimization Stats ===
Objective value: 0.0
S1 penalty (preference violations): 0
S2 penalty (workload gap): 0 (max=9, min=9)
S3 penalty (consecutive invigilation): 0
Solve time: 14.30s

=== Workload Distribution ===
  Instructor  0:   9 exams  █████████
  Instructor  1:   9 exams  █████████
  ...
  Instructor 29:   9 exams  █████████
```

### Run with Synthetic Data

```python
# In main.py, swap to synthetic generator:
instance = generate_instance(
    n_exams=20, n_timeslots=10, n_rooms=4,
    n_instructors=8, n_students=60, seed=42
)
```

### Solver Configuration

```python
solution, stats = solve(
    instance=instance,
    w1=1,              # S1 preference weight
    w2=5,              # S2 fairness weight (highest priority)
    w3=2,              # S3 consecutive penalty weight
    enable_s3=True,    # disable for faster solving on large instances
    time_limit=120     # seconds
)
```

## Current Status

### Completed (Weeks 1-6)
- CSP/CSOP formulation with 6 hard constraints and 3 soft constraints
- Full data model with validation and serialization (dataclasses with `__post_init__`)
- Conflict graph construction (adjacency list, O(n²·s) precomputation)
- Synthetic data generator with reproducible seeds
- Baseline backtracking solver written from scratch (H1-H3)
- Independent constraint validation functions for H1-H6
- OR-Tools CP-SAT solver with all 6 hard constraints (H1-H6)
- Soft constraint optimization (S1 preference, S2 Min-Max fairness, S3 consecutive avoidance)
- Carter benchmark dataset parser and integration
- Benchmark testing on hec-s-92 (80 exams, 18 timeslots)
- Workload distribution analysis and statistics reporting

### In Progress
- **Week 7:** Web interface (React + FastAPI) — teammate working on this
- **Week 5:** Visualization (timetable grid, workload charts)

### Planned
- **Week 4 (remaining):** Large instance testing (sta-f-83, yor-f-83, ear-f-83) + performance table
- **Week 8:** Report + analysis with experimental benchmarks across all Carter instances
- **Week 9:** Final presentation

## Known Limitations

- **S3 scalability:** The consecutive invigilation constraint creates O(instructors × consecutive_pairs × exams) boolean variables. For large instances, this can make the solver slow. Use `enable_s3=False` for faster solving.
- **Backtracking solver** handles only H1-H3 and is exponential. It exists solely as a baseline.
- **Carter dataset** lacks room and instructor data. These are synthetically generated, which means H2-H6 results are not directly comparable with literature that only evaluates graph coloring.
- **Optimality gap:** With S3 enabled and tight time limits, the solver may return FEASIBLE (not proven optimal) solutions.

## Dependencies

- **Python 3.10+**
- **ortools** — Google OR-Tools CP-SAT constraint programming solver
- **pytest** — unit testing
- **numpy** — statistical analysis for experiments
- **matplotlib** — performance graphs and visualizations
- **networkx** — conflict graph visualization

## Research Context

This project explores a fairness-aware CSOP framework for university exam timetabling. The key contributions are:

1. **Dual-role conflict modeling (H4):** PhD instructors who both lecture and invigilate are explicitly modeled, preventing scheduling overlaps that make algorithmic schedules impractical.

2. **Min-Max fairness optimization (S2):** Instead of minimizing total system penalty (which can sacrifice individual instructors), we minimize the maximum workload gap, ensuring equitable distribution.

3. **Two-solver comparison:** Manual backtracking baseline vs production-grade CP-SAT, demonstrating the impact of constraint propagation and heuristics.

4. **Real benchmark validation:** Evaluated on Carter (Toronto) benchmark instances, the standard dataset in exam timetabling research.

## License

Academic use.