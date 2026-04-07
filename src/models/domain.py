"""
Domain model for the University Exam Timetabling System.

Defines the core data structures that represent the scheduling problem.
These dataclasses are the single source of truth — every other module
(solvers, parsers, visualizers, API) operates on these types.

Architecture:
  Exam          — A single exam with students, lecturer, and invigilator requirements
  TimeSlot      — A (day, period) pair representing when an exam can be scheduled
  Room          — A physical classroom or virtual online room with capacity
  Instructor    — An academic staff member with PhD status and timeslot preferences
  ProblemInstance — The complete scheduling problem combining all of the above

Design decisions:
  - set[int] for student_ids: O(1) intersection for conflict graph, O(1) membership
  - dict[int, bool] for preferences: sparse representation, missing keys default to True
  - is_online flag on Exam: enables zero-invigilator online routing without changing domain
  - name field on Room: enables human-readable output (C300 instead of Room 0)
  - Validation in __post_init__: catches data issues at construction time, not solve time
"""

from __future__ import annotations
import warnings
from dataclasses import dataclass


@dataclass
class Exam:
    """
    Represents a single university exam to be scheduled.

    Each exam has a set of enrolled students (used for conflict detection),
    a responsible lecturer (used for H4 dual-role conflict), and a required
    number of invigilators (used for H6 and S2 fairness).

    Online exams (is_online=True) are treated specially:
      - Required invigilators can be 0 (no physical proctoring needed)
      - Forced to virtual room by H2 (capacity 100,000)
      - Excluded from H3 room clash (virtual room has unlimited concurrency)
      - Still subject to H1 (student time conflict) and S4 (day gap)

    Attributes:
        id: Unique exam identifier (0-indexed, sequential)
        student_ids: Set of enrolled student IDs. Used to build conflict graph.
                     Two exams sharing a student cannot be in the same timeslot.
        lecturer_id: ID of the responsible instructor. Must exist in ProblemInstance.instructors.
                     Used by H4 to prevent dual-role scheduling conflicts.
        required_invigilators: Number of proctors needed. Typically 1 per 40 students.
                               Can be 0 for online exams; physical exams with 0 emit a
                               warning and allow the solver to handle resource allocation.
        is_online: If True, exam is routed to virtual room with 0 invigilators.
                   Set by parser for weekend exams or explicitly marked online exams.
    """

    id: int
    student_ids: set[int]
    lecturer_id: int
    required_invigilators: int
    is_online: bool = False

    def __post_init__(self):
        # Negative invigilators make no sense in any context
        if self.required_invigilators < 0:
            raise ValueError("There can't be negative invigilators.")

        # Physical exams with zero invigilators are unusual but not fatal.
        # Emit a warning and let the solver handle resource allocation rather
        # than crashing the request with a 422 before the solver is even reached.
        if self.required_invigilators == 0 and not self.is_online:
            warnings.warn(
                f"Exam {self.id} is a physical exam with 0 required invigilators. "
                "The solver will handle resource allocation.",
                UserWarning,
                stacklevel=2,
            )

        # An exam without students is meaningless — likely a parser error
        if len(self.student_ids) <= 0:
            raise ValueError(
                "There must be at least a student to proceed through examination."
            )

        # Negative IDs indicate data corruption
        if self.lecturer_id < 0:
            raise ValueError("There can't be negative id.")

    def __repr__(self):
        return (
            f"Exam(id={self.id}, students={len(self.student_ids)}, "
            f"lecturer={self.lecturer_id}, invigilators={self.required_invigilators})"
        )


@dataclass
class TimeSlot:
    """
    Represents a schedulable time period for exams.

    Each timeslot is identified by a (day, period) pair:
      - day: 0-indexed day number (0=first exam day, 1=second, etc.)
      - period: 0-indexed period within the day (0=morning, 1=late morning, etc.)

    The timeslot ID is typically day * periods_per_day + period, creating a
    linear ordering that the solver uses for integer variables.

    Example with 5 periods per day:
      Day 0, Period 0 → ID 0  (08:50-10:20)
      Day 0, Period 1 → ID 1  (10:30-12:00)
      Day 0, Period 4 → ID 4  (15:50-17:20)
      Day 1, Period 0 → ID 5  (next day, morning)

    Attributes:
        id: Unique timeslot identifier (used as domain value for exam_times variables)
        day: Day index (0-based). Used by S4 to compute day gaps between exams.
        period: Period index within the day (0-based). Used by S3 for consecutive detection.
    """

    id: int
    day: int
    period: int

    def __post_init__(self):
        if self.day < 0 or self.period < 0:
            raise ValueError("Day and/or period should be a positive integer.")


