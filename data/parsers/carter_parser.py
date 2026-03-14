"""
Module for parsing the benchmark Carter's dataset (.crs and .stu files)
and integrating it into the custom CSP OOP architecture.
"""

import random
from collections import defaultdict

from src.models.domain import Exam, TimeSlot, Room, Instructor, ProblemInstance


def parse_carter(
    crs_path: str, 
    stu_path: str, 
    n_timeslots: int = 45, 
    periods_per_day: int = 3, 
    n_rooms: int = 15, 
    n_instructors: int = 30, 
    seed: int = 42
) -> ProblemInstance:
    """
    Parses Carter's benchmark dataset and generates missing entities 
    (timeslots, rooms, instructors) synthetically to fit the UETP model.
    
    Args:
        crs_path: Path to the .crs file (Course/Exam definitions).
        stu_path: Path to the .stu file (Student enrollments).
        n_timeslots: Number of synthetic timeslots to generate.
        periods_per_day: How many periods exist in a single day.
        n_rooms: Number of synthetic rooms to generate.
        n_instructors: Number of synthetic instructors to generate.
        seed: Random seed for reproducibility (crucial for academic papers).
    """
    
    # Set seed for reproducible experiments in the paper
    random.seed(seed)

    # ==========================================
    # STEP 1: Parse the .stu file (Student Data)
    # ==========================================
    # We use a defaultdict of sets. If an exam_id doesn't exist yet, 
    # it automatically initializes an empty set for it. O(1) lookups!
    exam_student_ids = defaultdict(set)
    
    with open(stu_path, 'r') as stu_file:
        # Each line represents a unique student. We use enumerate to generate student_ids starting from 0.
        for student_id, line in enumerate(stu_file):
            # Strip whitespace and split the line into individual exam IDs
            parts = line.strip().split()
            if not parts:
                continue
            
            # Add this student's ID to the corresponding exam's set
            for exam_str in parts:
                exam_id = int(exam_str)
                exam_student_ids[exam_id].add(student_id)

    # ==========================================
    # STEP 2: Parse the .crs file (Exam Data)
    # ==========================================
    # The .crs file acts as our source of truth for all valid exams.
    valid_exam_ids = []
    
    with open(crs_path, 'r') as crs_file:
        for line in crs_file:
            parts = line.strip().split()
            if len(parts) >= 2:
                # Format is usually "<exam_id> <number_of_students>"
                exam_id = int(parts[0])
                valid_exam_ids.append(exam_id)
                # Note: We ignore parts[1] (student count) because we directly 
                # calculated the accurate sets from the .stu file in Step 1.

    # ==========================================
    # STEP 3: Generate Synthetic Entities
    # ==========================================
    # Carter dataset lacks Rooms, Timeslots, and Instructors. 
    # We generate them here to test the "Dual-Role Conflict" hypothesis of the paper.

    # Generate Timeslots
    timeslots = [
        TimeSlot(id=i, day=i // periods_per_day, period=i % periods_per_day) 
        for i in range(n_timeslots)
    ]

    # Take the max students to generate rooms more reasonably
    max_students = max(len(exam_student_ids[eid]) for eid in valid_exam_ids if exam_student_ids[eid])

    # Generate Rooms with realistic university capacities [50 to 250]
    rooms = [
        Room(id=i, capacity=random.randint(max_students // 2, max_students + 50))
        for i in range(n_rooms)
    ]

    # Generate Instructors
    # is_phd simulates the "Dual-Role" (T.A.) condition. We set a ~35% probability.
    instructors = []
    for i in range(n_instructors):
        is_phd = random.random() < 0.35
        # 80% chance they are available/prefer a specific timeslot
        prefs = {slot.id: random.random() < 0.80 for slot in timeslots}
        instructors.append(Instructor(id=i, is_phd=is_phd, preferences=prefs))

    # Safety check: Ensure at least one PhD exists to prevent edge case crashes
    phd_ids = [ins.id for ins in instructors if ins.is_phd]
    if not phd_ids:
        instructors[0].is_phd = True
        phd_ids = [instructors[0].id]

    # ==========================================
    # STEP 4: Assemble Exam Objects
    # ==========================================
    exams = []
    
    for exam_id in valid_exam_ids:
        # Get the set of students for this exam. Default to empty set if none found.
        students = exam_student_ids.get(exam_id, set())
        
        # Edge Case Handling for domain.py: 
        # domain.py raises ValueError if an exam has 0 students. 
        # If the benchmark has a phantom exam, we assign a dummy student to bypass the error.
        if len(students) == 0:
            students.add(random.randint(0, 5000))
        
        # Dynamically calculate invigilators needed (e.g., 1 per 40 students)
        # Ensure it is at least 1 to satisfy domain.py constraints.
        req_invig = max(1, len(students) // 40)
        
        # Assign a random instructor as the primary subject lecturer
        lecturer_id = random.choice(phd_ids)

        # Instantiate the OOP Exam object
        exam_obj = Exam(
            id=exam_id,
            student_ids=students,
            lecturer_id=lecturer_id,
            required_invigilators=req_invig
        )
        exams.append(exam_obj)

    # ==========================================
    # STEP 5: Return Final ProblemInstance
    # ==========================================
    return ProblemInstance(
        exams=exams,
        timeslots=timeslots,
        rooms=rooms,
        instructors=instructors
    )