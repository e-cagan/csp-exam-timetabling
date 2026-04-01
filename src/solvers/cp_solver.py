"""
CP-SAT based solver for the University Exam Timetabling Problem.
Upgraded to MULTI-ROOM / EXAM SPLITTING Architecture.

Uses Google OR-Tools' CP-SAT solver to find optimal exam schedules
that satisfy all six hard constraints (H1-H6) while minimizing
soft constraint penalties (S1-S4) plus anti-fragmentation and overflow costs.

This is a Constraint Satisfaction Optimization Problem (CSOP):
  - Hard constraints (H1-H6): must be satisfied — modeled with model.add()
  - Soft constraints (S1-S4): should be minimized — modeled with model.minimize()
  - S5 (Anti-Fragmentation): penalizes unnecessary room splitting
  - Overflow penalty: heavily penalizes forcing physical exams online

OR-Tools CP-SAT internally handles:
  - Constraint propagation (AC-3, forward checking) — eliminates infeasible values early
  - Search heuristics (MRV, domain ordering) — picks the most constrained variable first
  - Large Neighborhood Search (LNS) — for optimization after finding feasible solutions
  - Branch and bound — for proving optimality

Hard constraint summary:
  H1 — No Student Time Conflict        (conflict graph → pairwise != on timeslots)
  H2 — Room Capacity + Online Routing   (multi-room boolean matrix, overflow safety valve)
  H3 — No Room Clash                    (pairwise room exclusion per same_slot, physical only)
  H4 — Lecturer Conflict (Dual-Role)    (conditional constraint via reification)
  H5 — No Double Invigilation           (conditional constraint via reification)
  H6 — Invigilator Count                (sum of booleans == required, 0 for online)

Soft constraint summary:
  S1 — Instructor Time Preference       (element constraint + AND for penalty)
  S2 — Workload Fairness                (min-max load balancing)
  S3 — Avoid Consecutive Invigilation   (reified slot-activity detection + AND)
  S4 — Student Consecutive Day Gap      (abs day difference + reified penalty)
  S5 — Anti-Fragmentation               (minimize total_rooms_used)

Multi-Room Architecture:
  Instead of a single integer room variable per exam (exam_rooms[eid] ∈ {0..R-1}),
  we use a boolean matrix: room_used[exam_id][room_id] ∈ {0, 1}.
  This allows a single exam to occupy MULTIPLE rooms simultaneously,
  which is essential for real-world large exams (e.g., 446 students split
  across 14 classrooms). The trade-off is significantly more variables:
  room_used[131][29] = 3,799 booleans vs the old 131 integer variables.

Online Exam Handling:
  Exams with is_online=True are routed to a Virtual Room (capacity=100,000).
  These exams require zero invigilators (req_invig=0) and are excluded from
  physical room clash detection (H3). Multiple online exams CAN share the
  virtual room in the same timeslot — unlimited concurrency.
"""

from collections import defaultdict
from ortools.sat.python import cp_model

from src.utils.conflict_graph import build_conflict_graph
from src.models.domain import ProblemInstance
from src.models.solution import Solution


