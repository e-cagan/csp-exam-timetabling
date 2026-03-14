"""
CP-SAT based solver for the University Exam Timetabling Problem.

Uses Google OR-Tools' CP-SAT solver to find optimal exam schedules
that satisfy all six hard constraints (H1-H6) while minimizing
soft constraint penalties (S1-S3).

This is a Constraint Satisfaction Optimization Problem (CSOP):
- Hard constraints (H1-H6): must be satisfied — modeled with model.add()
- Soft constraints (S1-S3): should be minimized — modeled with model.minimize()

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
"""

from ortools.sat.python import cp_model

from src.utils.conflict_graph import build_conflict_graph
from src.models.domain import ProblemInstance
from src.models.solution import Solution


def solve(
    instance: ProblemInstance,
    w1: int = 1,
    w2: int = 5,
    w3: int = 2,
    enable_s3: bool = True,
    time_limit: int = 120
) -> tuple[Solution | None, dict]:
    """
    Solves the exam timetabling problem using OR-Tools CP-SAT.

    Args:
        instance: The problem instance containing exams, rooms, timeslots, instructors.
        w1: Weight for S1 (instructor preference penalty).
        w2: Weight for S2 (workload fairness penalty).
        w3: Weight for S3 (consecutive invigilation penalty).
        enable_s3: Whether to include S3 in the objective (can be slow for large instances).
        time_limit: Maximum solver time in seconds.

    Returns:
        A tuple of (Solution or None, stats dict with objective value and solve time).
    """

    model = cp_model.CpModel()

    # ==================== Conflict Graph ====================
    # Precompute which exam pairs share students (used for H1).
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
    combined = {}

    for exam in instance.exams:
        combined[exam.id] = model.new_int_var(
            0, len(instance.timeslots) * num_rooms - 1, f"combined_{exam.id}"
        )
        model.add(combined[exam.id] == exam_times[exam.id] * num_rooms + exam_rooms[exam.id])

    model.add_all_different(list(combined.values()))

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
    # Variance requires quadratics which CP-SAT doesn't support natively.
    # Min-Max fairness is actually stronger — it directly prevents any single
    # instructor from being disproportionately burdened while others are idle.
    # This aligns with the Min-Max fairness approach from the paper.

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
    # "Active in slot t" = OR over all exams of (exam_in_slot_t AND invigilator_assigned)
    #   - Per-exam AND: add_min_equality(both, [is_in_slot, invigilator])
    #   - Slot-level OR: add_max_equality(active, [both_for_each_exam])
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
                    # Early slot: is exam here AND is instructor assigned?
                    is_in_early = model.new_bool_var(f"s3_ie_{exam.id}_{inst.id}_{t_early}")
                    model.add(exam_times[exam.id] == t_early).only_enforce_if(is_in_early)
                    model.add(exam_times[exam.id] != t_early).only_enforce_if(is_in_early.negated())

                    both_early = model.new_bool_var(f"s3_be_{exam.id}_{inst.id}_{t_early}")
                    model.add_min_equality(both_early, [is_in_early, invigilator[exam.id][inst.id]])
                    active_early_list.append(both_early)

                    # Late slot: same logic
                    is_in_late = model.new_bool_var(f"s3_il_{exam.id}_{inst.id}_{t_late}")
                    model.add(exam_times[exam.id] == t_late).only_enforce_if(is_in_late)
                    model.add(exam_times[exam.id] != t_late).only_enforce_if(is_in_late.negated())

                    both_late = model.new_bool_var(f"s3_bl_{exam.id}_{inst.id}_{t_late}")
                    model.add_min_equality(both_late, [is_in_late, invigilator[exam.id][inst.id]])
                    active_late_list.append(both_late)

                # OR: instructor active in slot if they invigilate at least one exam there
                active_in_early = model.new_bool_var(f"s3_ae_{inst.id}_{t_early}")
                model.add_max_equality(active_in_early, active_early_list)

                active_in_late = model.new_bool_var(f"s3_al_{inst.id}_{t_late}")
                model.add_max_equality(active_in_late, active_late_list)

                # AND: penalty if active in both consecutive slots
                consec_penalty = model.new_bool_var(f"s3_{inst.id}_{t_early}_{t_late}")
                model.add_min_equality(consec_penalty, [active_in_early, active_in_late])
                s3_cost.append(consec_penalty)

    # ==================== Objective Function ====================
    # F = w1 * Σ(S1) + w2 * S2 + w3 * Σ(S3)
    #
    # model.minimize() tells CP-SAT to find the feasible solution
    # with the lowest total weighted penalty, using branch-and-bound with LNS.

    total_s3 = sum(s3_cost) if s3_cost else 0

    total_objective = model.new_int_var(0, 1000000, "total_objective")
    model.add(total_objective == w1 * sum(s1_cost) + w2 * s2_cost + w3 * total_s3)
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
            "wall_time": solver.wall_time,
            "max_load": solver.value(max_load),
            "min_load": solver.value(min_load),
        }

        return solution, stats

    return None, {"status": "INFEASIBLE", "wall_time": solver.wall_time}