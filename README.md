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
* **Strategic Migration (Render → Hugging Face):**
    * **The Problem:** The previous hosting (Render Free Tier) had a strict **512MB RAM** limit, causing frequent **Out of Memory (OOM)** crashes during complex constraint propagation.
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
│   │   ├── carter_parser.py    # Carter benchmark dataset parser
│   │   └── okan_parser.py      # Istanbul Okan University Excel parser (pandas)
│   └── instances/
│       ├── carter/             # Carter benchmark files (.crs, .stu)
│       └── okan/               # Okan University Excel files
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

### Carter hec-s-92 (80 exams, 2823 students, 18 timeslots)

| Configuration | Status | Objective | S1 | S2 (gap) | S3 | S4 | Time |
|--------------|--------|-----------|-----|----------|-----|------|------|
| S1+S2 only | OPTIMAL | 0 | 0 | 0 (9-9) | — | — | 14.3s |
| S1+S2+S3 | FEASIBLE | 27 | 12 | 1 (8-7) | 5 | — | 120s |
| S1+S2+S4 | FEASIBLE | 14,451 | 0 | 0 (9-9) | — | 4,817 | 120s |

### Istanbul Okan University (131 exams, ~1190 students, 62 timeslots)

| Configuration | Status | Objective | S1 | S2 (gap) | S3 | S4 | Time |
|--------------|--------|-----------|-----|----------|-----|------|------|
| S1+S2+S4 | FEASIBLE | 2,870 | 0 | 1 (7-6) | — | 955 | 300s |

### Cross-Instance Comparison

| Metric | Carter hec-s-92 | Okan University |
|--------|----------------|-----------------|
| Exams | 80 | 131 |
| Students | 2,823 | ~1,190 |
| Timeslots | 18 | 62 |
| Rooms | 15 (synthetic) | 23 (real) |
| Instructors | 30 (synthetic) | 36 (real) |
| S1 (preference violations) | 0 | 0 |
| S2 (fairness gap) | 0 | 1 (mathematically minimum) |
| S4 (student day penalty) | 4,817 | 955 |
| Solve time | 120s | 300s |

**Key findings:**
- With only S1+S2, the Carter solver achieves **perfect fairness** (all 30 instructors assigned exactly 9 exams) with zero preference violations in 14 seconds, proven OPTIMAL.
- S4 (student day gap) produces a high penalty on Carter (4,817) because 80 exams are compressed into 18 timeslots (6 days × 3 periods) — the chromatic number equals available slots, leaving zero scheduling flexibility.
- **Okan University S4 is 5× lower** (955 vs 4,817) thanks to 62 timeslots spread over 8 exam days with 5 periods each, giving the solver far more room to space out student exams.
- Okan S2 gap=1 is the **mathematical minimum**: 131 exams / 36 instructors ≈ 3.64, requiring 33 instructors at 6 exams and 3 at 7 exams. Perfect equality (gap=0) is arithmetically impossible.
- **S1=0 on real data** is particularly significant: with actual instructor leave days from İZİN GÜNLERİ, zero preference violations confirms the solver respects real scheduling constraints.
- S3 and S4 each add significant computational cost due to large numbers of reified variables.

## Visualizations

The system generates four publication-ready charts saved to `experiments/figures/`:

| Chart | File | Description |
|-------|------|-------------|
| Timetable Grid | `timetable_grid.png` | 2D heatmap of exams placed on timeslot × room grid |
| Workload Chart | `workload_chart.png` | Bar chart of invigilation load per instructor with fairness coloring |
| Slot Utilization | `slot_utilization.png` | Exams per timeslot with room capacity limit line |
| Exam Size Distribution | `exam_size_distribution.png` | Histogram of student counts per exam |

## Datasets

### Carter Benchmark (Toronto Instances)

The most widely used benchmark suite in exam timetabling literature, originally compiled by Carter et al. (1996).

**Format:** `.crs` files (exam definitions) and `.stu` files (student enrollments). Room and instructor data are synthetically generated since Carter only covers the graph coloring aspect.

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
- **sta-f-83** has fewest students (549) but the highest enrollment rate (avg 10.4 exams/student, max 33).
- **pur-s-93** has non-contiguous exam IDs (IDs range from 1 to 3158 with gaps). The parser handles this by reading valid IDs from the .crs file.
- Conflict density is not computed for uta/pur due to the quadratic cost of O(n²) pair comparison at that scale.

### Istanbul Okan University (Real-World Data)

Real exam scheduling data from Istanbul Okan University, Faculty of Engineering and Natural Sciences, 2024-2025 Fall Semester. Unlike Carter, this dataset provides **real** room capacities, instructor leave days, and course-instructor mappings.

