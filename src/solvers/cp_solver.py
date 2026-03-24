"""
CP-SAT based solver for the University Exam Timetabling Problem.

Uses Google OR-Tools' CP-SAT solver to find optimal exam schedules
that satisfy all six hard constraints (H1-H6) while minimizing
soft constraint penalties (S1-S4).

This is a Constraint Satisfaction Optimization Problem (CSOP):
- Hard constraints (H1-H6): must be satisfied — modeled with model.add()
- Soft constraints (S1-S4): should be minimized — modeled with model.minimize()

OR-Tools CP-SAT internally handles:
- Constraint propagation (AC-3, forward checking)
- Search heuristics (MRV, domain ordering)
- Large Neighborhood Search (LNS) for optimization
- Branch and bound for proving optimality

Hard constraint summary:
  H1 — No Student Time Conflict        (conflict graph → pairwise != on timeslots)
  H2 — Room Capacity                   (allowed assignments filtering)
  H3 — No Room Clash                   (combined variable + all_different)
  H4 — Lecturer Conflict (Dual-Role)   (conditional constraint via reification)
  H5 — No Double Invigilation          (conditional constraint via reification)
  H6 — Minimum Invigilators Per Exam   (sum of booleans >= required)

Soft constraint summary:
  S1 — Instructor Time Preference      (element constraint + AND for penalty)
  S2 — Workload Fairness               (min-max load balancing)
  S3 — Avoid Consecutive Invigilation   (reified slot-activity detection + AND)
  S4 — Student Consecutive Day Gap      (abs day difference + reified penalty)
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
    Solves the exam timetabling problem using OR-Tools CP-SAT.

    Args:
        instance: The problem instance containing exams, rooms, timeslots, instructors.
        w1: Weight for S1 (instructor preference penalty).
        w2: Weight for S2 (workload fairness penalty).
        w3: Weight for S3 (consecutive invigilation penalty).
        w4: Weight for S4 (student consecutive day penalty).
        enable_s3: Whether to include S3 (can be slow for large instances).
        enable_s4: Whether to include S4 (can be slow for many students).
        time_limit: Maximum solver time in seconds.

    Returns:
        A tuple of (Solution or None, stats dict with objective value and solve time).
    """

    model = cp_model.CpModel()

    # ==================== Conflict Graph ====================
    conflict_graph = build_conflict_graph(exams=instance.exams)

    # ==================== Decision Variables ====================
    # 1) Timeslot & Room (per exam):
    #    exam_times[id] ∈ {0, ..., |T|-1}  →  X_e in formulation
    #    exam_rooms[id] ∈ {0, ..., |R|-1}  →  Y_e in formulation
    #
    # 2) Invigilator assignment (per exam-instructor pair):
    #    invigilator[exam_id][inst_id] ∈ {0, 1}  →  Z_{e,i} in formulation

    exam_times = {}
    exam_rooms = {}

    for exam in instance.exams:
        exam_times[exam.id] = model.new_int_var(0, len(instance.timeslots) - 1, f"time_{exam.id}")
        exam_rooms[exam.id] = model.new_int_var(0, len(instance.rooms) - 1, f"room_{exam.id}")

    invigilator = {}
    for exam in instance.exams:
        invigilator[exam.id] = {}
        for inst in instance.instructors:
            invigilator[exam.id][inst.id] = model.new_bool_var(f"invig_{exam.id}_{inst.id}")

    # ======================== HARD CONSTRAINTS ========================

    # ==================== H1: No Student Time Conflict ====================
    # students(e_a) ∩ students(e_b) ≠ ∅ → X_ea ≠ X_eb
    # Conflicting exams must be in different timeslots.

    for exam_a, neighbors in conflict_graph.items():
        for exam_b in neighbors:
            if exam_a < exam_b:
                model.add(exam_times[exam_a] != exam_times[exam_b])

    # ==================== H2: Room Capacity ====================
    # |students(e)| ≤ capacity(Y_e)
    # Each exam's room variable is restricted to rooms with sufficient capacity.

    for exam in instance.exams:
        student_count = len(exam.student_ids)
        allowed_rooms = [room.id for room in instance.rooms if room.capacity >= student_count]
        model.add_allowed_assignments([exam_rooms[exam.id]], [(r,) for r in allowed_rooms])

    # ==================== H3: No Room Clash ====================
    # Y_ea = Y_eb → X_ea ≠ X_eb
    # Encoded as: combined = timeslot * num_rooms + room, then all_different.

    num_rooms = len(instance.rooms)
    combined = []

    for exam in instance.exams:
        if exam.is_online:
            # Online exams aren't considered to test in all different
            model.add(exam_rooms[exam.id] == 999)
        else:
            # Only face to face exams are eligable to apply all different rule
            c_var = model.new_int_var(
                0, len(instance.timeslots) * num_rooms - 1, f"combined_{exam.id}"
            )
            model.add(c_var == exam_times[exam.id] * num_rooms + exam_rooms[exam.id])
            combined.append(c_var)

    model.add_all_different(combined)

    # ==================== H6: Minimum Invigilators Per Exam ====================
    # Σ_i Z_{e,i} ≥ required(e)

    for exam in instance.exams:
        model.add(
            sum(invigilator[exam.id][inst.id] for inst in instance.instructors) >= exam.required_invigilators
        )

    # ==================== H4 & H5: Lecturer Conflict and Double Invigilation ====================
    # H5: An instructor cannot invigilate two exams in the same timeslot.
    # H4: A lecturer cannot invigilate another exam in the same timeslot as their own.
    # Both use reified "same_slot" booleans with only_enforce_if.

    for i in range(len(instance.exams)):
        for j in range(i + 1, len(instance.exams)):
            e_a = instance.exams[i].id
            e_b = instance.exams[j].id

            same_slot = model.new_bool_var(f"same_slot_{e_a}_{e_b}")
            model.add(exam_times[e_a] == exam_times[e_b]).only_enforce_if(same_slot)
            model.add(exam_times[e_a] != exam_times[e_b]).only_enforce_if(same_slot.negated())

            # H5
            for inst in instance.instructors:
                model.add(
                    invigilator[e_a][inst.id] + invigilator[e_b][inst.id] <= 1
                ).only_enforce_if(same_slot)

            # H4
            lec_a = instance.exams[i].lecturer_id
            lec_b = instance.exams[j].lecturer_id

            model.add(invigilator[e_b][lec_a] == 0).only_enforce_if(same_slot)
            model.add(invigilator[e_a][lec_b] == 0).only_enforce_if(same_slot)

    # ======================== SOFT CONSTRAINTS ========================

    # ==================== S1: Instructor Time Preference ====================
    # penalty1 = Σ_{e,i} Z_{e,i} * (1 - pref(i, X_e))
    #
    # An instructor incurs a penalty when assigned to invigilate an exam
    # in a timeslot they don't prefer. Two conditions must hold simultaneously:
    #   1) The instructor is assigned to the exam (invigilator == 1)
    #   2) The exam is in a disliked timeslot (preference == False)
    #
    # Implementation:
    #   - "dislike" array: 1 for slots the instructor doesn't want, 0 otherwise
    #   - add_element: looks up dislike[exam_timeslot] at solve time
    #   - add_min_equality: acts as AND gate — min(a,b) = 1 only when both = 1

    s1_cost = []

    for exam in instance.exams:
        for inst in instance.instructors:
            dislike = [0 if inst.preferences.get(t, True) else 1 for t in range(len(instance.timeslots))]

            if sum(dislike) == 0:
                continue

            slot_penalty = model.new_int_var(0, 1, f"s1_slot_{exam.id}_{inst.id}")
            model.add_element(exam_times[exam.id], dislike, slot_penalty)

            penalty_var = model.new_int_var(0, 1, f"s1_{exam.id}_{inst.id}")
            model.add_min_equality(penalty_var, [slot_penalty, invigilator[exam.id][inst.id]])

            s1_cost.append(penalty_var)

    # ==================== S2: Workload Fairness (Min-Max) ====================
    # Original: penalty2 = Σ_i (load(i) - L̄)²
    # CP-SAT proxy: minimize (max_load - min_load)
    #
    # Min-Max fairness directly prevents any single instructor from being
    # disproportionately burdened while others are idle.

    loads = []
    for inst in instance.instructors:
        load = model.new_int_var(0, len(instance.exams), f"load_{inst.id}")
        model.add(load == sum(invigilator[exam.id][inst.id] for exam in instance.exams))
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
    # "Consecutive" = same day, period differs by 1 (e.g., morning → afternoon).
    #
    # For each (instructor, consecutive pair):
    #   1) Check if instructor is "active" in early slot (invigilates any exam there)
    #   2) Check if instructor is "active" in late slot
    #   3) Penalty = 1 if active in BOTH (AND via min)
    #
    # WARNING: Creates O(instructors × consecutive_pairs × exams) variables.
    # For large instances, disable via enable_s3=False.

    s3_cost = []

    if enable_s3:
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
                    is_in_early = model.new_bool_var(f"s3_ie_{exam.id}_{inst.id}_{t_early}")
                    model.add(exam_times[exam.id] == t_early).only_enforce_if(is_in_early)
                    model.add(exam_times[exam.id] != t_early).only_enforce_if(is_in_early.negated())

                    both_early = model.new_bool_var(f"s3_be_{exam.id}_{inst.id}_{t_early}")
                    model.add_min_equality(both_early, [is_in_early, invigilator[exam.id][inst.id]])
                    active_early_list.append(both_early)

                    is_in_late = model.new_bool_var(f"s3_il_{exam.id}_{inst.id}_{t_late}")
                    model.add(exam_times[exam.id] == t_late).only_enforce_if(is_in_late)
                    model.add(exam_times[exam.id] != t_late).only_enforce_if(is_in_late.negated())

                    both_late = model.new_bool_var(f"s3_bl_{exam.id}_{inst.id}_{t_late}")
                    model.add_min_equality(both_late, [is_in_late, invigilator[exam.id][inst.id]])
                    active_late_list.append(both_late)

                active_in_early = model.new_bool_var(f"s3_ae_{inst.id}_{t_early}")
                model.add_max_equality(active_in_early, active_early_list)

                active_in_late = model.new_bool_var(f"s3_al_{inst.id}_{t_late}")
                model.add_max_equality(active_in_late, active_late_list)

                consec_penalty = model.new_bool_var(f"s3_{inst.id}_{t_early}_{t_late}")
                model.add_min_equality(consec_penalty, [active_in_early, active_in_late])
                s3_cost.append(consec_penalty)

    # ==================== S4: Student Consecutive Day Gap ====================
    # Penalize when a student has exams on consecutive days (or same day).
    #
    # "Consecutive" here means |day(e_a) - day(e_b)| ≤ 1, which includes:
    #   - Same day (diff=0): student has two exams on the same day (different periods)
    #   - Adjacent day (diff=1): e.g., Monday + Tuesday, no rest day in between
    #
    # The goal is to ensure at least 1 empty day between any two exams
    # for each student: |day(e_a) - day(e_b)| ≥ 2 is the desired condition.
    #
    # Implementation steps:
    #   1) Derive exam_day variables from exam_times using integer division:
    #      exam_day[eid] = exam_times[eid] // periods_per_day
    #      CP-SAT provides add_division_equality(target, numerator, denominator)
    #
    #   2) Build a reverse mapping: student_id → list of exam_ids
    #      This inverts the exam.student_ids sets so we can iterate per-student.
    #
    #   3) For each student, for each pair of their exams:
    #      - Compute the absolute day difference: |day_a - day_b|
    #        CP-SAT provides add_abs_equality(target, expression)
    #      - If abs_diff ≤ 1, incur a penalty of 1
    #        Using reification: penalty=1 ↔ abs_diff ≤ 1
    #
    # Variable count: O(students × avg_exams_per_student²). For hec-s-92 with
    # 2823 students averaging ~4 exams each: ~2823 × 6 pairs = ~17,000 variables.
    #
    # NOTE: For very large instances (10,000+ students), consider sampling or
    # disable via enable_s4=False. Alternatively, limit to students with 3+ exams.

    s4_cost = []

    if enable_s4:
        # Step 1: Create exam_day variables via integer division
        # exam_day[eid] = exam_times[eid] ÷ periods_per_day (integer division)
        # This extracts the day index from the timeslot index.
        # Example: periods_per_day=3, timeslot=7 → day=2 (7÷3=2), period=1 (7%3=1)

        periods_per_day = max(t.period for t in instance.timeslots) + 1
        n_days = max(t.day for t in instance.timeslots) + 1

        exam_day = {}
        for exam in instance.exams:
            exam_day[exam.id] = model.new_int_var(0, n_days - 1, f"day_{exam.id}")
            model.add_division_equality(exam_day[exam.id], exam_times[exam.id], periods_per_day)

        # Step 2: Build reverse mapping — student_id → [exam_ids]
        # We invert the exam.student_ids relationship so we can iterate
        # per-student and find all their exam pairs efficiently.
        # defaultdict(list) avoids KeyError for students with only 1 exam.

        student_exams = defaultdict(list)
        for exam in instance.exams:
            for sid in exam.student_ids:
                student_exams[sid].append(exam.id)

        # Step 3: For each student, penalize exam pairs with |day_diff| ≤ 1
        # Only consider students with 2+ exams (otherwise no pair to check).
        # Within each student, iterate pairs with i < j to avoid duplicates.

        for sid, eids in student_exams.items():
            if len(eids) < 2:
                continue

            for i in range(len(eids)):
                for j in range(i + 1, len(eids)):
                    e_a = eids[i]
                    e_b = eids[j]

                    # Compute signed difference: diff = day_a - day_b
                    # Range is [-n_days+1, n_days-1] to cover all possibilities
                    diff = model.new_int_var(-(n_days - 1), n_days - 1, f"s4_diff_{sid}_{e_a}_{e_b}")
                    model.add(diff == exam_day[e_a] - exam_day[e_b])

                    # Compute absolute difference: abs_diff = |diff|
                    # CP-SAT's add_abs_equality handles this natively
                    abs_diff = model.new_int_var(0, n_days - 1, f"s4_abs_{sid}_{e_a}_{e_b}")
                    model.add_abs_equality(abs_diff, diff)

                    # Reified penalty: penalty = 1 ↔ abs_diff ≤ 1
                    # If the day gap is 0 (same day) or 1 (consecutive days),
                    # the student doesn't have enough rest → penalty.
                    # If abs_diff ≥ 2, there's at least one rest day → no penalty.
                    #
                    # Reification ensures the boolean is EXACTLY equivalent:
                    #   penalty=True  enforces abs_diff ≤ 1
                    #   penalty=False enforces abs_diff ≥ 2
                    penalty = model.new_bool_var(f"s4_{sid}_{e_a}_{e_b}")
                    model.add(abs_diff <= 1).only_enforce_if(penalty)
                    model.add(abs_diff >= 2).only_enforce_if(penalty.negated())

                    s4_cost.append(penalty)

    # ==================== Objective Function ====================
    # F = w1 * Σ(S1) + w2 * S2 + w3 * Σ(S3) + w4 * Σ(S4)
    #
    # Weights reflect priority:
    #   w2=5 (fairness is primary goal)
    #   w4=3 (student comfort is important)
    #   w3=2 (instructor scheduling comfort)
    #   w1=1 (preference satisfaction is nice-to-have)
    #
    # model.minimize() uses branch-and-bound with LNS to converge
    # toward the optimal solution within the time limit.

    total_s3 = sum(s3_cost) if s3_cost else 0
    total_s4 = sum(s4_cost) if s4_cost else 0

    total_objective = model.new_int_var(0, 10000000, "total_objective")
    model.add(
        total_objective == w1 * sum(s1_cost) + w2 * s2_cost + w3 * total_s3 + w4 * total_s4
    )
    model.minimize(total_objective)

    # ==================== Solve ====================
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit

    status = solver.solve(model)

    if status == cp_model.OPTIMAL or status == cp_model.FEASIBLE:
        exam_time_result = {}
        exam_room_result = {}

        for exam in instance.exams:
            exam_time_result[exam.id] = solver.value(exam_times[exam.id])
            exam_room_result[exam.id] = solver.value(exam_rooms[exam.id])

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

        stats = {
            "status": "OPTIMAL" if status == cp_model.OPTIMAL else "FEASIBLE",
            "objective": solver.objective_value,
            "s1_penalty": sum(solver.value(v) for v in s1_cost),
            "s2_penalty": solver.value(s2_cost),
            "s3_penalty": sum(solver.value(v) for v in s3_cost) if s3_cost else 0,
            "s4_penalty": sum(solver.value(v) for v in s4_cost) if s4_cost else 0,
            "wall_time": solver.wall_time,
            "max_load": solver.value(max_load),
            "min_load": solver.value(min_load),
        }

        return solution, stats

    return None, {"status": "INFEASIBLE", "wall_time": solver.wall_time}