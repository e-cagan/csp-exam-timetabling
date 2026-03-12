"""
Main module to run the algorithms.
"""

from data.generators.synthetic import generate_instance
from src.solvers.cp_solver import solve


if __name__ == '__main__':
    # 1. Generate instance
    instance = generate_instance(n_exams=20, n_timeslots=10, n_rooms=4, n_instructors=8, n_students=60)

    # 2. Test out the solution
    solution = solve(instance=instance)

    # 3. Check if there is a solution and print the response
    if solution:
        print("=== Solution Found ===\n")
        print("Exam  | Timeslot | Room")
        print("------+----------+-----")
        for exam in instance.exams:
            t = solution.exam_time[exam.id]
            r = solution.exam_room[exam.id]
            print(f"  {exam.id:<4}|    {t:<6}|  {r}")
    else:
        print("No solution found.")