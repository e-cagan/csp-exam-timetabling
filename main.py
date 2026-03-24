"""
Main module to run the algorithms.
"""

from data.parsers.okan_parser import parse_okan
from src.solvers.cp_solver import solve
from src.utils.visualize import generate_all

if __name__ == '__main__':
    # 1. Parse the Okan University real-world dataset directly from Excel files
    instance = parse_okan(
        student_excel_path="data/instances/okan/Ders İnceleme Raporu 04.10.2024 Güz Dönemi.xlsx",
        schedule_excel_path="data/instances/okan/2024-2025 Güz Final.xlsx",
        exams_sheet_name="FINAL(8-18 OCAK)"
    )

    print(f"Loaded Okan Instance: {instance}")

    # 2. Solve with soft constraints
    # S3 disabled for speed (too heavy for large real-world data initially)
    # S4 enabled for student fairness
    solution, stats = solve(instance=instance, enable_s3=False, enable_s4=True, time_limit=300)

    # 3. Display results
    if solution:
        print(f"\n=== Solution Found ({stats['status']}) ===\n")

        print("Exam  | Timeslot | Room | Students | Invigilators")
        print("------+----------+------+----------+-------------")
        for exam in instance.exams:
            t = solution.exam_time[exam.id]
            r = solution.exam_room[exam.id]
            s = len(exam.student_ids)
            invig = solution.assigned_invigilators.get(exam.id, set())
            invig_str = ", ".join(str(i) for i in sorted(invig)) if invig else "none"
            
            # Virtual rooms (Online exams) check
            room_display = "ONLINE" if r == 999 else r
            print(f"  {exam.id:<4}|    {t:<6}|  {room_display:<6}|  {s:>6}  | {invig_str}")

        print(f"\nTotal exams: {len(instance.exams)}")
        print(f"Timeslots used: {len(set(solution.exam_time.values()))}/{len(instance.timeslots)}")
        # We don't consider online exams in used rooms calculation
        used_rooms = [r for r in set(solution.exam_room.values()) if r != 999]
        print(f"Physical Rooms used: {len(used_rooms)}/{len(instance.rooms) - 1}")

        # Optimization stats
        print(f"\n=== Optimization Stats ===")
        print(f"Objective value: {stats['objective']}")
        print(f"S1 penalty (preference violations): {stats['s1_penalty']}")
        print(f"S2 penalty (workload gap): {stats['s2_penalty']} (max={stats['max_load']}, min={stats['min_load']})")
        print(f"S3 penalty (consecutive invigilation): {stats['s3_penalty']}")
        print(f"S4 penalty (student consecutive days): {stats['s4_penalty']}")
        print(f"Solve time: {stats['wall_time']:.2f}s")

        # Workload distribution
        print(f"\n=== Workload Distribution ===")
        for inst in instance.instructors:
            count = sum(1 for exam in instance.exams if inst.id in solution.assigned_invigilators.get(exam.id, set()))
            bar = "█" * count
            print(f"  Instructor {inst.id:>2}: {count:>3} exams  {bar}")

        # Generate visualizations
        print(f"\n=== Generating Visualizations ===")
        generate_all(instance, solution, stats)
    else:
        print(f"\nNo solution found. ({stats['status']}, time: {stats['wall_time']:.2f}s)")