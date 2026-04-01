"""
Visualization module for the University Exam Timetabling System.

Generates publication-ready charts from a solved ProblemInstance + Solution pair.
All figures are saved as PNG files to the specified output directory.

Charts generated:
  1. Timetable Grid         — exams on a timeslot × room grid (multi-room support)
  2. Workload Bar Chart     — invigilation load per instructor (fairness vis.)
  3. Slot Utilization       — physical room usage per timeslot (capacity vis.)
  4. Exam Size Distribution — histogram of student counts (problem structure vis.)

Multi-Room Support:
  Solution.exam_room is now dict[int, list[int]]. An exam can appear in
  multiple rooms for the same timeslot (e.g., exam 34 in 14 rooms).
  The timetable grid and slot utilization charts handle this by iterating
  over room lists instead of single room values.

Room Labels:
  Uses Room.name (e.g., "C300", "203-MLAB1", "ONLINE") from the domain model
  instead of generic "Room 0" labels. Falls back to "R-{id}" if name is empty.
"""

import os
from collections import defaultdict

import matplotlib.pyplot as plt
import numpy as np

from src.models.domain import ProblemInstance
from src.models.solution import Solution


def generate_all(
    instance: ProblemInstance,
    solution: Solution,
    stats: dict,
    output_dir: str = "experiments/figures"
):
    """
    Generates all four visualizations and saves them to output_dir.

    Args:
        instance: The solved problem instance (provides exam/room/instructor metadata).
        solution: The solution returned by the solver (provides assignments).
        stats: The stats dict returned by cp_solver.solve() (provides penalty values).
        output_dir: Directory to save PNG files. Created if it doesn't exist.
    """
    os.makedirs(output_dir, exist_ok=True)

    timetable_grid(instance, solution, output_dir)
    workload_chart(instance, solution, stats, output_dir)
    slot_utilization(instance, solution, output_dir)
    exam_size_distribution(instance, output_dir)

    print(f"\nAll figures saved to {output_dir}/")


def timetable_grid(instance: ProblemInstance, solution: Solution, output_dir: str):
    """
    Timetable Grid: a 2D heatmap where x=timeslot, y=room.

    Each cell shows the exam ID assigned to that (timeslot, room) pair.
    Empty cells (no exam scheduled) are white.
    Occupied cells are colored blue with the exam ID as text.

    Multi-Room Support:
      A single exam ID can appear in MULTIPLE cells for the same timeslot
      if the exam was split across rooms. For example, exam 34 (446 students)
      might appear in 14 room rows at timeslot T4.

    Room labels are pulled from Room.name in the domain model,
    showing real names like "C300", "203-MLAB1", "ONLINE" instead of indices.

    Args:
        instance: The problem instance (for room/timeslot metadata).
        solution: The solver output (for exam-to-timeslot/room assignments).
        output_dir: Where to save the PNG file.
    """
    n_timeslots = len(instance.timeslots)
    n_rooms = len(instance.rooms)

    # Build the grid: -1 means empty (no exam in this room at this timeslot)
    grid = np.full((n_rooms, n_timeslots), -1, dtype=int)

    for exam in instance.exams:
        t = solution.exam_time[exam.id]
        r_list = solution.exam_room[exam.id]  # Multi-room: list of room IDs

        # Fill grid cell for EACH room the exam occupies
        for r in r_list:
            if 0 <= r < n_rooms:  # Bounds check (safety)
                grid[r][t] = exam.id

    # Create figure — size scales with problem dimensions
    fig, ax = plt.subplots(
        figsize=(max(12, n_timeslots * 0.8), max(4, n_rooms * 0.6))
    )

    # Color occupied cells blue, empty cells white
    colored_grid = np.where(grid >= 0, 1, 0).astype(float)
    ax.imshow(colored_grid, cmap="Blues", aspect="auto", vmin=0, vmax=2)

    # Overlay exam IDs as text in each occupied cell
    for r in range(n_rooms):
        for t in range(n_timeslots):
            if grid[r][t] >= 0:
                ax.text(
                    t, r, str(grid[r][t]),
                    ha="center", va="center",
                    fontsize=7, fontweight="bold", color="black"
                )

    # Axis labels
    ax.set_xticks(range(n_timeslots))
    ax.set_xticklabels([f"T{t}" for t in range(n_timeslots)], fontsize=8)
    ax.set_yticks(range(n_rooms))

    # Use real room names from domain model (e.g., "C300", "ONLINE")
    # Fall back to "R-{id}" if Room.name is empty
    room_labels = [
        rm.name if rm.name else f"R-{rm.id}"
        for rm in instance.rooms
    ]
    ax.set_yticklabels(room_labels, fontsize=8)

    ax.set_xlabel("Timeslot", fontsize=11)
    ax.set_ylabel("Room", fontsize=11)
    ax.set_title(
        "Exam Timetable Grid (Multi-Room Support)",
        fontsize=13, fontweight="bold"
    )

    # Add grid lines between cells for visual clarity
    ax.set_xticks(np.arange(-0.5, n_timeslots, 1), minor=True)
    ax.set_yticks(np.arange(-0.5, n_rooms, 1), minor=True)
    ax.grid(which="minor", color="gray", linewidth=0.5)
    ax.tick_params(which="minor", size=0)

    plt.tight_layout()
    path = os.path.join(output_dir, "timetable_grid_s3_disabled.png")
    plt.savefig(path, dpi=150)
    plt.close()
    print(f"  Saved: {path}")


