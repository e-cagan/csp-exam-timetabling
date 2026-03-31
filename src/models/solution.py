"""
A module for defining solution dataclass.
"""

from __future__ import annotations
from dataclasses import dataclass

from .domain import ProblemInstance


@dataclass
class Solution:

    exam_time: dict[int, int]                       # X_e mapping (exam_id, timeslot_id)
    exam_room: dict[int, list[int]]                 # Y_e mapping (exam_id, list of room_ids)
    assigned_invigilators: dict[int, set[int]]      # Only assigned (exam_id, instructor_ids)

    # Detect edge cases
    def __post_init__(self):
        if self.exam_time.keys() != self.exam_room.keys():
            raise ValueError("A time or a room should be defined for every abailable exam.")
        
    
    def is_complete(self, instance: ProblemInstance) -> bool:
        """
        A function that checks is every exam assigned or not.
        """

        # Iterate trough exam ids to check that all exams are assigned
        for exam in instance.exams:
            if exam.id not in self.exam_time or exam.id not in self.exam_room:
                print(f"Exam {exam.id} hasn't defined.")
                return False
            if exam.id not in self.assigned_invigilators:
                print(f"The invigilator(s) should be assigned for exam {exam.id}")
                return False
            
        return True

    
    def to_dict(self) -> dict:
        """
        A function for converting the set of assigned invigilators to list. (JSON Serialization)
        """

        # Convert to serialized dict
        return {
            "exam_time": {str(exam_id): timeslot_id for exam_id, timeslot_id in self.exam_time.items()},
            "exam_room": {str(exam_id): room_id for exam_id, room_id in self.exam_room.items()},
            "assigned_invigilators": {str(exam_id): list(invigilator_set) for exam_id, invigilator_set in self.assigned_invigilators.items()}
        }

    
    @classmethod
    def from_dict(cls, data: dict) -> Solution:
        """
        A function which reverts the serialization. Opposite of to_dict.
        """

        # Convert fields to the opposite of to_dict function
        exam_time = {int(exam_id): timeslot_id for exam_id, timeslot_id in data["exam_time"].items()}
        exam_room = {int(exam_id): room_list for exam_id, room_list in data["exam_room"].items()}
        assigned_invigilators = {int(exam_id): set(invigilator_list) for exam_id, invigilator_list in data["assigned_invigilators"].items()}

        # Return the solution instance with filled fields
        return cls(exam_time=exam_time, exam_room=exam_room, assigned_invigilators=assigned_invigilators)