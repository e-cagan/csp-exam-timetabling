/**
 * excelExport.js — Generates a multi-sheet Excel workbook from solver results.
 *
 * Dependency: `npm install xlsx` (SheetJS Community Edition)
 *
 * Architecture: This is a pure utility with zero React dependencies.
 * It receives plain data objects and returns nothing — it triggers
 * a browser download as a side effect.
 *
 * Sheets:
 *   1. "Schedule"   — every placed exam with room, day, period, invigilators
 *   2. "Unassigned" — exams the solver couldn't place
 *   3. "Summary"    — solver stats (objective, violations, solve time)
 */

import * as XLSX from "xlsx";

const WEEKDAY_NAMES = [
  "Monday", "Tuesday", "Wednesday", "Thursday",
  "Friday", "Saturday", "Sunday",
];

/**
 * Build lookup maps from problemData arrays for O(1) access.
 */
function buildLookups(problemData) {
  const tsMap = {};
  for (const ts of problemData.timeslots) {
    tsMap[ts.id] = ts;
  }

  const roomMap = {};
  for (const r of problemData.rooms) {
    roomMap[r.id] = r;
  }

  const instrMap = {};
  for (const i of problemData.instructors) {
    instrMap[i.id] = i;
  }

  const examMap = {};
  for (const e of problemData.exams) {
    examMap[e.id] = e;
  }

  return { tsMap, roomMap, instrMap, examMap };
}

/**
 * Resolve a day index to a readable label with week wrapping.
 */
function dayLabel(dayIndex) {
  const name = WEEKDAY_NAMES[dayIndex % 7];
  const week = Math.floor(dayIndex / 7) + 1;
  // Only add week suffix if schedule spans more than 7 days
  // The caller doesn't know total days, so always include for clarity
  return week > 1 ? `${name} (W${week})` : name;
}

/**
 * Main export function.
 *
 * @param {object} problemData   — { exams[], timeslots[], rooms[], instructors[] }
 * @param {object} solverResult  — { solution, unassigned[], hardViolations, softPenalty, objective, solveTime }
 * @param {string} datasetName   — e.g. "hec-s-92-2" (used in filename)
 */
export function exportScheduleToExcel(problemData, solverResult, datasetName = "schedule") {
  if (!problemData || !solverResult?.solution) {
    console.warn("exportScheduleToExcel: missing data, aborting.");
    return;
  }

  const { tsMap, roomMap, instrMap, examMap } = buildLookups(problemData);
  const { exam_time, exam_room, assigned_invigilators } = solverResult.solution;

  // ── Sheet 1: Schedule ─────────────────────────────────────
  const scheduleRows = [];

  // Collect and sort placed exams by day → period → room for clean output
  const placed = Object.keys(exam_time).map(Number);
  placed.sort((a, b) => {
    const tsA = tsMap[exam_time[a]] || {};
    const tsB = tsMap[exam_time[b]] || {};
    if (tsA.day !== tsB.day) return (tsA.day ?? 0) - (tsB.day ?? 0);
    if (tsA.period !== tsB.period) return (tsA.period ?? 0) - (tsB.period ?? 0);
    return (exam_room[a] ?? 0) - (exam_room[b] ?? 0);
  });

  for (const examId of placed) {
    const exam = examMap[examId];
    const ts = tsMap[exam_time[examId]];
    const room = roomMap[exam_room[examId]];
    const invIds = assigned_invigilators[examId] || [];
    const invNames = invIds.map((id) => instrMap[id]?.name ?? `#${id}`).join(", ");

    scheduleRows.push({
      "Exam Code":      exam?.code ?? `E${examId}`,
      "Exam Name":      exam?.name ?? `Exam ${examId}`,
      "Students":       exam?.studentCount ?? "—",
      "Room":           room?.label ?? `Room ${exam_room[examId]}`,
      "Room Capacity":  room?.capacity ?? "—",
      "Day":            ts ? dayLabel(ts.day) : "—",
      "Day Index":      ts?.day ?? "—",
      "Period":         ts?.periodLabel ?? `P${ts?.period ?? "?"}`,
      "Invigilators":   invNames || "—",
      "Invg. Count":    invIds.length,
      "Lecturer ID":    exam?.lecturer_id ?? "—",
    });
  }

  const wsSchedule = XLSX.utils.json_to_sheet(scheduleRows);

  // Auto-size columns based on header + content width
  const scheduleColWidths = Object.keys(scheduleRows[0] || {}).map((key) => {
    const maxContent = Math.max(
      key.length,
      ...scheduleRows.map((r) => String(r[key] ?? "").length)
    );
    return { wch: Math.min(maxContent + 2, 40) };
  });
  wsSchedule["!cols"] = scheduleColWidths;

  // ── Sheet 2: Unassigned ───────────────────────────────────
  const unassignedRows = (solverResult.unassigned || []).map((examId) => {
    const exam = examMap[examId];
    return {
      "Exam Code":        exam?.code ?? `E${examId}`,
      "Exam Name":        exam?.name ?? `Exam ${examId}`,
      "Students":         exam?.studentCount ?? "—",
      "Required Invg.":   exam?.required_invigilators ?? "—",
      "Lecturer ID":      exam?.lecturer_id ?? "—",
      "Reason":           "Could not be placed (constraint conflict)",
    };
  });

  const wsUnassigned = unassignedRows.length > 0
    ? XLSX.utils.json_to_sheet(unassignedRows)
    : XLSX.utils.aoa_to_sheet([
        ["No unassigned exams — all exams were successfully placed."],
      ]);

  if (unassignedRows.length > 0) {
    wsUnassigned["!cols"] = Object.keys(unassignedRows[0]).map((key) => ({
      wch: Math.min(Math.max(key.length, 20) + 2, 45),
    }));
  }

  // ── Sheet 3: Summary ──────────────────────────────────────
  const summaryData = [
    ["Exam Timetable — Solver Report"],
    [],
    ["Dataset", datasetName],
    ["Generated", new Date().toLocaleString()],
    [],
    ["Metric", "Value"],
    ["Total Exams", problemData.exams.length],
    ["Exams Placed", placed.length],
    ["Unassigned Exams", (solverResult.unassigned || []).length],
    ["Total Rooms", problemData.rooms.length],
    ["Total Timeslots", problemData.timeslots.length],
    ["Total Instructors", problemData.instructors.length],
    [],
    ["Hard Violations", solverResult.hardViolations ?? 0],
    ["Soft Penalty", solverResult.softPenalty ?? 0],
    ["Objective Value", solverResult.objective ?? "—"],
    ["Solve Time (s)", solverResult.solveTime != null
      ? Number(solverResult.solveTime.toFixed(2))
      : "—"],
  ];

  const wsSummary = XLSX.utils.aoa_to_sheet(summaryData);
  wsSummary["!cols"] = [{ wch: 22 }, { wch: 30 }];

  // ── Assemble Workbook ─────────────────────────────────────
  const wb = XLSX.utils.book_new();
  XLSX.utils.book_append_sheet(wb, wsSchedule, "Schedule");
  XLSX.utils.book_append_sheet(wb, wsUnassigned, "Unassigned");
  XLSX.utils.book_append_sheet(wb, wsSummary, "Summary");

  // ── Trigger Download ──────────────────────────────────────
  const timestamp = new Date().toISOString().slice(0, 10);
  const filename = `timetable_${datasetName}_${timestamp}.xlsx`;
  XLSX.writeFile(wb, filename);
}