def workload_chart(
    instance: ProblemInstance,
    solution: Solution,
    stats: dict,
    output_dir: str
):
    """
    Workload Bar Chart: invigilation load per instructor.

    Each bar represents how many exams an instructor was assigned to invigilate.
    Color coding:
      - Green: at or near average (fair assignment)
      - Red: more than 1 away from average (unfair — either overloaded or underloaded)

    A horizontal dashed line shows the average load across all instructors.
    An annotation box displays S2 gap, max load, and min load.

    This chart directly visualizes the Min-Max fairness objective (S2).
    A flat chart (all bars same height) = perfect fairness (gap=0).

    Note: Online exams have 0 invigilators, so they don't contribute to workload.
    This can widen the S2 gap because fewer total assignments are distributed.

    Args:
        instance: The problem instance (for instructor metadata).
        solution: The solver output (for invigilator assignments).
        stats: The solver stats (for S2 penalty display).
        output_dir: Where to save the PNG file.
    """
    instructor_ids = sorted([inst.id for inst in instance.instructors])

    # Count exams per instructor (how many exams they invigilate)
    loads = []
    for inst_id in instructor_ids:
        count = sum(
            1 for exam in instance.exams
            if inst_id in solution.assigned_invigilators.get(exam.id, set())
        )
        loads.append(count)

    avg_load = np.mean(loads)

    fig, ax = plt.subplots(
        figsize=(max(10, len(instructor_ids) * 0.4), 5)
    )

    # Color bars based on deviation from average
    colors = []
    for load in loads:
        if load == int(avg_load) or load == int(avg_load) + 1:
            colors.append("#4CAF50")   # Green — fair (at average ± rounding)
        elif abs(load - avg_load) <= 1:
            colors.append("#FFC107")   # Yellow — slightly off
        else:
            colors.append("#F44336")   # Red — unfair (>1 from average)

    ax.bar(
        instructor_ids, loads,
        color=colors, edgecolor="black", linewidth=0.5
    )

    # Average load line
    ax.axhline(
        y=avg_load, color="navy", linestyle="--", linewidth=1.5,
        label=f"Average: {avg_load:.1f}"
    )

    ax.set_xlabel("Instructor ID", fontsize=11)
    ax.set_ylabel("Number of Exams Invigilated", fontsize=11)
    ax.set_title(
        "Invigilator Workload Distribution (S2 Fairness)",
        fontsize=13, fontweight="bold"
    )
    ax.set_xticks(instructor_ids)

    # Use instructor names if available, fall back to ID
    inst_labels = [
        getattr(inst, "name", str(inst.id))
        for inst in instance.instructors
    ]
    ax.set_xticklabels(inst_labels, fontsize=7, rotation=45, ha="right")
    ax.legend(fontsize=10)

    # S2 stats annotation box
    s2_text = (
        f"S2 gap: {stats.get('s2_penalty', '?')}  |  "
        f"Max: {stats.get('max_load', '?')}  |  "
        f"Min: {stats.get('min_load', '?')}"
    )
    ax.annotate(
        s2_text, xy=(0.5, 0.97), xycoords="axes fraction",
        ha="center", va="top", fontsize=9,
        bbox=dict(boxstyle="round,pad=0.3", facecolor="lightyellow", edgecolor="gray")
    )

    plt.tight_layout()
    path = os.path.join(output_dir, "workload_chart_s3_disabled.png")
    plt.savefig(path, dpi=150)
    plt.close()
    print(f"  Saved: {path}")