def solve(
    instance: ProblemInstance,
    w1: int = 1,
    w2: int = 5,
    w3: int = 2,
    w4: int = 3,
    enable_s3: bool = True,
    enable_s4: bool = True,
    time_limit: int = 120
) -> tuple[Solution | None, dict]:
    """
    Solves the exam timetabling problem using OR-Tools CP-SAT
    with multi-room splitting and online exam support.

    Args:
        instance: The problem instance containing exams, rooms, timeslots, instructors.
        w1: Weight for S1 (instructor preference penalty). Range: 0-10.
        w2: Weight for S2 (workload fairness penalty). Range: 0-10.
        w3: Weight for S3 (consecutive invigilation penalty). Range: 0-10.
        w4: Weight for S4 (student consecutive day penalty). Range: 0-10.
        enable_s3: Whether to include S3 (can be slow for large instances).
        enable_s4: Whether to include S4 (can be slow for many students).
        time_limit: Maximum solver time in seconds.

    Returns:
        A tuple of (Solution or None, stats dict with detailed penalty breakdown).
        Solution.exam_room is now dict[int, list[int]] (multi-room support).
    """

    model = cp_model.CpModel()

    # ==================== Precomputation ====================

    # Build the student-based conflict graph: which exam pairs share students.
    # This adjacency list is used by H1 to enforce pairwise timeslot inequality.
    # Time complexity: O(n² · s) where n=exams, s=avg students per exam.
    conflict_graph = build_conflict_graph(exams=instance.exams)

    # Identify the virtual room (capacity == 100,000) used for online exams.
    # If no virtual room exists (e.g., Carter benchmark with no online exams),
    # virtual_room_id = -1 and all online-related logic is safely skipped.
    virtual_room_id = next(
        (r.id for r in instance.rooms if r.capacity == 100000), -1
    )

    # ==================== Decision Variables ====================
    #
    # TIMESLOT VARIABLES: exam_times[exam_id] ∈ {0, ..., |T|-1}
    #   Maps each exam to a timeslot. This is the X_e variable in the formulation.
    #
    # ROOM VARIABLES (MULTI-ROOM): room_used[exam_id][room_id] ∈ {0, 1}
    #   Boolean matrix — 1 if exam uses this room, 0 otherwise.
    #   An exam can use MULTIPLE rooms simultaneously (room splitting).
    #   This replaces the old single-int exam_rooms[eid] ∈ {0..R-1}.
    #   Variable count: |exams| × |rooms| (e.g., 131 × 29 = 3,799 booleans).
    #
    # INVIGILATOR VARIABLES: invigilator[exam_id][inst_id] ∈ {0, 1}
    #   Boolean — 1 if instructor is assigned to invigilate this exam.
    #   This is the Z_{e,i} variable in the formulation.

    exam_times = {}
    room_used = {}

    for exam in instance.exams:
        exam_times[exam.id] = model.new_int_var(
            0, len(instance.timeslots) - 1, f"time_{exam.id}"
        )

        # Create a boolean variable for each possible (exam, room) pair.
        # This is the core of the multi-room architecture.
        room_used[exam.id] = {}
        for room in instance.rooms:
            room_used[exam.id][room.id] = model.new_bool_var(
                f"room_{exam.id}_{room.id}"
            )

    invigilator = {}
    for exam in instance.exams:
        invigilator[exam.id] = {}
        for inst in instance.instructors:
            invigilator[exam.id][inst.id] = model.new_bool_var(
                f"invig_{exam.id}_{inst.id}"
            )

    # ======================== HARD CONSTRAINTS ========================

    # ==================== H1: No Student Time Conflict ====================
    # students(e_a) ∩ students(e_b) ≠ ∅ → X_ea ≠ X_eb
    #
    # Two exams that share at least one student MUST be scheduled in different
    # timeslots. This is the fundamental graph coloring constraint.
    #
    # Applies to ALL exams including online — a student cannot take two
    # exams simultaneously even if both are online.
    #
    # We iterate conflict graph edges with exam_a < exam_b to avoid
    # posting duplicate constraints (the graph is undirected).

    for exam_a, neighbors in conflict_graph.items():
        for exam_b in neighbors:
            if exam_a < exam_b:
                model.add(exam_times[exam_a] != exam_times[exam_b])

    # ==================== H2: Room Capacity (Multi-Room Logic) ====================
    # For ONLINE exams:
    #   Forced to use ONLY the virtual room. All physical rooms set to 0.
    #   The virtual room has capacity 100,000 — trivially satisfies any exam size.
    #
    # For PHYSICAL exams:
    #   The sum of capacities of all selected physical rooms must be >= student count.
    #   An "overflow" safety valve exists: if no combination of physical rooms
    #   can fit the exam (shouldn't happen normally), the solver CAN fall back
    #   to the virtual room — but with a massive penalty (+5000) in the objective
    #   to ensure this only happens as a last resort.
    #
    #   The overflow mechanism uses the virtual room's boolean as a flag:
    #     is_overflow = room_used[exam_id][virtual_room_id]
    #     If is_overflow=0: physical rooms must sum to >= students (normal case)
    #     If is_overflow=1: all physical rooms forced to 0 (emergency online fallback)
    #
    #   This reification pattern (only_enforce_if) lets the solver choose
    #   between "find enough physical rooms" and "give up and go online",
    #   with the 5000-point penalty making the latter extremely unattractive.

    overflow_penalties = []

    for exam in instance.exams:
        if exam.is_online:
            # Online exam: force to virtual room, block all physical rooms.
            model.add(room_used[exam.id][virtual_room_id] == 1)
            for r in instance.rooms:
                if r.id != virtual_room_id:
                    model.add(room_used[exam.id][r.id] == 0)
        else:
            # Physical exam: multi-room capacity constraint with overflow safety valve.

            # The overflow flag is the virtual room's boolean for this exam.
            # If it becomes 1, the exam is "forced online" (emergency fallback).
            is_overflow = room_used[exam.id][virtual_room_id]
            overflow_penalties.append(is_overflow)

            # NORMAL CASE (no overflow): selected physical rooms must have enough
            # total capacity. sum(room_used[eid][rid] * capacity(rid)) >= students.
            # This allows the solver to pick ANY combination of rooms that fits.
            model.add(
                sum(
                    room_used[exam.id][r.id] * r.capacity
                    for r in instance.rooms
                    if r.id != virtual_room_id
                ) >= len(exam.student_ids)
            ).only_enforce_if(is_overflow.negated())

            # OVERFLOW CASE: if forced online, ban all physical room usage.
            # This ensures clean separation — no "half physical, half online" state.
            for r in instance.rooms:
                if r.id != virtual_room_id:
                    model.add(
                        room_used[exam.id][r.id] == 0
                    ).only_enforce_if(is_overflow)

    # ==================== H6: Minimum Invigilators Per Exam ====================
    # Σ_i Z_{e,i} == required(e)
    #
    # Using == (equality) instead of >= (inequality) because:
    #   - It's tighter — the solver doesn't waste time exploring extra assignments
    #   - S2 fairness works better when total assignment count is deterministic
    #   - required_invigilators is already calibrated (1 per 40 students)
    #
    # For ONLINE exams: required_invigilators == 0, so no instructor is assigned.
    # This is correct — online proctoring is handled separately.
    # For PHYSICAL exams: required_invigilators >= 1 (enforced by domain.py).

    for exam in instance.exams:
        model.add(
            sum(invigilator[exam.id][inst.id] for inst in instance.instructors)
            == exam.required_invigilators
        )

    # ==================== H3, H4, H5: Pairwise Exam Constraints ====================
    # These three constraints all depend on whether two exams are in the same
    # timeslot, so they share a common "same_slot" reified boolean variable.
    #
    # For each pair of exams (i, j) where i < j:
    #   1. Create same_slot boolean: True ↔ exam_times[i] == exam_times[j]
    #   2. H3: If same_slot, no shared physical room
    #   3. H5: If same_slot, no shared invigilator
    #   4. H4: If same_slot, lecturer of exam A cannot invigilate exam B (and vice versa)
    #
    # Reification pattern:
    #   model.add(A == B).only_enforce_if(bool_var)       — "if True, enforce A==B"
    #   model.add(A != B).only_enforce_if(bool_var.negated()) — "if False, enforce A!=B"
    #   Together, these make bool_var ↔ (A == B), a full reification.
    #
    # H3 (MULTI-ROOM VERSION):
    #   Old version used combined = timeslot * num_rooms + room → all_different.
    #   New version checks each physical room individually:
    #     room_used[e_a][r] + room_used[e_b][r] <= 1  (if same_slot)
    #   This ensures that if two exams are in the same timeslot, they cannot
    #   share ANY physical room — even if both use multiple rooms.
    #   Virtual room is excluded: multiple online exams CAN share it simultaneously.
    #
    #   Constraint count: O(exams² × physical_rooms) ≈ 131² × 28 ≈ 480K constraints.
    #   This is the main scalability bottleneck of the multi-room architecture.

    for i in range(len(instance.exams)):
        for j in range(i + 1, len(instance.exams)):
            e_a = instance.exams[i].id
            e_b = instance.exams[j].id

            # Reified same_slot boolean: True ↔ both exams in the same timeslot
            same_slot = model.new_bool_var(f"same_slot_{e_a}_{e_b}")
            model.add(
                exam_times[e_a] == exam_times[e_b]
            ).only_enforce_if(same_slot)
            model.add(
                exam_times[e_a] != exam_times[e_b]
            ).only_enforce_if(same_slot.negated())

            # H3: No Room Clash (physical rooms only)
            # If two exams are in the same timeslot, they cannot share any
            # physical room. Each room can only host ONE exam per timeslot.
            # Virtual room is excluded — online exams have unlimited concurrency.
            for r in instance.rooms:
                if r.id != virtual_room_id:
                    model.add(
                        room_used[e_a][r.id] + room_used[e_b][r.id] <= 1
                    ).only_enforce_if(same_slot)

            # H5: No Double Invigilation
            # An instructor cannot invigilate two exams in the same timeslot.
            # Applies to ALL exams including online — an instructor cannot
            # proctor two simultaneous online exams either.
            for inst in instance.instructors:
                model.add(
                    invigilator[e_a][inst.id] + invigilator[e_b][inst.id] <= 1
                ).only_enforce_if(same_slot)

            # H4: Lecturer Conflict (Dual-Role Prevention)
            # A PhD instructor who LECTURES exam A cannot INVIGILATE exam B
            # if they are in the same timeslot (and vice versa).
            # This prevents the real-world absurdity of an instructor trying
            # to both give their own exam and proctor another simultaneously.
            lec_a = instance.exams[i].lecturer_id
            lec_b = instance.exams[j].lecturer_id
            model.add(
                invigilator[e_b][lec_a] == 0
            ).only_enforce_if(same_slot)
            model.add(
                invigilator[e_a][lec_b] == 0
            ).only_enforce_if(same_slot)

    # ======================== SOFT CONSTRAINTS ========================

    # ==================== S1: Instructor Time Preference ====================
    # penalty1 = Σ_{e,i} Z_{e,i} * (1 - pref(i, X_e))
    #
    # An instructor incurs a penalty of 1 when BOTH conditions hold:
    #   1) They are assigned to invigilate the exam (Z_{e,i} = 1)
    #   2) The exam is in a timeslot they dislike (pref = False, typically a leave day)
    #
    # Implementation uses two OR-Tools primitives:
    #   - add_element(index_var, array, target): looks up dislike[timeslot] at solve time.
    #     This is a "variable-indexed array access" — the timeslot is a decision variable,
    #     so we can't do a simple array lookup at model-build time.
    #   - add_min_equality(target, [a, b]): target = min(a, b), which acts as AND gate.
    #     min(1, 1) = 1 (penalty), min(0, anything) = 0 (no penalty).
    #
    # Optimization: if an instructor has NO dislikes (all preferences True),
    # we skip them entirely — no penalty is possible regardless of timeslot.
    #
    # S1=0 on real Okan data means zero instructors were assigned to their leave days.

    s1_cost = []

    for exam in instance.exams:
        for inst in instance.instructors:
            # Build dislike array: 1 for timeslots the instructor doesn't want, 0 otherwise
            dislike = [
                0 if inst.preferences.get(t, True) else 1
                for t in range(len(instance.timeslots))
            ]

            # Skip if instructor has no dislikes — no penalty possible
            if sum(dislike) == 0:
                continue

            # Look up dislike value at the exam's assigned timeslot (solve-time lookup)
            slot_penalty = model.new_int_var(0, 1, f"s1_slot_{exam.id}_{inst.id}")
            model.add_element(exam_times[exam.id], dislike, slot_penalty)

            # AND gate: penalty = 1 only if BOTH assigned AND in disliked slot
            penalty_var = model.new_int_var(0, 1, f"s1_{exam.id}_{inst.id}")
            model.add_min_equality(
                penalty_var, [slot_penalty, invigilator[exam.id][inst.id]]
            )
            s1_cost.append(penalty_var)

    # ==================== S2: Workload Fairness (Min-Max) ====================
    # Original formulation: penalty2 = Σ_i (load(i) - L̄)²
    # CP-SAT doesn't support quadratic expressions, so we use a Min-Max proxy:
    #   minimize(max_load - min_load)
    #
    # This is actually a STRONGER fairness guarantee than variance minimization:
    #   - Variance allows some instructors to be heavily loaded if others compensate
    #   - Min-Max directly prevents ANY single instructor from being disproportionately burdened
    #
    # Implementation:
    #   1) Compute load[i] = Σ_e Z_{e,i} for each instructor (total exams assigned)
    #   2) max_load = max(loads), min_load = min(loads) via add_max/min_equality
    #   3) s2_cost = max_load - min_load
    #
    # S2 gap=2 on Okan data: 180 total assignments / 36 instructors = 5.0 avg.
    # Perfect gap=0 is theoretically possible but solver returns FEASIBLE (not OPTIMAL)
    # within 300s due to the multi-room variable explosion.

    loads = []
    for inst in instance.instructors:
        load = model.new_int_var(0, len(instance.exams), f"load_{inst.id}")
        model.add(
            load == sum(invigilator[exam.id][inst.id] for exam in instance.exams)
        )
        loads.append(load)

    max_load = model.new_int_var(0, len(instance.exams), "max_load")
    min_load = model.new_int_var(0, len(instance.exams), "min_load")
    model.add_max_equality(max_load, loads)
    model.add_min_equality(min_load, loads)

    s2_cost = model.new_int_var(0, len(instance.exams), "s2_cost")
    model.add(s2_cost == max_load - min_load)

    # ==================== S3: Avoid Consecutive Invigilation ====================
    # Penalize an instructor for invigilating in two adjacent timeslots.
    #
    # "Consecutive" = same day, period differs by exactly 1.
    # Example: Period 0 (08:50-10:20) and Period 1 (10:30-12:00) on the same day.
    #
    # For each (instructor, consecutive_pair):
    #   1) Detect if instructor is "active" in the early slot
    #      (assigned to invigilate at least one exam scheduled there)
    #   2) Detect if instructor is "active" in the late slot
    #   3) Penalty = 1 if active in BOTH (AND via add_min_equality)
    #
    # Detection uses nested reification:
    #   - For each exam: is_in_slot = (exam_times[eid] == slot_id) — reified boolean
    #   - both = min(is_in_slot, invigilator[eid][iid]) — AND gate
    #   - active_in_slot = max(both_list) — OR across all exams
    #
    # WARNING: Creates O(instructors × consecutive_pairs × exams) variables.
    # For 36 instructors × ~50 pairs × 131 exams ≈ 236K variables.
    # Use enable_s3=False for faster solving on large instances.

    s3_cost = []

    if enable_s3:
        # Find all consecutive timeslot pairs (same day, adjacent periods)
        consecutive_pairs = []
        for t1 in instance.timeslots:
            for t2 in instance.timeslots:
                if t1.id < t2.id and t1.day == t2.day and abs(t1.period - t2.period) == 1:
                    consecutive_pairs.append((t1.id, t2.id))

        for inst in instance.instructors:
            for t_early, t_late in consecutive_pairs:
                active_early_list = []
                active_late_list = []

                for exam in instance.exams:
                    # --- Early slot detection ---
                    # Is this exam scheduled in the early slot?
                    is_in_early = model.new_bool_var(
                        f"s3_ie_{exam.id}_{inst.id}_{t_early}"
                    )
                    model.add(
                        exam_times[exam.id] == t_early
                    ).only_enforce_if(is_in_early)
                    model.add(
                        exam_times[exam.id] != t_early
                    ).only_enforce_if(is_in_early.negated())

                    # AND: exam in early slot AND instructor assigned to it
                    both_early = model.new_bool_var(
                        f"s3_be_{exam.id}_{inst.id}_{t_early}"
                    )
                    model.add_min_equality(
                        both_early, [is_in_early, invigilator[exam.id][inst.id]]
                    )
                    active_early_list.append(both_early)

                    # --- Late slot detection (same logic) ---
                    is_in_late = model.new_bool_var(
                        f"s3_il_{exam.id}_{inst.id}_{t_late}"
                    )
                    model.add(
                        exam_times[exam.id] == t_late
                    ).only_enforce_if(is_in_late)
                    model.add(
                        exam_times[exam.id] != t_late
                    ).only_enforce_if(is_in_late.negated())

                    both_late = model.new_bool_var(
                        f"s3_bl_{exam.id}_{inst.id}_{t_late}"
                    )
                    model.add_min_equality(
                        both_late, [is_in_late, invigilator[exam.id][inst.id]]
                    )
                    active_late_list.append(both_late)

                # OR across all exams: instructor active if they invigilate
                # at least one exam in that slot
                active_in_early = model.new_bool_var(f"s3_ae_{inst.id}_{t_early}")
                model.add_max_equality(active_in_early, active_early_list)

                active_in_late = model.new_bool_var(f"s3_al_{inst.id}_{t_late}")
                model.add_max_equality(active_in_late, active_late_list)

                # Final AND: penalty if active in BOTH consecutive slots
                consec_penalty = model.new_bool_var(
                    f"s3_{inst.id}_{t_early}_{t_late}"
                )
                model.add_min_equality(
                    consec_penalty, [active_in_early, active_in_late]
                )
                s3_cost.append(consec_penalty)

    # ==================== S4: Student Consecutive Day Gap ====================
    # Penalize when a student has exams on consecutive days (or same day).
    #
    # "Consecutive" means |day(e_a) - day(e_b)| ≤ 1, which includes:
    #   - Same day (diff=0): student has two exams on the same day (different periods)
    #   - Adjacent day (diff=1): e.g., Monday + Tuesday, no rest day in between
    #
    # The goal is to ensure at least 1 empty day between any two exams
    # for each student: |day(e_a) - day(e_b)| ≥ 2 is the desired condition.
    #
    # This applies to ALL exams including online — from a student's perspective,
    # having an online exam on Monday and a physical exam on Tuesday is still
    # exhausting. The exam mode doesn't reduce the student's cognitive burden.
    #
    # Implementation steps:
    #   1) Derive exam_day[eid] = exam_times[eid] ÷ periods_per_day
    #      CP-SAT's add_division_equality handles integer division natively.
    #   2) Build reverse mapping: student_id → [exam_ids]
    #   3) For each student, for each pair of their exams:
    #      - diff = day_a - day_b (signed)
    #      - abs_diff = |diff| (via add_abs_equality)
    #      - penalty = 1 ↔ abs_diff ≤ 1 (reified)
    #
    # Variable count: O(students × C(avg_exams, 2)).
    # For ~1190 students averaging ~3 exams: ~1190 × 3 ≈ 3,570 penalty variables.

    s4_cost = []

    if enable_s4:
        # Step 1: Derive exam day from timeslot via integer division.
        # periods_per_day is inferred from the maximum period index + 1.
        # Example: if max period is 4, periods_per_day = 5.
        # timeslot 12 → day = 12 ÷ 5 = 2, period = 12 % 5 = 2
        periods_per_day = max(t.period for t in instance.timeslots) + 1
        n_days = max(t.day for t in instance.timeslots) + 1

        exam_day = {}
        for exam in instance.exams:
            exam_day[exam.id] = model.new_int_var(
                0, n_days - 1, f"day_{exam.id}"
            )
            model.add_division_equality(
                exam_day[exam.id], exam_times[exam.id], periods_per_day
            )

        # Step 2: Build reverse mapping — student_id → [exam_ids]
        # We invert the exam.student_ids relationship so we can iterate
        # per-student and find all their exam pairs efficiently.
        student_exams = defaultdict(list)
        for exam in instance.exams:
            for sid in exam.student_ids:
                student_exams[sid].append(exam.id)

        # Step 3: For each student, penalize exam pairs with |day_diff| ≤ 1
        # Only students with 2+ exams are checked (single-exam students have no pairs).
        for sid, eids in student_exams.items():
            if len(eids) < 2:
                continue

            for i in range(len(eids)):
                for j in range(i + 1, len(eids)):
                    e_a = eids[i]
                    e_b = eids[j]

                    # Signed difference: day_a - day_b
                    diff = model.new_int_var(
                        -(n_days - 1), n_days - 1,
                        f"s4_diff_{sid}_{e_a}_{e_b}"
                    )
                    model.add(diff == exam_day[e_a] - exam_day[e_b])

                    # Absolute difference: |day_a - day_b|
                    abs_diff = model.new_int_var(
                        0, n_days - 1,
                        f"s4_abs_{sid}_{e_a}_{e_b}"
                    )
                    model.add_abs_equality(abs_diff, diff)

                    # Reified penalty: penalty=1 ↔ abs_diff ≤ 1
                    # If True: abs_diff ≤ 1 (consecutive or same day → penalize)
                    # If False: abs_diff ≥ 2 (at least one rest day → no penalty)
                    penalty = model.new_bool_var(f"s4_{sid}_{e_a}_{e_b}")
                    model.add(abs_diff <= 1).only_enforce_if(penalty)
                    model.add(abs_diff >= 2).only_enforce_if(penalty.negated())

                    s4_cost.append(penalty)

    # ==================== Objective Function ====================
    # F = w1*S1 + w2*S2 + w3*S3 + w4*S4 + total_rooms_used + overflow_count*5000
    #
    # Components:
    #   S1-S4: Weighted soft constraint penalties (configurable 0-10 per weight)
    #   total_rooms_used (S5 — Anti-Fragmentation):
    #     Sum of all room_used booleans for physical rooms across all exams.
    #     Minimizing this discourages unnecessary room splitting.
    #     Example: if a 40-student exam can fit in 1 room (cap 44), the solver
    #     prefers that over splitting into 2 rooms (cap 24 + cap 24 = 48).
    #   overflow_count * 5000:
    #     Each physical exam forced to the virtual room incurs a 5000-point penalty.
    #     This massive cost ensures the solver only does this as a last resort
    #     when no combination of physical rooms can accommodate the exam.
    #
    # The anti-fragmentation and overflow terms have implicit weight=1 and weight=5000
    # respectively. They are NOT user-configurable — they are architectural invariants.

    total_s3 = sum(s3_cost) if s3_cost else 0
    total_s4 = sum(s4_cost) if s4_cost else 0

    # S5: Anti-Fragmentation — count total physical room assignments
    total_rooms_used = sum(
        room_used[e.id][r.id]
        for e in instance.exams
        for r in instance.rooms
        if r.id != virtual_room_id
    )

    total_objective = model.new_int_var(0, 10_000_000, "total_objective")
    model.add(
        total_objective ==
        w1 * sum(s1_cost)
        + w2 * s2_cost
        + w3 * total_s3
        + w4 * total_s4
        + total_rooms_used                  # Anti-fragmentation (weight=1)
        + sum(overflow_penalties) * 5000    # Overflow deterrent (weight=5000)
    )
    model.minimize(total_objective)

    # ==================== Solve ====================
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit

    status = solver.solve(model)

    # ==================== Extract Solution ====================
    if status == cp_model.OPTIMAL or status == cp_model.FEASIBLE:
        exam_time_result = {}
        exam_room_result = {}  # dict[int, list[int]] — multi-room support

        for exam in instance.exams:
            exam_time_result[exam.id] = solver.value(exam_times[exam.id])

            # Collect ALL rooms where room_used == 1 for this exam.
            # For a typical small exam: [5] (single room)
            # For a 446-student exam: [0, 2, 3, 7, 10, 14, ...] (14 rooms)
            # For an online exam: [virtual_room_id] (virtual room only)
            assigned_rooms = [
                r.id for r in instance.rooms
                if solver.value(room_used[exam.id][r.id]) == 1
            ]
            exam_room_result[exam.id] = assigned_rooms

        invig_result = {}
        for exam in instance.exams:
            assigned = set()
            for inst in instance.instructors:
                if solver.value(invigilator[exam.id][inst.id]) == 1:
                    assigned.add(inst.id)
            invig_result[exam.id] = assigned

        solution = Solution(
            exam_time=exam_time_result,
            exam_room=exam_room_result,
            assigned_invigilators=invig_result
        )

        # ==================== Stats Breakdown ====================
        # Provides a detailed decomposition of the objective value.
        # This is critical for paper/analysis: reviewers need to see
        # exactly how much each component contributes to the total.
        stats = {
            "status": "OPTIMAL" if status == cp_model.OPTIMAL else "FEASIBLE",
            "objective": solver.objective_value,
            # Individual soft constraint penalties
            "s1_penalty": sum(solver.value(v) for v in s1_cost),
            "s2_penalty": solver.value(s2_cost),
            "s3_penalty": sum(solver.value(v) for v in s3_cost) if s3_cost else 0,
            "s4_penalty": sum(solver.value(v) for v in s4_cost) if s4_cost else 0,
            # Multi-room specific metrics
            "total_rooms_used": solver.value(total_rooms_used),
            "overflow_count": sum(solver.value(v) for v in overflow_penalties),
            # Solver performance
            "wall_time": solver.wall_time,
            # Fairness details
            "max_load": solver.value(max_load),
            "min_load": solver.value(min_load),
        }

        return solution, stats

    # No feasible solution found within the time limit.
    return None, {"status": "INFEASIBLE", "wall_time": solver.wall_time}