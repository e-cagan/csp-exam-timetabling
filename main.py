"""
Main module to run the algorithms.
"""

from data.generators.synthetic import generate_instance
from data.parsers.carter_parser import parse_carter
from src.solvers.cp_solver import solve


if __name__ == '__main__':
    # Parse the Carter benchmark dataset
    instance = parse_carter(
        crs_path="data/instances/carter/hec-s-92-2.crs",
        stu_path="data/instances/carter/hec-s-92-2.stu",
        n_timeslots=18,
        n_rooms=15,
        n_instructors=30
    )

    print(f"Loaded Carter Instance: {instance}")

    # Solve with soft constraints (disable S3 for faster initial test)
    solution, stats = solve(instance=instance, enable_s3=True, time_limit=120)

    # Display results
    if solution:
        print(f"\n=== Solution Found ({stats['status']}) ===\n")

        print("Exam  | Timeslot | Room | Invigilators")
        print("------+----------+------+-------------")
        for exam in instance.exams:
            t = solution.exam_time[exam.id]
            r = solution.exam_room[exam.id]
            invig = solution.assigned_invigilators.get(exam.id, set())
            invig_str = ", ".join(str(i) for i in sorted(invig)) if invig else "none"
            print(f"  {exam.id:<4}|    {t:<6}|  {r:<4}| {invig_str}")

        print(f"\nTotal exams: {len(instance.exams)}")
        print(f"Timeslots used: {len(set(solution.exam_time.values()))}/{len(instance.timeslots)}")
        print(f"Rooms used: {len(set(solution.exam_room.values()))}/{len(instance.rooms)}")

        # Optimization stats
        print(f"\n=== Optimization Stats ===")
        print(f"Objective value: {stats['objective']}")
        print(f"S1 penalty (preference violations): {stats['s1_penalty']}")
        print(f"S2 penalty (workload gap): {stats['s2_penalty']} (max={stats['max_load']}, min={stats['min_load']})")
        print(f"S3 penalty (consecutive invigilation): {stats['s3_penalty']}")
        print(f"Solve time: {stats['wall_time']:.2f}s")

        # Workload distribution
        print(f"\n=== Workload Distribution ===")
        for inst in instance.instructors:
            count = sum(1 for exam in instance.exams if inst.id in solution.assigned_invigilators.get(exam.id, set()))
            bar = "|" * count
            print(f"  Instructor {inst.id:>2}: {count:>3} exams  {bar}")
    else:
        print(f"\nNo solution found. ({stats['status']}, time: {stats['wall_time']:.2f}s)")