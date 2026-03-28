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
  H2 — Room Capacity + Online Routing  (allowed assignments filtering)
  H3 — No Room Clash                   (combined variable + all_different, physical only)
  H4 — Lecturer Conflict (Dual-Role)   (conditional constraint via reification)
  H5 — No Double Invigilation          (conditional constraint via reification)
  H6 — Minimum Invigilators Per Exam   (sum of booleans == required)

Soft constraint summary:
  S1 — Instructor Time Preference      (element constraint + AND for penalty)
  S2 — Workload Fairness               (min-max load balancing)
  S3 — Avoid Consecutive Invigilation  (reified slot-activity detection + AND)
  S4 — Student Consecutive Day Gap     (abs day difference + reified penalty)

Online Exam Handling:
  Exams with is_online=True (e.g., weekend exams) are routed to a Virtual Room
  with effectively unlimited capacity (100,000). This virtual room is:
    - The ONLY allowed room for online exams (H2 routing)
    - EXCLUDED from physical room clash detection (H3)
    - Still subject to H1 (student conflicts), H4/H5 (instructor conflicts),
      H6 (invigilator requirements), and all soft constraints (S1-S4)
"""

from collections import defaultdict

from ortools.sat.python import cp_model

from src.utils.conflict_graph import build_conflict_graph
from src.models.domain import ProblemInstance
from src.models.solution import Solution


# ==================== Virtual Room Detection ====================
# The virtual room is identified by its capacity (100,000).
# This constant must match the capacity set in okan_parser.py and api.py
# when creating the virtual room for online exams.
VIRTUAL_ROOM_CAPACITY = 100000


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
        w1: Weight for S1 (instructor preference penalty). Range: 0-10.
        w2: Weight for S2 (workload fairness penalty). Range: 0-10.
        w3: Weight for S3 (consecutive invigilation penalty). Range: 0-10.
        w4: Weight for S4 (student consecutive day penalty). Range: 0-10.
        enable_s3: Whether to include S3 (can be slow for large instances).
        enable_s4: Whether to include S4 (can be slow for many students).
        time_limit: Maximum solver time in seconds.

    Returns:
        A tuple of (Solution or None, stats dict with objective value and solve time).
    """

    model = cp_model.CpModel()

    # ==================== Precomputation ====================

    # Conflict graph: which exam pairs share students (used for H1)
    conflict_graph = build_conflict_graph(exams=instance.exams)

    # Virtual room detection: find the room with capacity >= VIRTUAL_ROOM_CAPACITY.
    # This room acts as a "sink" for online exams — unlimited capacity, no physical clash.
    # If no virtual room exists (e.g., Carter benchmark), virtual_room_id = -1
    # and all online-related logic is safely skipped.
    virtual_room_id = next(
        (r.id for r in instance.rooms if r.capacity >= VIRTUAL_ROOM_CAPACITY),
        -1
    )

    # Precompute which exams are "virtual" — they go to the virtual room.
    # An exam is virtual if:
    #   1) It's explicitly marked as online (exam.is_online == True), OR
    #   2) It's too large for ANY physical room (oversized fallback)
    #
    # Case 2 handles real-world scenarios where a 400-student exam has no
    # physical room big enough — it gets routed to virtual room as a
    # "multi-room / overflow" placeholder. This prevents H2 infeasibility.
    physical_room_max_cap = max(
        (r.capacity for r in instance.rooms if r.id != virtual_room_id),
        default=0
    )

    virtual_exam_ids = set()
    for exam in instance.exams:
        if exam.is_online:
            virtual_exam_ids.add(exam.id)
        elif virtual_room_id != -1 and len(exam.student_ids) > physical_room_max_cap:
            # Oversized exam: no physical room can hold it → force to virtual room
            virtual_exam_ids.add(exam.id)

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
        exam_times[exam.id] = model.new_int_var(
            0, len(instance.timeslots) - 1, f"time_{exam.id}"
        )
        exam_rooms[exam.id] = model.new_int_var(
            0, len(instance.rooms) - 1, f"room_{exam.id}"
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
    # Conflicting exams must be in different timeslots.
    #
    # This applies to ALL exams — including online ones.
    # A student cannot take two exams simultaneously even if both are online.

    for exam_a, neighbors in conflict_graph.items():
        for exam_b in neighbors:
            if exam_a < exam_b:
                model.add(exam_times[exam_a] != exam_times[exam_b])

    # ==================== H2: Room Capacity + Online Routing ====================
    # Two-tier room assignment logic:
    #
    # VIRTUAL EXAMS (online or oversized):
    #   → Can ONLY be assigned to the virtual room.
    #   → Enforced by fixing exam_rooms[eid] == virtual_room_id.
    #   → Virtual room has capacity 100,000 so capacity check passes trivially.
    #
    # PHYSICAL EXAMS (face-to-face):
    #   → Can ONLY be assigned to physical rooms with sufficient capacity.
    #   → Virtual room is explicitly EXCLUDED from their allowed list.
    #   → This prevents the solver from "cheating" by putting a physical exam
    #     into the virtual room to avoid room clash constraints.
    #
    # This separation is the key architectural decision for online exam support.
    # It ensures clean domain separation: online ↔ physical never mix rooms.

    for exam in instance.exams:
        student_count = len(exam.student_ids)

        if exam.id in virtual_exam_ids:
            # Virtual exam: force to virtual room directly.
            # Using model.add() instead of add_allowed_assignments is more efficient
            # for single-value constraints — the solver propagates it immediately.
            model.add(exam_rooms[exam.id] == virtual_room_id)
        else:
            # Physical exam: only rooms with enough capacity, excluding virtual room.
            allowed_rooms = [
                r.id for r in instance.rooms
                if r.capacity >= student_count and r.id != virtual_room_id
            ]

            # Safety fallback: if somehow no physical room fits (shouldn't happen
            # if virtual_exam_ids was computed correctly, but defensive programming)
            if not allowed_rooms:
                allowed_rooms = [virtual_room_id]
                virtual_exam_ids.add(exam.id)

            model.add_allowed_assignments(
                [exam_rooms[exam.id]], [(r,) for r in allowed_rooms]
            )

    # ==================== H3: No Room Clash (Physical Exams Only) ====================
    # Y_ea = Y_eb → X_ea ≠ X_eb
    # Two exams cannot be in the same physical room at the same timeslot.
    #
    # Encoded as: combined = timeslot * num_rooms + room, then all_different.
    # Each unique (timeslot, room) pair produces a unique combined integer.
    # If all combined values are different → no two exams share a (slot, room).
    #
    # CRITICAL: Virtual exams are EXCLUDED from this constraint.
    # Multiple online exams CAN share the virtual room in the same timeslot —
    # that's the whole point of online exams having unlimited capacity.
    # Including virtual exams in all_different would make the problem infeasible
    # whenever more than one online exam exists in the same slot.

    num_rooms = len(instance.rooms)
    combined = []

    for exam in instance.exams:
        if exam.id in virtual_exam_ids:
            # Virtual exam: skip H3 entirely.
            # Room is already fixed to virtual_room_id by H2 above.
            continue

        # Physical exam: create combined variable and add to all_different set.
        c_var = model.new_int_var(
            0, len(instance.timeslots) * num_rooms - 1,
            f"combined_{exam.id}"
        )
        model.add(
            c_var == exam_times[exam.id] * num_rooms + exam_rooms[exam.id]
        )
        combined.append(c_var)

    # Apply all_different only to physical exam combined variables.
    if combined:
        model.add_all_different(combined)

    # ==================== H6: Minimum Invigilators Per Exam ====================
    # Σ_i Z_{e,i} == required(e)
    #
    # Using == instead of >= because:
    #   - It's tighter (fewer unnecessary assignments to explore)
    #   - S2 fairness works better when total assignments is fixed
    #   - required_invigilators already accounts for the minimum need
    #
    # This applies to ALL exams — online exams still need invigilators
    # (proctors monitor online sessions too).

    for exam in instance.exams:
        model.add(
            sum(invigilator[exam.id][inst.id] for inst in instance.instructors)
            == exam.required_invigilators
        )

    # ==================== H4 & H5: Lecturer Conflict and Double Invigilation ====================
    # H5: An instructor cannot invigilate two exams in the same timeslot.
    # H4: A lecturer cannot invigilate another exam in the same timeslot as their own.
    # Both use reified "same_slot" booleans with only_enforce_if.
    #
    # These apply to ALL exams including online — an instructor cannot proctor
    # two simultaneous online exams either.

    for i in range(len(instance.exams)):
        for j in range(i + 1, len(instance.exams)):
            e_a = instance.exams[i].id
            e_b = instance.exams[j].id

            same_slot = model.new_bool_var(f"same_slot_{e_a}_{e_b}")
            model.add(exam_times[e_a] == exam_times[e_b]).only_enforce_if(same_slot)
            model.add(exam_times[e_a] != exam_times[e_b]).only_enforce_if(same_slot.negated())

            # H5: No instructor can invigilate both exams if they're in the same slot
            for inst in instance.instructors:
                model.add(
                    invigilator[e_a][inst.id] + invigilator[e_b][inst.id] <= 1
                ).only_enforce_if(same_slot)

            # H4: Lecturer of exam A cannot invigilate exam B in the same slot (and vice versa)
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
            dislike = [
                0 if inst.preferences.get(t, True) else 1
                for t in range(len(instance.timeslots))
            ]

            # Skip if instructor has no dislikes — no penalty possible
            if sum(dislike) == 0:
                continue

            slot_penalty = model.new_int_var(0, 1, f"s1_slot_{exam.id}_{inst.id}")
            model.add_element(exam_times[exam.id], dislike, slot_penalty)

            penalty_var = model.new_int_var(0, 1, f"s1_{exam.id}_{inst.id}")
            model.add_min_equality(
                penalty_var, [slot_penalty, invigilator[exam.id][inst.id]]
            )

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
                    # Early slot: is exam here AND is instructor assigned?
                    is_in_early = model.new_bool_var(
                        f"s3_ie_{exam.id}_{inst.id}_{t_early}"
                    )
                    model.add(
                        exam_times[exam.id] == t_early
                    ).only_enforce_if(is_in_early)
                    model.add(
                        exam_times[exam.id] != t_early
                    ).only_enforce_if(is_in_early.negated())

                    both_early = model.new_bool_var(
                        f"s3_be_{exam.id}_{inst.id}_{t_early}"
                    )
                    model.add_min_equality(
                        both_early, [is_in_early, invigilator[exam.id][inst.id]]
                    )
                    active_early_list.append(both_early)

                    # Late slot: same logic
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

                # OR: instructor active in slot if they invigilate at least one exam there
                active_in_early = model.new_bool_var(f"s3_ae_{inst.id}_{t_early}")
                model.add_max_equality(active_in_early, active_early_list)

                active_in_late = model.new_bool_var(f"s3_al_{inst.id}_{t_late}")
                model.add_max_equality(active_in_late, active_late_list)

                # AND: penalty if active in both consecutive slots
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
    # "Consecutive" here means |day(e_a) - day(e_b)| ≤ 1, which includes:
    #   - Same day (diff=0): student has two exams on the same day (different periods)
    #   - Adjacent day (diff=1): e.g., Monday + Tuesday, no rest day in between
    #
    # The goal is to ensure at least 1 empty day between any two exams
    # for each student: |day(e_a) - day(e_b)| ≥ 2 is the desired condition.
    #
    # This applies to ALL exams including online — from a student's perspective,
    # having an online exam on Monday and a physical exam on Tuesday is still
    # exhausting. The exam mode doesn't reduce the student's burden.
    #
    # Implementation steps:
    #   1) Derive exam_day variables from exam_times using integer division
    #   2) Build a reverse mapping: student_id → list of exam_ids
    #   3) For each student, for each pair of their exams: penalize if |day_diff| ≤ 1
    #
    # Variable count: O(students × avg_exams_per_student²).

    s4_cost = []

    if enable_s4:
        # Step 1: Create exam_day variables via integer division
        # exam_day[eid] = exam_times[eid] ÷ periods_per_day
        # This extracts the day index from the timeslot index.
        # Example: periods_per_day=5, timeslot=12 → day=2 (12÷5=2), period=2 (12%5=2)

        periods_per_day = max(t.period for t in instance.timeslots) + 1
        n_days = max(t.day for t in instance.timeslots) + 1

        exam_day = {}
        for exam in instance.exams:
            exam_day[exam.id] = model.new_int_var(0, n_days - 1, f"day_{exam.id}")
            model.add_division_equality(
                exam_day[exam.id], exam_times[exam.id], periods_per_day
            )

        # Step 2: Build reverse mapping — student_id → [exam_ids]
        student_exams = defaultdict(list)
        for exam in instance.exams:
            for sid in exam.student_ids:
                student_exams[sid].append(exam.id)

        # Step 3: For each student, penalize exam pairs with |day_diff| ≤ 1
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
                    penalty = model.new_bool_var(f"s4_{sid}_{e_a}_{e_b}")
                    model.add(abs_diff <= 1).only_enforce_if(penalty)
                    model.add(abs_diff >= 2).only_enforce_if(penalty.negated())

                    s4_cost.append(penalty)

    # ==================== Objective Function ====================
    # F = w1 * Σ(S1) + w2 * S2 + w3 * Σ(S3) + w4 * Σ(S4)
    #
    # Weights reflect priority (0-10 range, configurable from frontend):
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