"""
Main module to run the algorithms with Multi-Room support.
"""

from data.parsers.okan_parser import parse_okan
from src.solvers.cp_solver import solve
from src.utils.visualize import generate_all

if __name__ == '__main__':
    # 1. Parse the Okan University real-world dataset directly from Excel files
    # Not: okan_parser artık (instance, course_codes) ikilisini döndüğü için unpack yapıyoruz.
    instance, course_codes = parse_okan(
        student_excel_path="data/instances/anonymusokan/ANON_Ders_Inceleme_Raporu.xlsx",
        schedule_excel_path="data/instances/anonymusokan/ANON_Guz_Final.xlsx",
        exams_sheet_name="FINAL(8-18 OCAK)",
        instructors_sheet_name="İZİN GÜNLERİ"
    )

    print(f"Loaded Okan Instance: {instance}")

    # 2. Solve with multi-room logic
    solution, stats = solve(instance=instance, enable_s3=False, enable_s4=True, time_limit=300)

    # 3. Display results
    if solution:
        print(f"\n=== Solution Found ({stats['status']}) ===\n")

        print("Exam  | Timeslot | Room(s)           | Students | Invigilators")
        print("------+----------+-------------------+----------+-------------")
        
        virtual_room_id = next((r.id for r in instance.rooms if r.capacity == 100000), -1)

        for exam in instance.exams:
            t = solution.exam_time[exam.id]
            r_list = solution.exam_room[exam.id] # Artık bir liste: [3, 4] gibi
            s = len(exam.student_ids)
            invig = solution.assigned_invigilators.get(exam.id, set())
            invig_str = ", ".join(str(i) for i in sorted(invig)) if invig else "none"
            
            # Virtual room check
            if virtual_room_id in r_list:
                room_display = "ONLINE"
            else:
                # Odaları virgülle birleştir, gerçek isimleri domain'den çek
                room_names = []
                for rid in r_list:
                    r_obj = next((rm for rm in instance.rooms if rm.id == rid), None)
                    room_names.append(getattr(r_obj, "name", str(rid)))
                room_display = ", ".join(room_names)
                
            print(f"  {exam.id:<4}|    {t:<6}|  {room_display:<17}|  {s:>6}  | {invig_str}")

        print(f"\nTotal exams: {len(instance.exams)}")
        print(f"Timeslots used: {len(set(solution.exam_time.values()))}/{len(instance.timeslots)}")
        
        # Fiziksel oda kullanım istatistiği (İç içe listeleri unique kümelere dönüştürüyoruz)
        used_physical_rooms = set()
        for r_ids in solution.exam_room.values():
            for rid in r_ids:
                if rid != virtual_room_id:
                    used_physical_rooms.add(rid)
                    
        print(f"Physical Rooms used: {len(used_physical_rooms)}/{len(instance.rooms) - 1}")

        # Optimization stats
        print(f"\n=== Optimization Stats ===")
        print(f"Objective value: {stats['objective']}")
        print(f" ├─ S1 (Preference Violations) : {stats['s1_penalty']}")
        print(f" ├─ S2 (Workload Fairness Gap) : {stats['s2_penalty']} (max={stats['max_load']}, min={stats['min_load']})")
        print(f" ├─ S3 (Consecutive Invig.)    : {stats['s3_penalty']}")
        print(f" ├─ S4 (Student Day Gap)       : {stats['s4_penalty']}")
        print(f" ├─ Total Physical Rooms Used  : {stats['total_rooms_used']} (Anti-fragmentation)")
        print(f" └─ Overflow Penalty (Online)  : {stats['overflow_count']} exams forced online")
        print(f"Solve time: {stats['wall_time']:.2f}s")

        # Workload distribution
        print(f"\n=== Workload Distribution ===")
        for inst in instance.instructors:
            count = sum(1 for exam in instance.exams if inst.id in solution.assigned_invigilators.get(exam.id, set()))
            bar = "█" * count
            print(f"  Instructor {inst.id:>2}: {count:>3} exams  {bar}")

        # Generate visualizations
        generate_all(instance, solution, stats)
    else:
        print(f"\nNo solution found. ({stats['status']}, time: {stats['wall_time']:.2f}s)")