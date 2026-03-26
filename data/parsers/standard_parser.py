"""
Standard Excel Template Parser for University Exam Timetabling System.

Reads the standardized Excel format with FOUR sheets:
- Rooms: Room_ID, Capacity
- Instructors: Instructor_Name, Is_PhD, Unavailable_Days
- Courses: Course_Code, Instructor_Name
- Enrollments: Course_Code, Student_ID

Completely deterministic: NO synthetic data generation.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Optional

import pandas as pd

from src.models.domain import Exam, TimeSlot, Room, Instructor, ProblemInstance


def parse_standard_template(
    excel_path: str | Path,
    n_days: int = 6,
    periods_per_day: int = 3,
) -> ProblemInstance:
    
    excel_path = Path(excel_path)
    if not excel_path.exists():
        raise FileNotFoundError(f"Excel file not found: {excel_path}")

    # ════════════════════════════════════════════════════════════
    #  TIMESLOTS: Generate deterministic structure
    # ════════════════════════════════════════════════════════════
    timeslots: list[TimeSlot] = []
    for day in range(n_days):
        for period in range(periods_per_day):
            ts_id = day * periods_per_day + period
            timeslots.append(TimeSlot(id=ts_id, day=day, period=period))

    # ════════════════════════════════════════════════════════════
    #  SHEET 1: Rooms
    # ════════════════════════════════════════════════════════════
    try:
        rooms_df = pd.read_excel(excel_path, sheet_name="Rooms")
    except ValueError as e:
        raise ValueError(f"Missing 'Rooms' sheet in {excel_path}: {e}")

    rooms: list[Room] = []
    room_id_map: dict[str, int] = {} 

    for idx, row in rooms_df.iterrows():
        room_str_id = str(row.get("Room_ID", "")).strip()
        if not room_str_id or pd.isna(row.get("Capacity")):
            continue
            
        capacity = int(row["Capacity"])
        if capacity <= 0:
            continue # domain.py requires capacity > 0
            
        numeric_id = len(rooms)
        room_id_map[room_str_id] = numeric_id
        rooms.append(Room(id=numeric_id, capacity=capacity))

    # ════════════════════════════════════════════════════════════
    #  SHEET 2: Instructors
    # ════════════════════════════════════════════════════════════
    try:
        instructors_df = pd.read_excel(excel_path, sheet_name="Instructors")
    except ValueError as e:
        raise ValueError(f"Missing 'Instructors' sheet in {excel_path}: {e}")

    instructors: list[Instructor] = []
    instructor_id_map: dict[str, int] = {}

    for idx, row in instructors_df.iterrows():
        name = str(row.get("Instructor_Name", "")).strip()
        if not name or name == "nan":
            continue
            
        is_phd = _parse_bool(row.get("Is_PhD", False))
        unavailable_days_raw = row.get("Unavailable_Days", "")

        numeric_id = len(instructors)
        instructor_id_map[name] = numeric_id

        # Parse strictly: only the days mentioned are False. Everything else is True.
        unavailable_days: set[int] = set()
        if pd.notna(unavailable_days_raw) and str(unavailable_days_raw).strip():
            for part in str(unavailable_days_raw).split(","):
                part = part.strip()
                if part.isdigit():
                    unavailable_days.add(int(part))

        preferences: dict[int, bool] = {}
        for ts in timeslots:
            preferences[ts.id] = ts.day not in unavailable_days

        # domain.py needs at least one preference, ensure it doesn't crash
        if not preferences:
             preferences[0] = True

        instructors.append(Instructor(
            id=numeric_id,
            is_phd=is_phd,
            preferences=preferences,
        ))

    # ════════════════════════════════════════════════════════════
    #  SHEET 3 & 4: Courses and Enrollments
    # ════════════════════════════════════════════════════════════
    try:
        courses_df = pd.read_excel(excel_path, sheet_name="Courses")
        enrollments_df = pd.read_excel(excel_path, sheet_name="Enrollments")
    except ValueError as e:
        raise ValueError(f"Missing 'Courses' or 'Enrollments' sheet in {excel_path}: {e}")

    # Group students by course
    course_students: dict[str, set[int]] = {}
    for _, row in enrollments_df.iterrows():
        course_code = str(row.get("Course_Code", "")).strip()
        student_str_id = str(row.get("Student_ID", "")).strip()
        
        if not course_code or not student_str_id or student_str_id == "nan":
            continue

        # Extract only digits for student ID (to match domain int requirement)
        numeric_student_id_str = ''.join(filter(str.isdigit, student_str_id))
        if numeric_student_id_str:
            numeric_student_id = int(numeric_student_id_str)
            if course_code not in course_students:
                course_students[course_code] = set()
            course_students[course_code].add(numeric_student_id)

    # Build Exams based strictly on the Courses sheet
    exams: list[Exam] = []
    exam_id_counter = 0

    for _, row in courses_df.iterrows():
        course_code = str(row.get("Course_Code", "")).strip()
        instructor_name = str(row.get("Instructor_Name", "")).strip()
        
        if not course_code or course_code == "nan":
            continue

        # Only create exam if there are enrolled students (prevents domain.py ValueError)
        students = course_students.get(course_code, set())
        if len(students) == 0:
            continue

        # Map instructor (Fallback to 0 if not found, to prevent crashes)
        lecturer_id = instructor_id_map.get(instructor_name, 0)

        # Realistic required invigilator math (1 per 40 students)
        required_invigilators = max(1, math.ceil(len(students) / 40))

        exams.append(Exam(
            id=exam_id_counter,
            student_ids=students,
            lecturer_id=lecturer_id,
            required_invigilators=required_invigilators,
            is_online=False,
        ))
        exam_id_counter += 1

    # ════════════════════════════════════════════════════════════
    #  BUILD AND VALIDATE PROBLEM INSTANCE
    # ════════════════════════════════════════════════════════════
    return ProblemInstance(
        exams=exams,
        timeslots=timeslots,
        rooms=rooms,
        instructors=instructors,
    )


def _parse_bool(value) -> bool:
    if pd.isna(value): return False
    if isinstance(value, bool): return value
    if isinstance(value, (int, float)): return bool(value)
    return str(value).strip().lower() in ("true", "yes", "1", "t", "y", "evet")


def get_template_metadata(excel_path: str | Path) -> dict:
    excel_path = Path(excel_path)
    if not excel_path.exists():
        raise FileNotFoundError(f"Excel file not found: {excel_path}")

    try:
        rooms_df = pd.read_excel(excel_path, sheet_name="Rooms")
        instructors_df = pd.read_excel(excel_path, sheet_name="Instructors")
        courses_df = pd.read_excel(excel_path, sheet_name="Courses")
        enrollments_df = pd.read_excel(excel_path, sheet_name="Enrollments")
    except Exception as e:
        raise ValueError(f"Failed to read template sheets: {e}")

    return {
        "rooms": len(rooms_df),
        "instructors": len(instructors_df),
        "courses": len(courses_df),
        "students": enrollments_df["Student_ID"].nunique() if "Student_ID" in enrollments_df.columns else 0,
        "enrollments": len(enrollments_df),
    }