"""
Solution model for the University Exam Timetabling System.

Represents a complete assignment of exams to timeslots, rooms, and invigilators.
This dataclass is the output of the solver and the input to the visualizer.

Multi-Room Support:
  exam_room is dict[int, list[int]] — each exam maps to a LIST of room IDs.
  A small exam might use [5] (single room), while a 446-student exam might
  use [0, 2, 3, 7, 10, 14, ...] (14 rooms). Online exams use [virtual_room_id].

Serialization:
  to_dict() and from_dict() handle JSON conversion for API responses.
  Sets are converted to lists, integer keys to strings (JSON requirement).
"""

from __future__ import annotations
from dataclasses import dataclass

from .domain import ProblemInstance


@dataclass
class Solution:
    """
    A complete exam schedule — the output of the CP-SAT solver.

    Attributes:
        exam_time: Maps exam_id → timeslot_id. Every exam has exactly one timeslot.
        exam_room: Maps exam_id → list of room_ids. Multi-room support means
                   an exam can occupy multiple rooms simultaneously.
                   Online exams: [virtual_room_id] (single virtual room).
                   Physical exams: [room_id] (small) or [r1, r2, ...] (large, split).
        assigned_invigilators: Maps exam_id → set of instructor_ids.
                               Online exams: empty set (no invigilators needed).
                               Physical exams: set of assigned proctor IDs.
    """

    exam_time: dict[int, int]
    exam_room: dict[int, list[int]]
    assigned_invigilators: dict[int, set[int]]

    def __post_init__(self):
        # Every exam must have BOTH a timeslot and a room assignment.
        # If these sets don't match, the solution is incomplete/corrupted.
        if self.exam_time.keys() != self.exam_room.keys():
            raise ValueError(
                "A time or a room should be defined for every available exam."
            )

    def is_complete(self, instance: ProblemInstance) -> bool:
        """
        Verifies that every exam in the instance has a complete assignment.

        Checks three conditions per exam:
          1. Timeslot assigned (exists in exam_time)
          2. Room(s) assigned (exists in exam_room)
          3. Invigilators assigned (exists in assigned_invigilators)

        This is a post-solve sanity check — the solver should always produce
        complete solutions, but this catches edge cases in serialization/deserialization.

        Args:
            instance: The original problem instance to validate against.

        Returns:
            True if all exams have complete assignments, False otherwise.
        """
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
        Serializes the solution to a JSON-compatible dictionary.

        Conversions performed:
          - Integer keys → string keys (JSON requires string keys)
          - Sets → lists (JSON has no set type)
          - Room lists are preserved as-is (already JSON-compatible)

        Used by the FastAPI backend to send solutions to the frontend.

        Returns:
            Dictionary with string keys and JSON-serializable values.
        """
        return {
            "exam_time": {
                str(exam_id): timeslot_id
                for exam_id, timeslot_id in self.exam_time.items()
            },
            "exam_room": {
                str(exam_id): room_ids
                for exam_id, room_ids in self.exam_room.items()
            },
            "assigned_invigilators": {
                str(exam_id): list(invigilator_set)
                for exam_id, invigilator_set in self.assigned_invigilators.items()
            },
        }

    @classmethod
    def from_dict(cls, data: dict) -> Solution:
        """
        Deserializes a solution from a JSON-compatible dictionary.

        Reverses the conversions in to_dict():
          - String keys → integer keys
          - Lists → sets (for invigilators)
          - Room lists are preserved as-is

        Used by the frontend to reconstruct solutions received from the API.

        Args:
            data: Dictionary with string keys (from JSON parsing).

        Returns:
            Solution instance with proper Python types.
        """
        exam_time = {
            int(exam_id): timeslot_id
            for exam_id, timeslot_id in data["exam_time"].items()
        }
        exam_room = {
            int(exam_id): room_list
            for exam_id, room_list in data["exam_room"].items()
        }
        assigned_invigilators = {
            int(exam_id): set(invigilator_list)
            for exam_id, invigilator_list in data["assigned_invigilators"].items()
        }

        return cls(
            exam_time=exam_time,
            exam_room=exam_room,
            assigned_invigilators=assigned_invigilators,
        )