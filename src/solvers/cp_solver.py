"""
CP-SAT based solver for the University Exam Timetabling Problem.

Uses Google OR-Tools' CP-SAT solver to find feasible exam schedules
that satisfy hard constraints H1-H3 (timeslot/room assignment).

OR-Tools approach vs manual backtracking:
- Backtracking: we write the search algorithm, constraint checks, and domain management ourselves.
- OR-Tools: we declare variables, state constraints, and let the solver handle
  search strategy, propagation (AC-3, forward checking), and heuristics internally.
"""

from ortools.sat.python import cp_model

from src.utils.conflict_graph import build_conflict_graph
from src.models.domain import ProblemInstance
from src.models.solution import Solution


def solve(instance: ProblemInstance) -> Solution | None:
    """
    Solves the exam timetabling problem using OR-Tools CP-SAT.

    Takes a ProblemInstance, builds a constraint model with H1-H3,
    and returns a Solution if one exists, or None if infeasible.
    """

    model = cp_model.CpModel()

    # ==================== Conflict Graph ====================
    # Precompute which exam pairs share students (used for H1).
    # Same graph structure as in our manual backtracking solver.
    conflict_graph = build_conflict_graph(exams=instance.exams)

    # ==================== Decision Variables ====================
    # For each exam, two variables:
    #   exam_times[id] ∈ {0, ..., |T|-1}  →  which timeslot (X_e in formulation)
    #   exam_rooms[id] ∈ {0, ..., |R|-1}  →  which room     (Y_e in formulation)
    # OR-Tools will find values for these that satisfy all constraints.

    exam_times = {}
    exam_rooms = {}

    for exam in instance.exams:
        exam_times[exam.id] = model.new_int_var(0, len(instance.timeslots) - 1, f"time_{exam.id}")
        exam_rooms[exam.id] = model.new_int_var(0, len(instance.rooms) - 1, f"room_{exam.id}")

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

    # ==================== Solve ====================
    # CP-SAT returns a status code:
    #   OPTIMAL  — best possible solution found (relevant when objective exists)
    #   FEASIBLE — a valid solution found (sufficient when no objective)
    #   INFEASIBLE / MODEL_INVALID / UNKNOWN — no solution

    solver = cp_model.CpSolver()
    status = solver.solve(model)

    if status == cp_model.OPTIMAL or status == cp_model.FEASIBLE:
        # Extract variable values into our Solution dataclass
        exam_time_result = {}
        exam_room_result = {}

        for exam in instance.exams:
            exam_time_result[exam.id] = solver.value(exam_times[exam.id])
            exam_room_result[exam.id] = solver.value(exam_rooms[exam.id])

        return Solution(
            exam_time=exam_time_result,
            exam_room=exam_room_result,
            assigned_invigilators={}
        )

    return None