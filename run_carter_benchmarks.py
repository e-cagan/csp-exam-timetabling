"""
Module to run benchmarks on Carter's datasets.
It excludes 'pur-s-93' and runs the remaining 5 instances.
Since Carter only provides student enrollments and exam IDs, 
this script utilizes the synthetic generation capabilities of carter_parser.py
to create rooms, instructors (with dual-role PhDs), and timeslots.
"""

import os
from data.parsers.carter_parser import parse_carter
from src.solvers.cp_solver import solve
from src.models.domain import Room

def run_benchmarks():
    # Define the base path where Carter datasets are stored
    base_path = "data/instances/carter"
    
    # List of Carter datasets to benchmark (excluding pur-s-93-2)
    # The stats (exams and students) are derived from the README/Benchmark table
    # to establish a clear relationship between the files and their complexity.
    datasets = [
        {"name": "hec-s-92-2", "exams": 80,  "students": 2823},
        {"name": "sta-f-83-2", "exams": 138, "students": 549},
        {"name": "yor-f-83-2", "exams": 180, "students": 919},
        {"name": "ear-f-83-2", "exams": 189, "students": 1108},
        {"name": "uta-s-92-2", "exams": 638, "students": 21329}
    ]

    # Configuration for synthetic generation and solver
    # Matching the exact same parameters used in main.py for a fair comparison
    config = {
        "time_limit": 600,        # 600 seconds limit to match Okan University runs
        "enable_s3": False,       # S3 (Consecutive Invigilation) disabled to prevent state space explosion
        "enable_s4": True,        # S4 (Student Day Gap) enabled
        "n_timeslots": 45,        # Synthetic timeslots to generate
        "n_rooms": 20,            # Synthetic physical rooms
        "n_instructors": 40       # Synthetic instructors to handle the load
    }

    print(f"{'='*60}")
    print("STARTING CARTER BENCHMARK SUITE")
    print(f"{'='*60}\n")

    for ds in datasets:
        dataset = ds["name"]
        crs_path = os.path.join(base_path, f"{dataset}.crs")
        stu_path = os.path.join(base_path, f"{dataset}.stu")
        
        print(f"\n{'='*60}")
        print(f"Processing Dataset: {dataset.upper()} (Exams: {ds['exams']}, Students: {ds['students']})")
        print(f"{'='*60}")

        # 1. Parse the Carter dataset and generate synthetic entities
        try:
            instance = parse_carter(
                crs_path=crs_path,
                stu_path=stu_path,
                n_timeslots=config["n_timeslots"],
                n_rooms=config["n_rooms"],
                n_instructors=config["n_instructors"],
                seed=42 # Fixed seed for reproducible results in the paper
            )
            
            # =================================================================
            # FIX FOR KeyError: -1 IN cp_solver.py
            # =================================================================
            # The solver explicitly looks for a virtual room (capacity=100000) 
            # to handle the Overflow Penalty logic (routing physical exams online).
            # Because carter_parser.py only generates physical rooms, we dynamically 
            # inject a Virtual Room here before passing the instance to the solver.
            # This completely avoids touching the solver codebase.
            
            virtual_room_id = len(instance.rooms)
            virtual_room = Room(id=virtual_room_id, capacity=100000, name="ONLINE")
            instance.rooms.append(virtual_room)
            
            print(f"Loaded Carter Instance: {instance}")
            
        except Exception as e:
            print(f"Error parsing {dataset}: {e}")
            continue

        # 2. Solve the instance
        print(f"\nSolving {dataset} with time limit {config['time_limit']}s...")
        solution, stats = solve(
            instance=instance, 
            enable_s3=config["enable_s3"], 
            enable_s4=config["enable_s4"], 
            time_limit=config["time_limit"]
        )

        # 3. Display results in the exact format of main.py
        if solution:
            print(f"\n=== Solution Found ({stats['status']}) ===\n")

            print("Exam  | Timeslot | Room(s)           | Students | Invigilators")
            print("------+----------+-------------------+----------+-------------")
            
            # Re-fetch virtual room id just to be safe
            v_room_id = next((r.id for r in instance.rooms if r.capacity == 100000), -1)

            for exam in instance.exams:
                t = solution.exam_time[exam.id]
                r_list = solution.exam_room[exam.id] # List of room IDs due to Multi-Room Splitting
                s = len(exam.student_ids)
                invig = solution.assigned_invigilators.get(exam.id, set())
                invig_str = ", ".join(str(i) for i in sorted(invig)) if invig else "none"
                
                # Check for virtual/online room
                if v_room_id in r_list:
                    room_display = "ONLINE"
                else:
                    # Combine physical room IDs or names
                    room_names = []
                    for rid in r_list:
                        r_obj = next((rm for rm in instance.rooms if rm.id == rid), None)
                        room_names.append(getattr(r_obj, "name", str(rid)))
                    room_display = ", ".join(room_names)
                    
                print(f"  {exam.id:<4}|    {t:<6}|  {room_display:<17}|  {s:>6}  | {invig_str}")

            print(f"\nTotal exams: {len(instance.exams)}")
            print(f"Timeslots used: {len(set(solution.exam_time.values()))}/{len(instance.timeslots)}")
            
            # Calculate total used physical rooms (flatten the lists and unique them)
            used_physical_rooms = set()
            for r_ids in solution.exam_room.values():
                for rid in r_ids:
                    if rid != v_room_id:
                        used_physical_rooms.add(rid)

            # -1 because we don't count the virtual room in the total physical room count
            print(f"Physical Rooms used: {len(used_physical_rooms)}/{len(instance.rooms) - 1}")

            # Print Optimization Statistics matching main.py exactly
            print(f"\n=== Optimization Stats ===")
            print(f"Objective value: {stats['objective']}")
            print(f" ├─ S1 (Preference Violations) : {stats['s1_penalty']}")
            print(f" ├─ S2 (Workload Fairness Gap) : {stats['s2_penalty']} (max={stats['max_load']}, min={stats['min_load']})")
            print(f" ├─ S3 (Consecutive Invig.)    : {stats['s3_penalty']}")
            print(f" ├─ S4 (Student Day Gap)       : {stats['s4_penalty']}")
            print(f" ├─ Total Physical Rooms Used  : {stats['total_rooms_used']} (Anti-fragmentation)")
            print(f" └─ Overflow Penalty (Online)  : {stats.get('overflow_count', 0)} exams forced online")
            print(f"Solve time: {stats['wall_time']:.2f}s")

            # Print Workload Distribution
            print(f"\n=== Workload Distribution ===")
            for inst in instance.instructors:
                count = sum(1 for exam in instance.exams if inst.id in solution.assigned_invigilators.get(exam.id, set()))
                bar = "█" * count
                print(f"  Instructor {inst.id:>2}: {count:>3} exams  {bar}")
                
        else:
            print(f"\nNo solution found. ({stats['status']}, time: {stats['wall_time']:.2f}s)")

if __name__ == '__main__':
    run_benchmarks()