**Data Sources:**
- **Ders İnceleme Raporu** — Student enrollment records (student_id → course_code mappings, equivalent to Carter's `.stu` file)
- **Final Schedule Excel** — Exam schedule with dates, times, rooms, and invigilators
  - `FINAL(8-18 OCAK)` sheet: Physical exam entries
  - `DERSLİK KAPASİTE` sheet: Real classroom capacities (22 rooms, 14-53 capacity)
  - `İZİN GÜNLERİ` sheet: Instructor leave days → S1 preference data

**Instance Characteristics:**

| Metric | Value |
|--------|-------|
| Exams | 131 |
| Students | ~1,190 |
| Timeslots | 62 (8 exam days × 5 periods + online slots) |
| Rooms | 23 (22 real classrooms + synthetic halls for large exams) |
| Instructors | 36 (25 PhD, from İZİN GÜNLERİ sheet) |
| Conflict Density | ~17.9% |
| Avg Students/Exam | 56 |
| Max Exam Size | 446 |

**Parser Features (`okan_parser.py`):**
- Fuzzy course code matching: handles Turkish character differences (INŞ→INS), spaces, slash-separated codes (IE437/ILOG417), and prefix-based patterns (END405/419 → END419)
- Achieves 94.4% match rate between schedule and enrollment data (134/142 entries)
- Deduplication for exams split across multiple rooms or multi-day project exams
- Automatic room scaling: adds synthetic large rooms (halls) when exam sizes exceed max classroom capacity
- Instructor PhD detection from academic titles (DR., PROF., DOÇ.)
- Leave day parsing from Turkish text ("Pazartesi (YL)", "Cuma (iki haftada bir)")

## Usage

### Setup

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Run with Okan University Data

```python
from data.parsers.okan_parser import parse_okan

instance = parse_okan(
    enrollment_path="data/instances/okan/Ders_Inceleme_Raporu.xlsx",
    schedule_path="data/instances/okan/2024-2025_Guz_Final.xlsx",
    schedule_sheet="FINAL(8-18 OCAK)"
)
```

### Run with Carter Benchmark

```python
from data.parsers.carter_parser import parse_carter

instance = parse_carter(
    crs_path="data/instances/carter/hec-s-92-2.crs",
    stu_path="data/instances/carter/hec-s-92-2.stu",
    n_timeslots=18, n_rooms=15, n_instructors=30
)
```

### Example Output (Okan University)
```
Loaded Okan Instance: ProblemInstance(exams=131, timeslots=62, rooms=23, instructors=36)

=== Solution Found (FEASIBLE) ===

Exam  | Timeslot | Room | Students | Invigilators
------+----------+------+----------+-------------
  0   |    61    |  22  |      80  | 23, 32
  1   |    0     |  0   |       1  | 23
  2   |    2     |  3   |      43  | 21
  ...

=== Optimization Stats ===
Objective value: 2870.0
S1 penalty (preference violations): 0
S2 penalty (workload gap): 1 (max=7, min=6)
S3 penalty (consecutive invigilation): 0
S4 penalty (student consecutive days): 955
Solve time: 300.31s

=== Workload Distribution ===
  Instructor  0:   6 exams  ██████
  Instructor  1:   6 exams  ██████
  Instructor  2:   7 exams  ███████
  Instructor  3:   7 exams  ███████
  ...
  Instructor 35:   6 exams  ██████
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

### Completed (Weeks 1-8)
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
- Istanbul Okan University real-world data parser (pandas + fuzzy matching)
- Benchmark testing on Carter hec-s-92 and Okan University data
- Visualization module: timetable grid, workload chart, slot utilization, exam distribution
- Web interface: React 19 + FastAPI, deployed on Vercel + Hugging Face Spaces

### Planned
- **Week 9:** Final presentation + report

## Known Limitations

- **S3 scalability:** Creates O(instructors × consecutive_pairs × exams) boolean variables. Use `enable_s3=False` for faster solving on large instances.
- **S4 scalability:** Creates O(students × avg_exam_pairs) variables. For instances with 10,000+ students, consider `enable_s4=False` or sampling.
- **S4 penalty floor:** When the chromatic number equals the available timeslots (schedule is maximally packed), S4 cannot be fully minimized. Increasing timeslots reduces S4 penalty.
- **Backtracking solver** handles only H1-H3 and is exponential. It exists solely as a baseline.
- **Carter dataset** lacks room and instructor data. These are synthetically generated, which means H2-H6 results are not directly comparable with literature that only evaluates graph coloring.
- **Okan parser coverage:** 94.4% match rate — remaining 5.6% are courses from programs not present in enrollment data (e.g., GEOM courses).
- **Optimality gap:** With S3/S4 enabled and tight time limits, the solver may return FEASIBLE (not proven optimal) solutions.

## Dependencies

- **Python 3.10+**
- **ortools** — Google OR-Tools CP-SAT constraint programming solver
- **pandas** — Excel data parsing and manipulation (Okan parser)
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

5. **Dual validation — synthetic + real-world:** Evaluated on both Carter (Toronto) benchmark instances (the standard dataset in exam timetabling research) and real Istanbul Okan University data with actual room capacities, instructor leave days, and student enrollments.

## License

Academic use.