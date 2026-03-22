"""
Visualization module for the University Exam Timetabling System.

Generates publication-ready charts from a solved ProblemInstance + Solution pair.
All figures are saved as PNG files to the specified output directory.

Charts generated:
  1. Timetable Grid     — exams placed on a timeslot × room grid
  2. Workload Bar Chart  — invigilation load per instructor (fairness visualization)
  3. Slot Utilization    — how many exams per timeslot (capacity usage)
  4. Exam Size Distribution — histogram of student counts per exam
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
    Generates all visualizations and saves them to output_dir.

    Args:
        instance: The solved problem instance.
        solution: The solution returned by the solver.
        stats: The stats dict returned by cp_solver.solve().
        output_dir: Directory to save figures.
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
    Empty cells mean no exam is scheduled there.

    This is the most important visualization for the paper — it shows
    the entire schedule at a glance and visually confirms H3 (no room clash).
    """

    n_timeslots = len(instance.timeslots)
    n_rooms = len(instance.rooms)

    # Build the grid: -1 means empty
    grid = np.full((n_rooms, n_timeslots), -1, dtype=int)

    for exam in instance.exams:
        t = solution.exam_time[exam.id]
        r = solution.exam_room[exam.id]
        grid[r][t] = exam.id

    # Create figure
    fig, ax = plt.subplots(figsize=(max(12, n_timeslots * 0.8), max(4, n_rooms * 0.6)))

    # Color: cells with exams are colored, empty cells are white
    colored_grid = np.where(grid >= 0, 1, 0).astype(float)
    ax.imshow(colored_grid, cmap="Blues", aspect="auto", vmin=0, vmax=2)

    # Add exam IDs as text in each cell
    for r in range(n_rooms):
        for t in range(n_timeslots):
            if grid[r][t] >= 0:
                ax.text(t, r, str(grid[r][t]), ha="center", va="center",
                        fontsize=7, fontweight="bold", color="black")

    # Labels
    ax.set_xticks(range(n_timeslots))
    ax.set_xticklabels([f"T{t}" for t in range(n_timeslots)], fontsize=8)
    ax.set_yticks(range(n_rooms))
    ax.set_yticklabels([f"Room {r}" for r in range(n_rooms)], fontsize=8)
    ax.set_xlabel("Timeslot", fontsize=11)
    ax.set_ylabel("Room", fontsize=11)
    ax.set_title("Exam Timetable Grid", fontsize=13, fontweight="bold")

    # Grid lines
    ax.set_xticks(np.arange(-0.5, n_timeslots, 1), minor=True)
    ax.set_yticks(np.arange(-0.5, n_rooms, 1), minor=True)
    ax.grid(which="minor", color="gray", linewidth=0.5)
    ax.tick_params(which="minor", size=0)

    plt.tight_layout()
    path = os.path.join(output_dir, "timetable_grid.png")
    plt.savefig(path, dpi=150)
    plt.close()
    print(f"  Saved: {path}")


