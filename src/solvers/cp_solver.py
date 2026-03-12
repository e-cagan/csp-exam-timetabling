"""
A module which focuses on solving the problem using google ortools library.
"""

from ortools.sat.python import cp_model

from utils.conflict_graph import build_conflict_graph
from models.domain import ProblemInstance
from models.solution import Solution


def solve(instance: ProblemInstance) -> Solution | None:
    """
    A function which tries to solve the problem.
    """

    # Create the model and solver instances
    model = cp_model.CpModel()
    solver = cp_model.CpSolver()

    # Build the conflict graph
    conflict_graph = build_conflict_graph(exams=instance.exams)

    # Define the variables for timeslots and rooms and store them inside of lookup dicts
    exam_times = {}
    exam_rooms = {}

    # Iterate trough exams and add the variable based on exam id
    for exam in instance.exams:
        exam_times[exam.id] = model.new_int_var(0, len(instance.timeslots) - 1, f"time_{exam.id}")
        exam_rooms[exam.id] = model.new_int_var(0, len(instance.rooms) - 1, f"room_{exam.id}")

    # Check if the contraints satisfied (H1, H2 and H3 for now)
    ## H1 constraint (Two exams sharing a student cannot be in the same timeslot.)
    for exam_a, neighbors in conflict_graph.items():
        for exam_b in neighbors:
            if exam_a < exam_b:
                model.add(exam_times[exam_a] != exam_times[exam_b])

    ## H2 constraint (Exam's student count must not exceed the assigned room's capacity.)
    for exam in instance.exams:
        allowed_rooms = []
        for room in instance.rooms:
            if room.capacity >= len(exam.student_ids):
                allowed_rooms.append(room.id)
        model.add_allowed_assignments([exam_rooms[exam.id]], [(r,) for r in allowed_rooms])

    ## H3 constraint (Two exams in the same room cannot be in the same timeslot.)
    num_rooms = len(instance.rooms)
    combined = {}

    for exam in instance.exams:
        combined[exam.id] = model.new_int_var(0, len(instance.timeslots) * num_rooms - 1, f"combined_{exam.id}")
        model.add(combined[exam.id] == exam_times[exam.id] * num_rooms + exam_rooms[exam.id])

    model.add_all_different(list(combined.values()))

    # Solve the problem
    status = solver.solve(model)

    # Check if solution found
    if status == cp_model.OPTIMAL or status == cp_model.FEASIBLE:       # OPTIMAL = best solution, FEASIBLE = valid solution
        # Extract solution                                              # We accept both of them because we don't have any objective yet
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