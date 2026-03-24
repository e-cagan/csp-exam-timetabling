---
title: UETP Backend
emoji: 🎓
colorFrom: blue
colorTo: indigo
sdk: docker
pinned: false
---

# University Exam Timetabling System (CSP/CSOP)

A Constraint Satisfaction Optimization Problem (CSOP) based system that schedules university exams into timeslots and rooms without conflicts, while optimizing for instructor workload fairness, time preferences, and student scheduling comfort.

## Problem Definition

Scheduling university exams is a real-world combinatorial optimization problem classified as NP-hard. Given a set of exams, timeslots, rooms, and instructors, the goal is to find an assignment that satisfies all hard constraints and minimizes penalties from soft constraints — for both instructors and students.

### CSP Formulation

The problem is formally defined as **CSP = (X, D, C)** with an optimization extension **CSOP = (X, D, C, F)** where:

- **Variables (X):** Each exam `e` has three decision variables:
  - `X_e ∈ T` → timeslot assignment
  - `Y_e ∈ R` → room assignment
  - `Z_{e,i} ∈ {0,1}` → invigilator assignment

- **Domains (D):** All available timeslots, rooms, and instructors.

- **Constraints (C):** Six hard constraints (must be satisfied) and four soft constraints (optimization goals).

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
| S4 | Student Consecutive Day Gap | `add_division_equality` + `add_abs_equality` + reification | Penalize students having exams on consecutive days |

### Multi-Objective Function

`F = w1 * S1 + w2 * S2 + w3 * S3 + w4 * S4`

Default weights: `w1=1, w2=5, w3=2, w4=3`. S2 (fairness) has the highest weight as the primary optimization goal. S4 (student comfort) is second priority, reflecting stakeholder feedback from graduate students.

**Note on S2:** The original formulation uses variance `Σ(load(i) - L̄)²`, but CP-SAT doesn't support quadratic expressions. We use a Min-Max proxy instead: `minimize(max_load - min_load)`. This is actually a stronger fairness guarantee — it directly prevents any single instructor from being disproportionately burdened.

**Note on S4:** Uses integer division (`add_division_equality`) to derive exam day from timeslot, then absolute difference (`add_abs_equality`) to compute day gaps between exam pairs per student. A penalty is incurred when `|day(e_a) - day(e_b)| ≤ 1`.

## 🌐 Full-Stack Architecture & Deployment

The system is designed as a decoupled Full-Stack application, ensuring independent scalability for both the user interface and the heavy-computation solver engine.

### **Frontend (Vercel)**
* **Framework:** React 19 with Vite for ultra-fast development and optimized production bundling.
* **Styling:** Tailwind CSS 4.0 for a modern, responsive, and performant UI.
* **Data Handling:** Integrated `xlsx` and `xlsx-js-style` libraries for exporting formatted Excel timetables.
* **Hosting:** Deployed on **Vercel** for low-latency global access.

### **Backend (Hugging Face Spaces + Docker)**
* **API Framework:** FastAPI (Python 3.10) providing high-performance asynchronous endpoints.
* **Containerization:** The entire backend is containerized using **Docker** to ensure environment consistency.
* **Strategic Migration (Render → Hugging Face):** * **The Problem:** The previous hosting (Render Free Tier) had a strict **512MB RAM** limit, causing frequent **Out of Memory (OOM)** crashes during complex constraint propagation.
    * **The Solution:** Migrated to Hugging Face Spaces with **16GB RAM / 2 vCPU**. This 32x memory increase allows the OR-Tools CP-SAT engine to handle thousands of reified boolean variables (especially for S2 Fairness and S4 Student Day Gap) without bottlenecks.
* **Hosting:** Currently running on **Hugging Face Spaces** for robust computational power.

### **Integration & Security**
* **CORS:** Securely configured to allow communication between the Vercel frontend and Hugging Face API.
* **Environment Variables:** Systematic use of `.env` management to handle API base URLs across production and local environments.

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
│   │   └── soft.py             # S1-S4 penalty functions
│   │
│   ├── solvers/
│   │   ├── backtracking.py     # Baseline: manual backtracking (Week 2)
│   │   └── cp_solver.py        # Production: OR-Tools CP-SAT with H1-H6 + S1-S4
│   │
│   └── utils/
│       ├── conflict_graph.py   # Student-based exam conflict graph builder
│       ├── visualize.py        # Matplotlib visualization generator
│       └── io.py               # JSON serialization helpers
│
├── experiments/
│   └── figures/                # Generated visualizations (PNG)
├── tests/                      # Unit tests
├── main.py                     # Entry point — parse, solve, display, visualize
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