def workload_chart(instance: ProblemInstance, solution: Solution, stats: dict, output_dir: str):
    """
    Workload Bar Chart: shows how many exams each instructor invigilates.
    A flat bar chart = perfect fairness (S2 penalty = 0).
    Uneven bars = unfair distribution.

    This directly visualizes the Min-Max fairness objective.
    The chart includes a horizontal line for the average load.
    """

    # Count exams per instructor
    instructor_ids = sorted([inst.id for inst in instance.instructors])
    loads = []
    for inst_id in instructor_ids:
        count = sum(
            1 for exam in instance.exams
            if inst_id in solution.assigned_invigilators.get(exam.id, set())
        )
        loads.append(count)

    avg_load = np.mean(loads)

    # Create figure
    fig, ax = plt.subplots(figsize=(max(10, len(instructor_ids) * 0.4), 5))

    # Color bars: green if at average, yellow/red if deviating
    colors = []
    for load in loads:
        if load == int(avg_load) or load == int(avg_load) + 1:
            colors.append("#4CAF50")  # green — fair
        elif abs(load - avg_load) <= 1:
            colors.append("#FFC107")  # yellow — slightly off
        else:
            colors.append("#F44336")  # red — unfair

    bars = ax.bar(instructor_ids, loads, color=colors, edgecolor="black", linewidth=0.5)

    # Average line
    ax.axhline(y=avg_load, color="navy", linestyle="--", linewidth=1.5, label=f"Average: {avg_load:.1f}")

    # Labels
    ax.set_xlabel("Instructor ID", fontsize=11)
    ax.set_ylabel("Number of Exams Invigilated", fontsize=11)
    ax.set_title("Invigilator Workload Distribution (S2 Fairness)", fontsize=13, fontweight="bold")
    ax.set_xticks(instructor_ids)
    ax.set_xticklabels(instructor_ids, fontsize=7)
    ax.legend(fontsize=10)

    # Stats annotation
    s2_text = f"S2 gap: {stats.get('s2_penalty', '?')}  |  Max: {stats.get('max_load', '?')}  |  Min: {stats.get('min_load', '?')}"
    ax.annotate(s2_text, xy=(0.5, 0.97), xycoords="axes fraction",
                ha="center", va="top", fontsize=9,
                bbox=dict(boxstyle="round,pad=0.3", facecolor="lightyellow", edgecolor="gray"))

    plt.tight_layout()
    path = os.path.join(output_dir, "workload_chart.png")
    plt.savefig(path, dpi=150)
    plt.close()
    print(f"  Saved: {path}")


def slot_utilization(instance: ProblemInstance, solution: Solution, output_dir: str):
    """
    Slot Utilization Chart: how many exams are scheduled in each timeslot.
    Shows whether the schedule is spread out or concentrated.
    Taller bars mean more exams competing for rooms in that slot.
    """

    n_timeslots = len(instance.timeslots)

    # Count exams per timeslot
    slot_counts = defaultdict(int)
    for exam in instance.exams:
        t = solution.exam_time[exam.id]
        slot_counts[t] += 1

    slots = list(range(n_timeslots))
    counts = [slot_counts.get(t, 0) for t in slots]
    max_possible = len(instance.rooms)  # max exams per slot = number of rooms

    # Create figure
    fig, ax = plt.subplots(figsize=(max(10, n_timeslots * 0.5), 5))

    ax.bar(slots, counts, color="#2196F3", edgecolor="black", linewidth=0.5)
    ax.axhline(y=max_possible, color="red", linestyle="--", linewidth=1.5,
               label=f"Room limit: {max_possible}")

    ax.set_xlabel("Timeslot", fontsize=11)
    ax.set_ylabel("Number of Exams", fontsize=11)
    ax.set_title("Timeslot Utilization", fontsize=13, fontweight="bold")
    ax.set_xticks(slots)
    ax.set_xticklabels([f"T{t}" for t in slots], fontsize=8)
    ax.legend(fontsize=10)

    plt.tight_layout()
    path = os.path.join(output_dir, "slot_utilization.png")
    plt.savefig(path, dpi=150)
    plt.close()
    print(f"  Saved: {path}")


def exam_size_distribution(instance: ProblemInstance, output_dir: str):
    """
    Exam Size Distribution: histogram of how many students each exam has.
    Shows the problem structure — are exams mostly small or large?
    Useful for understanding H2 (room capacity) pressure.
    """

    sizes = [len(exam.student_ids) for exam in instance.exams]

    fig, ax = plt.subplots(figsize=(8, 5))

    ax.hist(sizes, bins=20, color="#9C27B0", edgecolor="black", linewidth=0.5, alpha=0.85)

    ax.axvline(x=np.mean(sizes), color="red", linestyle="--", linewidth=1.5,
               label=f"Mean: {np.mean(sizes):.0f} students")
    ax.axvline(x=np.median(sizes), color="orange", linestyle="--", linewidth=1.5,
               label=f"Median: {np.median(sizes):.0f} students")

    ax.set_xlabel("Number of Students per Exam", fontsize=11)
    ax.set_ylabel("Frequency", fontsize=11)
    ax.set_title("Exam Size Distribution", fontsize=13, fontweight="bold")
    ax.legend(fontsize=10)

    plt.tight_layout()
    path = os.path.join(output_dir, "exam_size_distribution.png")
    plt.savefig(path, dpi=150)
    plt.close()
    print(f"  Saved: {path}")