def slot_utilization(
    instance: ProblemInstance,
    solution: Solution,
    output_dir: str
):
    """
    Slot Utilization Chart: physical rooms utilized per timeslot.

    Each bar shows how many physical room-slots are occupied in that timeslot.
    A red dashed line shows the total number of physical rooms (the ceiling).
    Bars approaching the red line indicate near-capacity timeslots.

    Multi-Room Support:
      Each physical room used by an exam in a timeslot counts as 1.
      If exam 34 uses 14 rooms at T4, that contributes 14 to T4's bar.
      Virtual (ONLINE) rooms are excluded from the count.

    This chart helps identify scheduling bottlenecks — timeslots where
    room availability is nearly exhausted.

    Args:
        instance: The problem instance (for room/timeslot metadata).
        solution: The solver output (for room assignments).
        output_dir: Where to save the PNG file.
    """
    n_timeslots = len(instance.timeslots)

    # Identify virtual room to exclude from physical room counts
    virtual_room_id = next(
        (r.id for r in instance.rooms if r.capacity == 100000), -1
    )

    # Count physical room-slots used per timeslot
    slot_room_counts = defaultdict(int)
    for exam in instance.exams:
        t = solution.exam_time[exam.id]
        r_list = solution.exam_room[exam.id]
        # Count only physical rooms (exclude virtual/online room)
        physical_rooms_used = sum(1 for r in r_list if r != virtual_room_id)
        slot_room_counts[t] += physical_rooms_used

    slots = list(range(n_timeslots))
    counts = [slot_room_counts.get(t, 0) for t in slots]

    # Total physical rooms available (virtual room excluded)
    max_possible = len([r for r in instance.rooms if r.id != virtual_room_id])

    fig, ax = plt.subplots(
        figsize=(max(10, n_timeslots * 0.5), 5)
    )

    ax.bar(slots, counts, color="#2196F3", edgecolor="black", linewidth=0.5)
    ax.axhline(
        y=max_possible, color="red", linestyle="--", linewidth=1.5,
        label=f"Physical Room Limit: {max_possible}"
    )

    ax.set_xlabel("Timeslot", fontsize=11)
    ax.set_ylabel("Rooms Utilized", fontsize=11)
    ax.set_title(
        "Timeslot Room Utilization", fontsize=13, fontweight="bold"
    )
    ax.set_xticks(slots)
    ax.set_xticklabels([f"T{t}" for t in slots], fontsize=8)
    ax.legend(fontsize=10)

    plt.tight_layout()
    path = os.path.join(output_dir, "slot_utilization_s3_disabled.png")
    plt.savefig(path, dpi=150)
    plt.close()
    print(f"  Saved: {path}")


def exam_size_distribution(instance: ProblemInstance, output_dir: str):
    """
    Exam Size Distribution: histogram of student counts per exam.

    Shows the structural characteristics of the problem:
      - Left-skewed (many small exams) vs right-skewed (many large exams)
      - Long tail indicates a few very large exams requiring multi-room splitting
      - Mean vs median difference indicates skewness

    Vertical lines mark the mean and median for quick reference.

    For Okan University data:
      Mean ≈ 56, Median ≈ 25 (right-skewed — many small exams, few large ones)
      Long tail extends to 446 students (exam 34, split across 14 rooms)

    This chart helps explain H2 pressure: exams in the tail need multi-room
    splitting, which is the primary driver of solver complexity.

    Args:
        instance: The problem instance (for exam student counts).
        output_dir: Where to save the PNG file.
    """
    sizes = [len(exam.student_ids) for exam in instance.exams]

    fig, ax = plt.subplots(figsize=(8, 5))

    ax.hist(
        sizes, bins=20,
        color="#9C27B0", edgecolor="black", linewidth=0.5, alpha=0.85
    )

    # Mean and median reference lines
    ax.axvline(
        x=np.mean(sizes), color="red", linestyle="--", linewidth=1.5,
        label=f"Mean: {np.mean(sizes):.0f} students"
    )
    ax.axvline(
        x=np.median(sizes), color="orange", linestyle="--", linewidth=1.5,
        label=f"Median: {np.median(sizes):.0f} students"
    )

    ax.set_xlabel("Number of Students per Exam", fontsize=11)
    ax.set_ylabel("Frequency", fontsize=11)
    ax.set_title(
        "Exam Size Distribution", fontsize=13, fontweight="bold"
    )
    ax.legend(fontsize=10)

    plt.tight_layout()
    path = os.path.join(output_dir, "exam_size_distribution_s3_disabled.png")
    plt.savefig(path, dpi=150)
    plt.close()
    print(f"  Saved: {path}")