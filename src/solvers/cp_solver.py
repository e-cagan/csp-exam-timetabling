"""
CP-SAT based solver for the University Exam Timetabling Problem.

Uses Google OR-Tools' CP-SAT solver to find feasible exam schedules
that satisfy all six hard constraints (H1-H6), covering both
timeslot/room assignment and invigilator allocation.

OR-Tools approach vs manual backtracking:
- Backtracking: we write the search algorithm, constraint checks, and domain management ourselves.
- OR-Tools: we declare variables, state constraints, and let the solver handle
  search strategy, propagation (AC-3, forward checking), and heuristics internally.

Constraint summary:
  H1 — No Student Time Conflict        (conflict graph → pairwise != on timeslots)
  H2 — Room Capacity                   (allowed assignments filtering)
  H3 — No Room Clash                   (combined variable + all_different)
  H4 — Lecturer Conflict (Dual-Role)   (conditional constraint via reification)
  H5 — No Double Invigilation          (conditional constraint via reification)
  H6 — Minimum Invigilators Per Exam   (sum of booleans >= required)
"""

from ortools.sat.python import cp_model

from src.utils.conflict_graph import build_conflict_graph
from src.models.domain import ProblemInstance
from src.models.solution import Solution


def solve(instance: ProblemInstance) -> Solution | None:
    """
    Solves the exam timetabling problem using OR-Tools CP-SAT.

    Takes a ProblemInstance, builds a constraint model with H1-H6,
    and returns a Solution if one exists, or None if infeasible.
    """

    model = cp_model.CpModel()

    # ==================== Conflict Graph ====================
    # Precompute which exam pairs share students (used for H1).
    # Same graph structure as in our manual backtracking solver.
    conflict_graph = build_conflict_graph(exams=instance.exams)

    # ==================== Decision Variables ====================
    # Two types of decision variables, matching the CSP formulation:
    #
    # 1) Timeslot & Room (per exam):
    #    exam_times[id] ∈ {0, ..., |T|-1}  →  X_e in formulation
    #    exam_rooms[id] ∈ {0, ..., |R|-1}  →  Y_e in formulation
    #
    # 2) Invigilator assignment (per exam-instructor pair):
    #    invigilator[exam_id][inst_id] ∈ {0, 1}  →  Z_{e,i} in formulation
    #    A boolean: 1 if instructor is assigned to invigilate that exam.

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

    # ==================== H1: No Student Time Conflict ====================
    # Formulation: students(e_a) ∩ students(e_b) ≠ ∅ → X_ea ≠ X_eb
    #
    # For every pair of exams that share at least one student,
    # their timeslot variables must take different values.
    # The (exam_a < exam_b) guard avoids adding duplicate constraints
    # since the conflict graph is undirected.

    for exam_a, neighbors in conflict_graph.items():
        for exam_b in neighbors:
            if exam_a < exam_b:
                model.add(exam_times[exam_a] != exam_times[exam_b])

    # ==================== H2: Room Capacity ====================
    # Formulation: |students(e)| ≤ capacity(Y_e)
    #
    # Each exam can only be assigned to rooms large enough to hold
    # all its students. We restrict each exam's room variable to
    # only take values corresponding to sufficiently large rooms.
    # add_allowed_assignments expects a list of tuples — each tuple
    # is one valid assignment for the variable(s).

    for exam in instance.exams:
        student_count = len(exam.student_ids)
        allowed_rooms = [room.id for room in instance.rooms if room.capacity >= student_count]
        model.add_allowed_assignments([exam_rooms[exam.id]], [(r,) for r in allowed_rooms])

    # ==================== H3: No Room Clash ====================
    # Formulation: Y_ea = Y_eb → X_ea ≠ X_eb
    #
    # No two exams can occupy the same room at the same time.
    # We encode this by creating a "combined" variable for each exam:
    #   combined = timeslot * num_rooms + room
    # This maps each (timeslot, room) pair to a unique integer.
    # Requiring all combined values to be different guarantees
    # that no two exams share the same slot+room combination.

    num_rooms = len(instance.rooms)
    combined = {}

    for exam in instance.exams:
        combined[exam.id] = model.new_int_var(
            0, len(instance.timeslots) * num_rooms - 1, f"combined_{exam.id}"
        )
        model.add(combined[exam.id] == exam_times[exam.id] * num_rooms + exam_rooms[exam.id])

    model.add_all_different(list(combined.values()))

    # ==================== H6: Minimum Invigilators Per Exam ====================
    # Formulation: Σ_i Z_{e,i} ≥ required(e)
    #
    # Each exam must have at least the required number of invigilators.
    # Since invigilator variables are boolean (0 or 1), summing them
    # gives the count of assigned invigilators. We constrain this sum
    # to be at least the exam's required_invigilators value.
    # Added before H4/H5 because it's independent — no conditional logic needed.

    for exam in instance.exams:
        model.add(
            sum(invigilator[exam.id][inst.id] for inst in instance.instructors) >= exam.required_invigilators
        )

    # ==================== H4 & H5: Lecturer Conflict and Double Invigilation ====================
    # H5 Formulation: Σ_{e: X_e = t} Z_{e,i} ≤ 1
    #   An instructor cannot invigilate two exams in the same timeslot.
    #
    # H4 Formulation: lecturer(e) = i → Z_{e',i} = 0 if X_{e'} = X_e
    #   A PhD instructor who lectures exam e cannot be assigned as an
    #   invigilator for another exam e' running in the same timeslot.
    #
    # Both constraints are conditional: they only apply when two exams
    # share the same timeslot. OR-Tools handles this via "reification":
    #   - We create a boolean variable "same_slot" for each exam pair.
    #   - only_enforce_if(same_slot) makes a constraint active only when same_slot is True.
    #   - Two reification constraints define same_slot precisely:
    #       same_slot = True  ↔  exam_times[a] == exam_times[b]
    #       same_slot = False ↔  exam_times[a] != exam_times[b]
    #
    # H4 and H5 share the same exam-pair loop and same_slot variable
    # to avoid redundant boolean variables and duplicate iteration.

    for i in range(len(instance.exams)):
        for j in range(i + 1, len(instance.exams)):
            e_a = instance.exams[i].id
            e_b = instance.exams[j].id

            # Create a reified boolean: same_slot ↔ (timeslot_a == timeslot_b)
            same_slot = model.new_bool_var(f"same_slot_{e_a}_{e_b}")
            model.add(exam_times[e_a] == exam_times[e_b]).only_enforce_if(same_slot)
            model.add(exam_times[e_a] != exam_times[e_b]).only_enforce_if(same_slot.negated())

            # H5: If two exams are in the same slot, no single instructor
            # can invigilate both. For each instructor, the sum of their
            # assignments to exam_a and exam_b must be at most 1.
            for inst in instance.instructors:
                model.add(
                    invigilator[e_a][inst.id] + invigilator[e_b][inst.id] <= 1
                ).only_enforce_if(same_slot)

            # H4: If two exams are in the same slot, exam_a's lecturer
            # cannot invigilate exam_b, and exam_b's lecturer cannot
            # invigilate exam_a. This prevents a PhD instructor from
            # being pulled away from their own exam to invigilate elsewhere.
            lec_a = instance.exams[i].lecturer_id
            lec_b = instance.exams[j].lecturer_id

            model.add(invigilator[e_b][lec_a] == 0).only_enforce_if(same_slot)
            model.add(invigilator[e_a][lec_b] == 0).only_enforce_if(same_slot)

    # ==================== Solve ====================
    # CP-SAT returns a status code:
    #   OPTIMAL    — best possible solution (relevant when an objective is set)
    #   FEASIBLE   — a valid solution found (sufficient when no objective)
    #   INFEASIBLE — proven that no solution exists
    #   UNKNOWN    — solver timed out or hit resource limits

    solver = cp_model.CpSolver()
    # FOR LOGGING
    # solver.parameters.log_search_progress = True
    status = solver.solve(model)

    if status == cp_model.OPTIMAL or status == cp_model.FEASIBLE:
        # Extract timeslot and room assignments
        exam_time_result = {}
        exam_room_result = {}

        for exam in instance.exams:
            exam_time_result[exam.id] = solver.value(exam_times[exam.id])
            exam_room_result[exam.id] = solver.value(exam_rooms[exam.id])

        # Extract invigilator assignments:
        # For each exam, collect the set of instructor IDs whose boolean variable is 1
        invig_result = {}
        for exam in instance.exams:
            assigned = set()
            for inst in instance.instructors:
                if solver.value(invigilator[exam.id][inst.id]) == 1:
                    assigned.add(inst.id)
            invig_result[exam.id] = assigned

        return Solution(
            exam_time=exam_time_result,
            exam_room=exam_room_result,
            assigned_invigilators=invig_result
        )

    return None