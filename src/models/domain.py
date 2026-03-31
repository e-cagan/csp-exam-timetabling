"""
A module for defining domain dataclasses to solve afterwards.
"""

from __future__ import annotations
from dataclasses import dataclass


@dataclass
class Exam:
    
    id: int                         # exam id
    student_ids: set[int]           # id's of students
    lecturer_id: int                # id of lecturer
    required_invigilators: int      # The amount of invigilators required
    is_online: bool = False         # Is exam online or not (by default False)

    # Edge case detection
    def __post_init__(self):
        if self.required_invigilators < 0:
            raise ValueError("There can't be negative invigilators.")
        
        # YENİ: Sınav FİZİKSEL ise en az 1 gözetmen şart, ONLINE ise 0 olabilir.
        if self.required_invigilators == 0 and not self.is_online:
            raise ValueError("Physical exams must have at least one invigilator to proceed through examination.")
            
        if len(self.student_ids) <= 0:
            raise ValueError("There must be at least a student to proceed through examination.")
        if self.lecturer_id < 0:
            raise ValueError("There can't be negative id.")
        
    # Pretty formatting
    def __repr__(self):
        return f"Exam(id={self.id}, students={len(self.student_ids)}, lecturer={self.lecturer_id}, invigilators={self.required_invigilators})"


@dataclass
class TimeSlot:

    id: int                         # timeslot id
    day: int                        # number of day. (e.g monday = 0, tuesday = 1... etc.)
    period: int                     # number of period. (e.g morning = 0, noon = 1 etc.)

    # Edge case detection
    def __post_init__(self):
        if self.day < 0 or self.period < 0:
            raise ValueError("Day and/or period should be a positive integer.")


@dataclass
class Room:

    id: int                         # room id
    capacity: int                   # amount of room capacity
    name: str = ""                  # Room name (optional)

    # Edge case detection
    def __post_init__(self):
        if self.capacity <= 0:
            raise ValueError(f"Insufficient or invalid capacity for room {self.id}")


@dataclass
class Instructor:

    id: int                         # instructor id
    is_phd: bool                    # If true, the instructor can both give lectures and be invigilator
    preferences: dict[int, bool]    # key is a timeslot_id where value is if the instructor wants that slot or not.
                                    # pref = 1, penalty = 0 for value True. -- pref = 0, penalty = 1 for value False.

    # Edge case detection
    def __post_init__(self):
        if len(self.preferences) == 0:
            raise ValueError("Instructors should have preferences about timeslots.")


@dataclass
class ProblemInstance:

    exams: list[Exam]               # list of exams
    timeslots: list[TimeSlot]       # list of timeslots
    rooms: list[Room]               # list of rooms
    instructors: list[Instructor]   # list of instructors

    # Edge case detection
    def __post_init__(self):
        # Add instructor ids on a set to check an ID match
        instructor_ids = {ins.id for ins in self.instructors}
        
        if len(self.exams) <= 0 or len(self.timeslots) <= 0 or len(self.rooms) <= 0 or len(self.instructors) <= 0:
            raise ValueError("Undefined problem. Please assign values of all fields.")
        if len(self.timeslots) * len(self.rooms) < len(self.exams):
            raise ValueError("Insufficient amount of slots.")
        
        # Iterate trough exams and it's instructor ids to check is instructor registered
        for exam in self.exams:
            if exam.lecturer_id not in instructor_ids:
                raise ValueError(f"Exam {exam.id}: lecturer {exam.lecturer_id} not found in instructors")
        
    # Pretty formatting
    def __repr__(self):
        return f"ProblemInstance(exams={len(self.exams)}, timeslots={len(self.timeslots)}, rooms={len(self.rooms)}, instructors={len(self.instructors)})"