A declarative constraint programming solver using Google OR-Tools CP-SAT. Handles all hard constraints (H1-H6) and soft constraints (S1-S4) with optimization.

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
- **S4** — `add_division_equality` for day extraction + `add_abs_equality` for gap + reified penalty

## Benchmark Results

Tested on the Carter benchmark dataset (Toronto instances), the standard benchmark for exam timetabling research.

### hec-s-92 (80 exams, 2823 students, 18 timeslots)

| Configuration | Status | Objective | S1 | S2 (gap) | S3 | S4 | Time |
|--------------|--------|-----------|-----|----------|-----|------|------|
| S1+S2 only | OPTIMAL | 0 | 0 | 0 (9-9) | — | — | 14.3s |
| S1+S2+S3 | FEASIBLE | 27 | 12 | 1 (8-7) | 5 | — | 120s |
| S1+S2+S4 | FEASIBLE | 15,457 | 1 | 0 (9-9) | — | 5,152 | 120s |

**Key findings:**
- With only S1+S2, the solver achieves **perfect fairness** (all 30 instructors assigned exactly 9 exams) with zero preference violations in 14 seconds, proven OPTIMAL.
- S4 (student day gap) produces a high penalty (5,152) because 80 exams compressed into 18 timeslots (6 days × 3 periods) leaves minimal scheduling flexibility. This is inherent to the problem's chromatic number being exactly 18 — the schedule is maximally packed.
- S2 fairness remains perfect (gap=0) even with S4 enabled, confirming that instructor fairness and student comfort can be optimized simultaneously.
- S3 and S4 each add significant computational cost due to large numbers of reified variables.

## Visualizations

The system generates four publication-ready charts saved to `experiments/figures/`:

| Chart | File | Description |
|-------|------|-------------|
| Timetable Grid | `timetable_grid.png` | 2D heatmap of exams placed on timeslot × room grid |
| Workload Chart | `workload_chart.png` | Bar chart of invigilation load per instructor with fairness coloring |
| Slot Utilization | `slot_utilization.png` | Exams per timeslot with room capacity limit line |
| Exam Size Distribution | `exam_size_distribution.png` | Histogram of student counts per exam |

## Carter Benchmark Dataset

The project supports the Toronto benchmark instances, the most widely used benchmark suite in exam timetabling literature. The dataset was originally compiled by Carter et al. (1996) and has since become the standard evaluation platform for exam timetabling algorithms.

### Dataset Format

- **`.crs` files:** Each line defines an exam — `exam_id  num_students`. Acts as the source of truth for valid exam IDs.
- **`.stu` files:** Each line represents a student — space-separated exam IDs they are enrolled in. This implicitly defines the conflict graph: any two exams appearing on the same line share a student and cannot be scheduled simultaneously.

### Instance Characteristics

| Instance | Exams | Students | Enrollments | Avg Exams/Student | Max Exam Size | Conflict Edges | Graph Density | Chromatic Bound |
|----------|-------|----------|-------------|-------------------|---------------|----------------|---------------|-----------------|
| hec-s-92 | 80 | 2,823 | 10,625 | 3.8 | 634 | 1,351 | 42.8% | 18 |
| sta-f-83 | 138 | 549 | 5,689 | 10.4 | 237 | 1,829 | 19.3% | 13 |
| yor-f-83 | 180 | 919 | 6,012 | 6.5 | 175 | 4,923 | 30.6% | 21 |
| ear-f-83 | 189 | 1,108 | 8,092 | 7.3 | 232 | 4,849 | 27.3% | 24 |
| uta-s-92 | 638 | 21,329 | 59,144 | 2.8 | 1,314 | — | — | 35 |
| pur-s-93 | 2,419 | 30,032 | 120,686 | 4.0 | 1,961 | — | — | 42 |

**Notes:**
- **hec-s-92** is the smallest but densest instance (42.8% conflict density). Nearly half of all exam pairs share at least one student.
- **sta-f-83** has fewest students (549) but the highest enrollment rate (avg 10.4 exams/student, max 33). Students take many courses, creating widespread conflicts despite low density.
- **pur-s-93** has non-contiguous exam IDs (IDs range from 1 to 3158 with gaps). The parser handles this by reading valid IDs from the .crs file.
- **uta-s-92** and **pur-s-93** are large-scale instances (600+ and 2400+ exams respectively) that stress-test solver scalability.
- Conflict density is not computed for uta/pur due to the quadratic cost of O(n²) pair comparison at that scale.
- Room and instructor data are synthetically generated since Carter only covers the graph coloring (timeslot assignment) aspect.

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

=== Solution Found (FEASIBLE) ===