@dataclass
class Room:
    """
    Represents a physical classroom or virtual online room.

    Physical rooms have real capacities (e.g., C300 → 40 seats, C106 → 53 seats).
    The virtual room (capacity=100,000) acts as a sink for online exams,
    allowing unlimited concurrent online exams in the same timeslot.

    With the multi-room architecture, a single exam can use MULTIPLE rooms
    simultaneously. For example, a 446-student exam might use 14 rooms
    (C106 + C108 + C300 + ... = 446+ total capacity).

    The name field provides human-readable labels for output and visualization.
    Without it, exam assignments would show "Room 5" instead of "C303".

    Attributes:
        id: Unique room identifier (0-indexed, sequential)
        capacity: Maximum number of students the room can hold.
                  Physical rooms: 14-53 (real Okan data).
                  Virtual room: 100,000 (effectively unlimited).
        name: Human-readable room name (e.g., "C300", "203-MLAB1", "ONLINE").
              Optional — defaults to empty string. Used by visualize.py and API response.
    """

    id: int
    capacity: int
    name: str = ""

    def __post_init__(self):
        if self.capacity <= 0:
            raise ValueError(
                f"Insufficient or invalid capacity for room {self.id}"
            )


@dataclass
class Instructor:
    """
    Represents an academic staff member who can invigilate exams.

    Each instructor has a PhD status flag and a timeslot preference dictionary:
      - is_phd: Determines eligibility for lecturing + invigilating (dual-role, H4).
        In Okan data, PhD status is parsed from academic titles (DR., PROF., DOÇ.).
        Non-PhD staff (AR. GÖR.) can only invigilate, not lecture.
      - preferences: Maps timeslot_id → bool. True = available, False = leave day.
        Used by S1 to penalize assignments to unwanted timeslots.
        In Okan data, parsed from İZİN GÜNLERİ (leave days) sheet.

    Example preferences for an instructor with Monday and Friday leave:
      {0: False, 1: False, ..., 4: False,   # Monday slots (day 0)
       5: True, 6: True, ..., 9: True,      # Tuesday slots (day 1)
       ...
       20: False, 21: False, ..., 24: False} # Friday slots (day 4)

    Attributes:
        id: Unique instructor identifier (0-indexed, sequential)
        is_phd: True if instructor holds a doctoral degree (DR., PROF., DOÇ.)
        preferences: dict mapping timeslot_id → availability boolean.
                     Missing keys default to True (available) in the solver.
    """

    id: int
    is_phd: bool
    preferences: dict[int, bool]

    def __post_init__(self):
        # Empty preferences means the parser failed to provide timeslot data.
        # The solver needs at least one preference to build S1 cost variables.
        if len(self.preferences) == 0:
            raise ValueError("Instructors should have preferences about timeslots.")


@dataclass
class ProblemInstance:
    """
    The complete exam timetabling problem, ready to be solved.

    Bundles all entities (exams, timeslots, rooms, instructors) and validates
    that the instance is internally consistent before passing to the solver.

    Validation checks:
      1. All entity lists are non-empty (otherwise nothing to solve)
      2. Sufficient slot-room capacity: |timeslots| × |rooms| >= |exams|
         (pigeonhole principle — there must be enough (slot, room) pairs)
      3. Every exam's lecturer exists in the instructor list
         (otherwise H4 would reference a nonexistent instructor)

    Attributes:
        exams: List of Exam objects to be scheduled
        timeslots: List of TimeSlot objects defining the scheduling horizon
        rooms: List of Room objects (physical + virtual) defining available spaces
        instructors: List of Instructor objects who can invigilate
    """

    exams: list[Exam]
    timeslots: list[TimeSlot]
    rooms: list[Room]
    instructors: list[Instructor]

    def __post_init__(self):
        # Build instructor ID set for O(1) lookup during validation
        instructor_ids = {ins.id for ins in self.instructors}

        # Ensure all entity lists are populated
        if (len(self.exams) <= 0 or len(self.timeslots) <= 0
                or len(self.rooms) <= 0 or len(self.instructors) <= 0):
            raise ValueError(
                "Undefined problem. Please assign values of all fields."
            )

        # Pigeonhole check: enough (timeslot, room) pairs for all exams?
        # With multi-room support, an exam can use multiple rooms in one slot,
        # so this is a loose lower bound — but still catches obvious misconfigurations.
        if len(self.timeslots) * len(self.rooms) < len(self.exams):
            raise ValueError("Insufficient amount of slots.")

        # Every exam's lecturer must exist in the instructor pool.
        # Otherwise H4 (lecturer conflict) would try to constrain a ghost instructor.
        for exam in self.exams:
            if exam.lecturer_id not in instructor_ids:
                raise ValueError(
                    f"Exam {exam.id}: lecturer {exam.lecturer_id} "
                    f"not found in instructors"
                )

    def __repr__(self):
        return (
            f"ProblemInstance(exams={len(self.exams)}, "
            f"timeslots={len(self.timeslots)}, "
            f"rooms={len(self.rooms)}, "
            f"instructors={len(self.instructors)})"
        )