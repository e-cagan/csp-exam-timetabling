"""
Conflict graph builder for the University Exam Timetabling System.

Constructs an undirected graph where:
  - Nodes represent exams
  - Edges connect exams that share at least one student

This graph is the foundation of the exam timetabling problem:
  - H1 constraint: conflicting exams (connected by an edge) must be in different timeslots
  - The chromatic number of this graph is the MINIMUM number of timeslots needed
  - Graph density indicates problem difficulty (higher density = more constrained)

Time complexity: O(n² · s) where n = number of exams, s = average students per exam.
  For each pair of exams, we compute set intersection on their student_ids.
  Python's set intersection (&) is O(min(|A|, |B|)) on average.

Space complexity: O(n²) worst case for the adjacency list (complete graph).

Example for Okan University (131 exams, ~1190 students):
  Conflict edges: ~1,599   Graph density: ~17.9%
  Meaning ~18% of all exam pairs share at least one student.
"""

from __future__ import annotations
from src.models.domain import Exam


def build_conflict_graph(exams: list[Exam]) -> dict[int, set[int]]:
    """
    Builds an undirected conflict graph from a list of exams.

    Two exams are "in conflict" if they share at least one student.
    This means they CANNOT be scheduled in the same timeslot (H1 constraint).

    The graph is represented as an adjacency list:
      {exam_id: {set of conflicting exam_ids}}

    Every exam appears as a key, even if it has no conflicts (isolated node).
    Edges are bidirectional: if A conflicts with B, then B conflicts with A.

    Args:
        exams: List of Exam objects, each with a student_ids set.

    Returns:
        Adjacency list mapping each exam_id to its set of conflicting exam_ids.
        Example: {0: {1, 3, 7}, 1: {0, 5}, 2: set(), ...}
                 Exam 0 conflicts with exams 1, 3, 7.
                 Exam 2 has no conflicts (can be in any timeslot).
    """

    # Initialize adjacency list — every exam starts with an empty conflict set.
    # Using dict comprehension ensures isolated exams (no conflicts) are included.
    conflicts = {exam.id: set() for exam in exams}

    # Check all unique pairs (i, j) where i < j to avoid duplicate checks.
    # For each pair, compute the intersection of their student sets.
    # If the intersection is non-empty, they share a student → add edge.
    #
    # Python's set intersection operator (&) returns a new set containing
    # elements present in BOTH sets. If it's non-empty (truthy), conflict exists.
    for i in range(len(exams)):
        for j in range(i + 1, len(exams)):
            # Set intersection: O(min(|students_i|, |students_j|))
            if exams[i].student_ids & exams[j].student_ids:
                # Add bidirectional edge (undirected graph)
                conflicts[exams[i].id].add(exams[j].id)
                conflicts[exams[j].id].add(exams[i].id)

    return conflicts