Exam  | Timeslot | Room | Students | Invigilators
------+----------+------+----------+-------------
  1   |    8     |  3   |     367  | 2, 6, 7, 20, 21, 23, 24, 25, 29
  2   |    1     |  8   |     469  | 5, 6, 11, 12, 13, 14, 15, 17, 19, 24, 29
  3   |    16    |  0   |     245  | 16, 17, 18, 20, 21, 27
  ...

=== Optimization Stats ===
Objective value: 14451.0
S1 penalty (preference violations): 0
S2 penalty (workload gap): 0 (max=9, min=9)
S3 penalty (consecutive invigilation): 0
S4 penalty (student consecutive days): 4817
Solve time: 120.11s

=== Workload Distribution ===
  Instructor  0:   9 exams  █████████
  ...
  Instructor 29:   9 exams  █████████
```

### Solver Configuration

```python
solution, stats = solve(
    instance=instance,
    w1=1,              # S1 preference weight
    w2=5,              # S2 fairness weight (highest priority)
    w3=2,              # S3 consecutive invigilation weight
    w4=3,              # S4 student day gap weight
    enable_s3=True,    # disable for faster solving on large instances
    enable_s4=True,    # disable for faster solving on many-student instances
    time_limit=120     # seconds
)
```

## Current Status

### Completed (Weeks 1-7)
- CSP/CSOP formulation with 6 hard constraints and 4 soft constraints
- Full data model with validation and serialization (dataclasses with `__post_init__`)
- Conflict graph construction (adjacency list, O(n²·s) precomputation)
- Synthetic data generator with reproducible seeds
- Baseline backtracking solver written from scratch (H1-H3)
- Independent constraint validation functions for H1-H6
- OR-Tools CP-SAT solver with all 6 hard constraints (H1-H6)
- Soft constraint optimization:
  - S1: Instructor time preference (element constraint + AND gate)
  - S2: Min-Max workload fairness (load balancing)
  - S3: Consecutive invigilation avoidance (reified slot detection)
  - S4: Student consecutive day gap (division + abs + reification)
- Carter benchmark dataset parser and integration
- Benchmark testing on hec-s-92 (80 exams, 18 timeslots)
- Visualization module: timetable grid, workload chart, slot utilization, exam distribution
- Web interface: React + FastAPI (teammate)

### Planned
- **Week 8:** Large instance testing (sta-f-83, yor-f-83, ear-f-83) + report + analysis
- **Week 9:** Final presentation

## Known Limitations

- **S3 scalability:** Creates O(instructors × consecutive_pairs × exams) boolean variables. Use `enable_s3=False` for faster solving on large instances.
- **S4 scalability:** Creates O(students × avg_exam_pairs) variables. For instances with 10,000+ students, consider `enable_s4=False` or sampling.
- **S4 penalty floor:** When the chromatic number equals the available timeslots (schedule is maximally packed), S4 cannot be fully minimized. Increasing timeslots reduces S4 penalty.
- **Backtracking solver** handles only H1-H3 and is exponential. It exists solely as a baseline.
- **Carter dataset** lacks room and instructor data. These are synthetically generated, which means H2-H6 results are not directly comparable with literature that only evaluates graph coloring.
- **Optimality gap:** With S3/S4 enabled and tight time limits, the solver may return FEASIBLE (not proven optimal) solutions.

## Dependencies

- **Python 3.10+**
- **ortools** — Google OR-Tools CP-SAT constraint programming solver
- **matplotlib** — visualization generation
- **numpy** — statistical analysis and chart computation
- **pytest** — unit testing
- **networkx** — conflict graph visualization

## Research Context

This project explores a fairness-aware CSOP framework for university exam timetabling. The key contributions are:

1. **Dual-role conflict modeling (H4):** PhD instructors who both lecture and invigilate are explicitly modeled, preventing scheduling overlaps that make algorithmic schedules impractical.

2. **Min-Max fairness optimization (S2):** Instead of minimizing total system penalty (which can sacrifice individual instructors), we minimize the maximum workload gap, ensuring equitable distribution.

3. **Holistic stakeholder fairness (S1-S4):** The framework optimizes for both instructor comfort (S1 preferences, S2 workload, S3 consecutive avoidance) and student comfort (S4 day gap), addressing the needs of all scheduling stakeholders.

4. **Two-solver comparison:** Manual backtracking baseline vs production-grade CP-SAT, demonstrating the impact of constraint propagation and heuristics.

5. **Real benchmark validation:** Evaluated on Carter (Toronto) benchmark instances, the standard dataset in exam timetabling research, with detailed conflict graph analysis.

## License

Academic use.