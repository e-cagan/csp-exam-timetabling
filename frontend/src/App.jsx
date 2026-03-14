import { useState, useEffect, useCallback, useRef } from "react";
import {
  Upload,
  Play,
  Download,
  CheckCircle2,
  AlertTriangle,
  X,
  FileSpreadsheet,
  Clock,
  Users,
  BookOpen,
  DoorOpen,
  GripVertical,
  Loader2,
  Shield,
  ChevronDown,
  ChevronRight,
  Info,
  Zap,
  AlertCircle,
  BarChart3,
  CalendarDays,
  PackageOpen,
} from "lucide-react";


/* ────────────────────────────────────────────────────────────
   MOCK DATA — mirrors Python domain.py structures exactly.

   KEY ARCHITECTURAL DECISION (Req #3):
   Day names and period labels are NOW embedded inside the
   timeslot objects themselves — the frontend has ZERO hardcoded
   UI label arrays. The backend (or Excel parser) is responsible
   for providing `dayLabel` and `periodLabel` strings alongside
   the mathematical (day, period) indices. This means the grid
   renders correctly for 3-day, 8-day, or 15-day exam periods,
   with morning/afternoon or custom time formats, without any
   frontend mapping code.
   ──────────────────────────────────────────────────────────── */

function generateMockTimeslots() {
  const dayLabels = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"];
  const periodDefs = [
    { label: "09:00 – 10:30", period: 0 },
    { label: "11:00 – 12:30", period: 1 },
    { label: "14:00 – 15:30", period: 2 },
    { label: "16:00 – 17:30", period: 3 },
  ];
  const slots = [];
  let id = 0;
  for (let d = 0; d < dayLabels.length; d++) {
    for (const pDef of periodDefs) {
      slots.push({
        id: id++,
        day: d,
        period: pDef.period,
        dayLabel: dayLabels[d],       // ← backend provides this
        periodLabel: pDef.label,      // ← backend provides this
      });
    }
  }
  return slots;
}

const MOCK_TIMESLOTS = generateMockTimeslots();

const MOCK_ROOMS = [
  { id: 0, capacity: 120, label: "A-101" },
  { id: 1, capacity: 80,  label: "A-102" },
  { id: 2, capacity: 200, label: "B-201" },
  { id: 3, capacity: 60,  label: "B-202" },
  { id: 4, capacity: 150, label: "C-301" },
  { id: 5, capacity: 90,  label: "C-302" },
];

const MOCK_INSTRUCTORS = [
  { id: 0, is_phd: true,  name: "Prof. Yılmaz" },
  { id: 1, is_phd: true,  name: "Prof. Kaya" },
  { id: 2, is_phd: false, name: "RA. Demir" },
  { id: 3, is_phd: true,  name: "Prof. Çelik" },
  { id: 4, is_phd: false, name: "RA. Arslan" },
  { id: 5, is_phd: true,  name: "Prof. Şahin" },
  { id: 6, is_phd: false, name: "RA. Aydın" },
  { id: 7, is_phd: true,  name: "Prof. Öztürk" },
];

const EXAM_CATALOG = [
  { id: 0,  code: "CS101",   name: "Intro to CS",       studentCount: 95,  lecturer_id: 0, required_invigilators: 2 },
  { id: 1,  code: "CS201",   name: "Data Structures",   studentCount: 72,  lecturer_id: 1, required_invigilators: 2 },
  { id: 2,  code: "CS301",   name: "Algorithms",        studentCount: 58,  lecturer_id: 3, required_invigilators: 1 },
  { id: 3,  code: "CS401",   name: "Operating Systems", studentCount: 45,  lecturer_id: 5, required_invigilators: 1 },
  { id: 4,  code: "MATH101", name: "Calculus I",        studentCount: 180, lecturer_id: 7, required_invigilators: 3 },
  { id: 5,  code: "MATH201", name: "Linear Algebra",    studentCount: 110, lecturer_id: 7, required_invigilators: 2 },
  { id: 6,  code: "PHYS101", name: "Physics I",         studentCount: 150, lecturer_id: 5, required_invigilators: 2 },
  { id: 7,  code: "ENG101",  name: "Academic English",  studentCount: 60,  lecturer_id: 3, required_invigilators: 1 },
  { id: 8,  code: "CS350",   name: "Database Systems",  studentCount: 65,  lecturer_id: 1, required_invigilators: 1 },
  { id: 9,  code: "CS450",   name: "Machine Learning",  studentCount: 40,  lecturer_id: 0, required_invigilators: 1 },
  { id: 10, code: "MATH301", name: "Probability",       studentCount: 85,  lecturer_id: 7, required_invigilators: 2 },
  { id: 11, code: "CS499",   name: "Capstone Project",  studentCount: 25,  lecturer_id: 3, required_invigilators: 1 },
];

// solution.py output: exam_time, exam_room, assigned_invigilators
const MOCK_SOLUTION = {
  exam_time: { 0: 0, 1: 1, 2: 4, 3: 5, 4: 2, 5: 8, 6: 3, 7: 9, 8: 12, 9: 13, 10: 6 },
  exam_room: { 0: 0, 1: 1, 2: 3, 3: 4, 4: 2, 5: 0, 6: 2, 7: 5, 8: 1, 9: 3, 10: 4 },
  assigned_invigilators: {
    0: [2, 4], 1: [0, 6], 2: [4], 3: [2], 4: [1, 4, 6],
    5: [2, 3], 6: [0, 6], 7: [4], 8: [6], 9: [2], 10: [1, 4],
  },
};

// Exam 11 (CS499) is intentionally left unassigned for demo
const UNASSIGNED_EXAM_IDS = [11];


/* ────────────────────────────────────────────────────────────
   UTILITY — Derive grid structure dynamically from timeslot data.
   No hardcoded day/period label arrays anywhere.
   ──────────────────────────────────────────────────────────── */

function buildDayMap(timeslots) {
  const dayMap = {};
  timeslots.forEach((ts) => {
    if (!dayMap[ts.day]) dayMap[ts.day] = { label: ts.dayLabel, periods: [] };
    dayMap[ts.day].periods.push(ts);
  });
  const sortedDays = Object.keys(dayMap).map(Number).sort((a, b) => a - b);
  sortedDays.forEach((d) => dayMap[d].periods.sort((a, b) => a.period - b.period));
  return { dayMap, sortedDays };
}


const PASTEL_HUES = [
  "bg-blue-50 border-blue-300 text-blue-900",
  "bg-emerald-50 border-emerald-300 text-emerald-900",
  "bg-amber-50 border-amber-300 text-amber-900",
  "bg-violet-50 border-violet-300 text-violet-900",
  "bg-rose-50 border-rose-300 text-rose-900",
  "bg-cyan-50 border-cyan-300 text-cyan-900",
  "bg-orange-50 border-orange-300 text-orange-900",
  "bg-teal-50 border-teal-300 text-teal-900",
  "bg-indigo-50 border-indigo-300 text-indigo-900",
  "bg-pink-50 border-pink-300 text-pink-900",
  "bg-lime-50 border-lime-300 text-lime-900",
  "bg-fuchsia-50 border-fuchsia-300 text-fuchsia-900",
];

function examColor(examId) {
  return PASTEL_HUES[examId % PASTEL_HUES.length];
}


/* ────────────────────────────────────────────────────────────
   SOLVER SIMULATION (Req #4)
   Async Promise with random 3–8s duration.
   The frontend has NO idea how long this takes — it must treat
   it as a genuine unpredictable async operation.
   ──────────────────────────────────────────────────────────── */

function simulateSolverRequest() {
  return new Promise((resolve) => {
    const duration = 3000 + Math.random() * 5000;
    setTimeout(() => {
      resolve({
        solution: MOCK_SOLUTION,
        unassigned: UNASSIGNED_EXAM_IDS,
        hardViolations: 0,
        softPenalty: 14,
      });
    }, duration);
  });
}


/* ────────────────────────────────────────────────────────────
   COMPONENTS
   ──────────────────────────────────────────────────────────── */

function ImportModal({ isOpen, onClose, onImport }) {
  const [isDragging, setIsDragging] = useState(false);

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-slate-900/60 backdrop-blur-sm" onClick={onClose} />
      <div
        className="relative w-full max-w-lg mx-4 bg-white rounded-2xl shadow-2xl overflow-hidden"
        style={{ animation: "modalIn .25s cubic-bezier(.16,1,.3,1)" }}
      >
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-100">
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-lg bg-blue-600 flex items-center justify-center">
              <Upload size={16} className="text-white" />
            </div>
            <h2 className="text-lg font-semibold text-slate-900 tracking-tight">Import Problem Instance</h2>
          </div>
          <button onClick={onClose} className="p-1.5 rounded-lg hover:bg-slate-100 transition-colors">
            <X size={18} className="text-slate-400" />
          </button>
        </div>

        <div className="p-6">
          <div
            onDragOver={(e) => { e.preventDefault(); setIsDragging(true); }}
            onDragLeave={() => setIsDragging(false)}
            onDrop={(e) => { e.preventDefault(); setIsDragging(false); }}
            className={`
              relative flex flex-col items-center justify-center gap-3 p-10 rounded-xl border-2 border-dashed
              transition-all duration-200 cursor-pointer
              ${isDragging
                ? "border-blue-500 bg-blue-50 scale-[1.01]"
                : "border-slate-200 bg-slate-50/50 hover:border-slate-300 hover:bg-slate-50"
              }
            `}
          >
            <div className={`w-14 h-14 rounded-2xl flex items-center justify-center transition-colors duration-200 ${isDragging ? "bg-blue-100" : "bg-slate-100"}`}>
              <FileSpreadsheet size={26} className={isDragging ? "text-blue-600" : "text-slate-400"} />
            </div>
            <div className="text-center">
              <p className="text-sm font-medium text-slate-700">
                Drop your <span className="text-blue-600">.xlsx</span> or <span className="text-blue-600">.csv</span> file here
              </p>
              <p className="text-xs text-slate-400 mt-1">or click to browse — max 10 MB</p>
            </div>
          </div>

          <div className="mt-5 p-3.5 rounded-lg bg-amber-50 border border-amber-200">
            <div className="flex gap-2">
              <Info size={15} className="text-amber-600 mt-0.5 shrink-0" />
              <div className="text-xs text-amber-800 leading-relaxed">
                <p className="font-medium mb-0.5">Expected sheets:</p>
                <p><strong>Exams</strong> — id, student_ids, lecturer_id, required_invigilators</p>
                <p><strong>TimeSlots</strong> — id, day, period, dayLabel, periodLabel</p>
                <p><strong>Rooms</strong> — id, capacity, label</p>
                <p><strong>Instructors</strong> — id, is_phd, name, preferences</p>
              </div>
            </div>
          </div>

          <div className="flex justify-end gap-2.5 mt-6">
            <button onClick={onClose} className="px-4 py-2 text-sm font-medium text-slate-600 bg-slate-100 rounded-lg hover:bg-slate-200 transition-colors">
              Cancel
            </button>
            <button
              onClick={() => { onImport(); onClose(); }}
              className="px-4 py-2 text-sm font-medium text-white bg-blue-600 rounded-lg hover:bg-blue-700 transition-colors shadow-sm"
            >
              Upload &amp; Parse
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}


/* ── Indeterminate Solver Overlay (Req #4) ─────────────────── */

function SolverOverlay({ elapsedSeconds, stage }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/70 backdrop-blur-sm">
      <div
        className="bg-white rounded-2xl shadow-2xl p-8 w-full max-w-sm mx-4 text-center"
        style={{ animation: "modalIn .3s cubic-bezier(.16,1,.3,1)" }}
      >
        {/* Indeterminate spinning ring — no percentage */}
        <div className="relative w-20 h-20 mx-auto mb-5">
          <svg className="w-20 h-20 indeterminate-spin" viewBox="0 0 80 80">
            <circle cx="40" cy="40" r="34" fill="none" stroke="#e2e8f0" strokeWidth="5" />
            <circle
              cx="40" cy="40" r="34" fill="none"
              stroke="url(#solverGrad)" strokeWidth="5" strokeLinecap="round"
              strokeDasharray={`${Math.PI * 34 * 0.75} ${Math.PI * 34 * 1.25}`}
            />
            <defs>
              <linearGradient id="solverGrad" x1="0%" y1="0%" x2="100%" y2="0%">
                <stop offset="0%" stopColor="#2563eb" />
                <stop offset="100%" stopColor="#818cf8" />
              </linearGradient>
            </defs>
          </svg>
          <div className="absolute inset-0 flex items-center justify-center">
            <Zap size={22} className="text-blue-600" />
          </div>
        </div>

        <h3 className="text-base font-semibold text-slate-900 mb-1">Running CSP Solver</h3>
        <p className="text-sm text-slate-500 mb-1.5">{stage}</p>
        <p className="text-xs text-slate-400 font-mono tabular-nums">{elapsedSeconds}s elapsed</p>

        <div className="flex items-center justify-center gap-1.5 mt-4">
          {[0, 1, 2].map((i) => (
            <span
              key={i}
              className="w-1.5 h-1.5 rounded-full bg-blue-500"
              style={{ animation: `pulse 1.2s ease-in-out ${i * 0.2}s infinite` }}
            />
          ))}
        </div>
      </div>
    </div>
  );
}


function StatCard({ icon: Icon, label, value, accent }) {
  const accents = {
    blue:    "bg-blue-50 text-blue-600",
    emerald: "bg-emerald-50 text-emerald-600",
    amber:   "bg-amber-50 text-amber-600",
    violet:  "bg-violet-50 text-violet-600",
  };
  return (
    <div className="flex items-center gap-3 p-3.5 rounded-xl bg-white border border-slate-200/80 shadow-sm">
      <div className={`w-9 h-9 rounded-lg flex items-center justify-center ${accents[accent]}`}>
        <Icon size={18} />
      </div>
      <div>
        <p className="text-xs text-slate-500 leading-none">{label}</p>
        <p className="text-lg font-bold text-slate-800 leading-tight mt-0.5">{value}</p>
      </div>
    </div>
  );
}


function ExamChip({ exam, instructors, invigilatorIds }) {
  const invNames = (invigilatorIds || [])
    .map((id) => instructors.find((i) => i.id === id)?.name ?? `#${id}`)
    .join(", ");
  return (
    <div className={`p-2 rounded-lg border ${examColor(exam.id)} text-left w-full`}>
      <div className="flex items-center justify-between">
        <span className="text-xs font-bold tracking-wide">{exam.code}</span>
        <span className="text-[10px] opacity-60">{exam.studentCount} std</span>
      </div>
      <p className="text-[10px] mt-0.5 opacity-70 truncate">{exam.name}</p>
      {invNames && <p className="text-[10px] mt-1 opacity-60 truncate" title={invNames}>👁 {invNames}</p>}
    </div>
  );
}


/* ── Timetable Grid — 100% dynamic headers from timeslot data (Req #3) ─ */

function TimetableGrid({ solution, timeslots, rooms, exams, instructors }) {
  const { dayMap, sortedDays } = buildDayMap(timeslots);

  // Build lookup: `${roomId}-${timeslotId}` → examId
  const cellLookup = {};
  Object.entries(solution.exam_time).forEach(([eid, tid]) => {
    const rid = solution.exam_room[eid];
    cellLookup[`${rid}-${tid}`] = Number(eid);
  });

  return (
    <div className="overflow-x-auto rounded-xl border border-slate-200/80 shadow-sm bg-white">
      <table className="w-full border-collapse min-w-[900px]">
        <thead>
          {/* Day header row — label pulled from dayMap[day].label */}
          <tr className="bg-slate-800">
            <th className="sticky left-0 z-20 bg-slate-800 w-28 min-w-28 px-3 py-2.5 text-left text-[11px] font-semibold text-slate-300 uppercase tracking-wider border-r border-slate-700">
              Room
            </th>
            {sortedDays.map((day) => (
              <th
                key={day}
                colSpan={dayMap[day].periods.length}
                className="px-2 py-2.5 text-center text-[11px] font-semibold text-white uppercase tracking-wider border-r border-slate-700 last:border-r-0"
              >
                <div className="flex items-center justify-center gap-1.5">
                  <CalendarDays size={12} className="opacity-60" />
                  {dayMap[day].label}
                </div>
              </th>
            ))}
          </tr>
          {/* Period sub-header — label pulled from each timeslot's periodLabel */}
          <tr className="bg-slate-700">
            <th className="sticky left-0 z-20 bg-slate-700 w-28 min-w-28 px-3 py-2 border-r border-slate-600" />
            {sortedDays.map((day) =>
              dayMap[day].periods.map((ts) => (
                <th
                  key={ts.id}
                  className="px-2 py-2 text-center text-[10px] font-medium text-slate-300 border-r border-slate-600 last:border-r-0 min-w-[120px]"
                >
                  {ts.periodLabel}
                </th>
              ))
            )}
          </tr>
        </thead>
        <tbody>
          {rooms.map((room, ri) => (
            <tr
              key={room.id}
              className={ri % 2 === 0 ? "bg-white" : "bg-slate-50/60"}
            >
              <td
                className="sticky left-0 z-10 px-3 py-2.5 border-r border-slate-200 font-medium text-xs text-slate-700"
                style={{ backgroundColor: ri % 2 === 0 ? "white" : "#f8fafc" }}
              >
                <div className="flex items-center gap-1.5">
                  <DoorOpen size={13} className="text-slate-400" />
                  <span>{room.label}</span>
                  <span className="text-[10px] text-slate-400 font-normal">({room.capacity})</span>
                </div>
              </td>
              {sortedDays.map((day) =>
                dayMap[day].periods.map((ts) => {
                  const key = `${room.id}-${ts.id}`;
                  const examId = cellLookup[key];
                  const exam = examId != null ? exams.find((e) => e.id === examId) : null;
                  const isNewDay = ts.period === dayMap[day].periods[0]?.period;
                  return (
                    <td
                      key={ts.id}
                      className={`px-1.5 py-1.5 border-r border-slate-100 last:border-r-0 align-top ${isNewDay ? "border-l border-l-slate-200" : ""}`}
                    >
                      {exam && (
                        <ExamChip
                          exam={exam}
                          instructors={instructors}
                          invigilatorIds={solution.assigned_invigilators[examId]}
                        />
                      )}
                    </td>
                  );
                })
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}


function UnassignedPool({ examIds, exams }) {
  if (examIds.length === 0) return null;
  const unassigned = examIds.map((id) => exams.find((e) => e.id === id)).filter(Boolean);
  return (
    <div className="rounded-xl border border-amber-200 bg-amber-50/50 p-4">
      <div className="flex items-center gap-2 mb-3">
        <AlertTriangle size={16} className="text-amber-600" />
        <h3 className="text-sm font-semibold text-amber-900">Unassigned Exams ({unassigned.length})</h3>
      </div>
      <p className="text-xs text-amber-700/80 mb-3">
        These exams could not be placed due to tight constraint violations. Consider adding rooms, timeslots, or relaxing soft constraints.
      </p>
      <div className="flex flex-wrap gap-2">
        {unassigned.map((exam) => (
          <div key={exam.id} className="flex items-center gap-2 px-3 py-2 rounded-lg bg-white border border-amber-200 shadow-sm">
            <AlertCircle size={13} className="text-amber-500" />
            <span className="text-xs font-semibold text-slate-800">{exam.code}</span>
            <span className="text-[10px] text-slate-500">— {exam.name}</span>
            <span className="text-[10px] text-slate-400">({exam.studentCount} students)</span>
          </div>
        ))}
      </div>
    </div>
  );
}


function ConstraintBadge({ hardViolations, softPenalty }) {
  const isClean = hardViolations === 0;
  return (
    <div className={`flex items-center gap-4 px-5 py-3 rounded-xl border shadow-sm ${isClean ? "bg-emerald-50 border-emerald-200" : "bg-red-50 border-red-200"}`}>
      <div className="flex items-center gap-2">
        {isClean ? <CheckCircle2 size={18} className="text-emerald-600" /> : <AlertTriangle size={18} className="text-red-600" />}
        <div>
          <p className={`text-sm font-semibold ${isClean ? "text-emerald-800" : "text-red-800"}`}>
            {isClean ? "All Hard Constraints Satisfied" : `${hardViolations} Hard Constraint Violation(s)`}
          </p>
          <p className="text-xs text-slate-500 mt-0.5">
            Soft penalty score: <span className="font-mono font-medium">{softPenalty}</span>
          </p>
        </div>
      </div>
    </div>
  );
}


/* ────────────────────────────────────────────────────────────
   MAIN APP
   ──────────────────────────────────────────────────────────── */

export default function App() {
  const [importOpen, setImportOpen] = useState(false);

  // ── Problem instance state: null = nothing imported yet (Req #2) ──
  const [problemData, setProblemData] = useState(null);

  // ── Solver state (Req #4) ──
  const [solverRunning, setSolverRunning] = useState(false);
  const [solverStage, setSolverStage] = useState("");
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const [solverResult, setSolverResult] = useState(null);
  const elapsedRef = useRef(null);
  const stageRef = useRef(null);

  const dataLoaded = problemData !== null;
  const hasSolution = solverResult !== null;

  // ── Simulate file import → populates problemData (Req #2) ──
  const handleImport = useCallback(() => {
    setProblemData({
      exams: EXAM_CATALOG,
      timeslots: MOCK_TIMESLOTS,
      rooms: MOCK_ROOMS,
      instructors: MOCK_INSTRUCTORS,
    });
    setSolverResult(null);
  }, []);

  // ── Indeterminate solver: async/await + elapsed timer + rotating stages (Req #4) ──
  const runSolver = useCallback(async () => {
    if (!dataLoaded) return;

    setSolverRunning(true);
    setSolverResult(null);
    setElapsedSeconds(0);

    // Elapsed-seconds tick
    const tickInterval = setInterval(() => {
      setElapsedSeconds((s) => s + 1);
    }, 1000);
    elapsedRef.current = tickInterval;

    // Rotating stage labels — cycles endlessly until promise resolves
    const stages = [
      "Parsing problem instance…",
      "Building constraint graph…",
      "Applying arc consistency (AC-3)…",
      "Running backtracking search…",
      "Propagating domain reductions…",
      "Evaluating soft constraints…",
      "Assigning invigilators (greedy)…",
      "Validating solution integrity…",
    ];
    let si = 0;
    setSolverStage(stages[0]);
    const stageInterval = setInterval(() => {
      si = (si + 1) % stages.length;
      setSolverStage(stages[si]);
    }, 900);
    stageRef.current = stageInterval;

    // Await the actual (simulated) backend call — unpredictable duration
    try {
      const result = await simulateSolverRequest();
      setSolverResult(result);
    } finally {
      clearInterval(tickInterval);
      clearInterval(stageInterval);
      elapsedRef.current = null;
      stageRef.current = null;
      setSolverRunning(false);
    }
  }, [dataLoaded]);

  // Cleanup intervals on unmount
  useEffect(() => {
    return () => {
      if (elapsedRef.current) clearInterval(elapsedRef.current);
      if (stageRef.current) clearInterval(stageRef.current);
    };
  }, []);

  // ── Derived display values (all from problemData, never hardcoded) ──
  const numDays = dataLoaded
    ? new Set(problemData.timeslots.map((ts) => ts.day)).size
    : 0;
  const periodsPerDay = dataLoaded
    ? new Set(problemData.timeslots.map((ts) => ts.period)).size
    : 0;
  const assignedCount = hasSolution ? Object.keys(solverResult.solution.exam_time).length : 0;
  const totalExams = dataLoaded ? problemData.exams.length : 0;

  return (
    <>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=DM+Sans:ital,opsz,wght@0,9..40,300;0,9..40,400;0,9..40,500;0,9..40,600;0,9..40,700&family=JetBrains+Mono:wght@400;500;600&display=swap');
        *, *::before, *::after { box-sizing: border-box; margin: 0; }
        body { font-family: 'DM Sans', system-ui, sans-serif; background: #f1f5f9; min-height: 100vh; }
        code, .font-mono { font-family: 'JetBrains Mono', monospace; }
        @keyframes modalIn { from { opacity:0; transform: scale(.96) translateY(8px); } to { opacity:1; transform: scale(1) translateY(0); } }
        @keyframes pulse { 0%,100%{ opacity:.3; transform:scale(.8); } 50%{ opacity:1; transform:scale(1.1); } }
        @keyframes fadeUp { from { opacity:0; transform:translateY(12px); } to { opacity:1; transform:translateY(0); } }
        @keyframes indeterminateSpin { 0%{ transform:rotate(0deg); } 100%{ transform:rotate(360deg); } }
        .indeterminate-spin { animation: indeterminateSpin 1.4s linear infinite; }
        .anim-fade-up { animation: fadeUp .45s cubic-bezier(.16,1,.3,1) both; }
        .anim-d1 { animation-delay: .06s; }
        .anim-d2 { animation-delay: .12s; }
        .anim-d3 { animation-delay: .18s; }
        .anim-d4 { animation-delay: .24s; }
        ::-webkit-scrollbar { height: 6px; width: 6px; }
        ::-webkit-scrollbar-track { background: transparent; }
        ::-webkit-scrollbar-thumb { background: #cbd5e1; border-radius: 999px; }
      `}</style>

      <div className="min-h-screen bg-slate-100">
        {/* ── HEADER — full viewport width (Req #1) ── */}
        <header className="bg-white border-b border-slate-200 shadow-sm sticky top-0 z-30">
          <div className="w-full px-4 sm:px-6 lg:px-10">
            <div className="flex items-center justify-between h-16">
              <div className="flex items-center gap-3">
                <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-blue-600 to-indigo-600 flex items-center justify-center shadow-md shadow-blue-500/20">
                  <CalendarDays size={18} className="text-white" />
                </div>
                <div>
                  <h1 className="text-base font-bold text-slate-900 tracking-tight leading-none">
                    Exam Scheduler
                  </h1>
                  <p className="text-[10px] text-slate-400 font-medium tracking-wide uppercase mt-0.5">
                    CSP-Based Timetabling Engine
                  </p>
                </div>
              </div>

              {/* ── ACTION BUTTONS ── */}
              <div className="flex items-center gap-2.5">
                <button
                  onClick={() => setImportOpen(true)}
                  className="flex items-center gap-2 px-3.5 py-2 text-xs font-medium text-slate-700 bg-white border border-slate-200 rounded-lg hover:bg-slate-50 hover:border-slate-300 transition-all shadow-sm"
                >
                  <Upload size={14} />
                  <span className="hidden sm:inline">Import Data</span>
                </button>

                <button
                  onClick={runSolver}
                  disabled={!dataLoaded || solverRunning}
                  className="flex items-center gap-2 px-4 py-2 text-xs font-semibold text-white bg-gradient-to-r from-blue-600 to-indigo-600 rounded-lg hover:from-blue-700 hover:to-indigo-700 transition-all shadow-md shadow-blue-500/25 disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {solverRunning ? <Loader2 size={14} className="animate-spin" /> : <Zap size={14} />}
                  Run Solver
                </button>

                <button
                  disabled={!hasSolution}
                  className="flex items-center gap-2 px-3.5 py-2 text-xs font-medium text-emerald-700 bg-emerald-50 border border-emerald-200 rounded-lg hover:bg-emerald-100 transition-all shadow-sm disabled:opacity-40 disabled:cursor-not-allowed"
                >
                  <Download size={14} />
                  <span className="hidden sm:inline">Export Excel</span>
                </button>
              </div>
            </div>
          </div>
        </header>

        {/* ── MAIN CONTENT — full viewport width (Req #1) ── */}
        <main className="w-full px-4 sm:px-6 lg:px-10 py-6 space-y-5">

          {/* ── STAT CARDS — show "—" when no data loaded (Req #2) ── */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 anim-fade-up">
            <StatCard icon={BookOpen} label="Total Exams"   value={dataLoaded ? totalExams : "—"} accent="blue" />
            <StatCard icon={DoorOpen} label="Rooms"         value={dataLoaded ? problemData.rooms.length : "—"} accent="emerald" />
            <StatCard icon={Clock}    label="Timeslots"     value={dataLoaded ? `${numDays}d × ${periodsPerDay}p` : "—"} accent="amber" />
            <StatCard icon={Users}    label="Instructors"   value={dataLoaded ? problemData.instructors.length : "—"} accent="violet" />
          </div>

          {/* ── EMPTY STATE — no data imported yet (Req #2) ── */}
          {!dataLoaded && (
            <div className="anim-fade-up anim-d1 flex flex-col items-center justify-center py-20 rounded-xl bg-white border border-dashed border-slate-300 shadow-sm">
              <div className="w-16 h-16 rounded-2xl bg-slate-100 flex items-center justify-center mb-4">
                <PackageOpen size={28} className="text-slate-300" />
              </div>
              <h2 className="text-base font-semibold text-slate-600 mb-1">No Data Loaded</h2>
              <p className="text-sm text-slate-400 max-w-md text-center mb-5">
                Start by importing your problem instance file. The dashboard will populate once the data is parsed.
              </p>
              <button
                onClick={() => setImportOpen(true)}
                className="flex items-center gap-2 px-4 py-2.5 text-sm font-medium text-blue-700 bg-blue-50 border border-blue-200 rounded-lg hover:bg-blue-100 transition-colors"
              >
                <Upload size={15} />
                Import Excel / CSV
              </button>
            </div>
          )}

          {/* ── READY STATE — data loaded, awaiting solver ── */}
          {dataLoaded && !hasSolution && !solverRunning && (
            <div className="anim-fade-up anim-d1 flex flex-col items-center justify-center py-16 rounded-xl bg-white border border-slate-200 shadow-sm">
              <div className="w-16 h-16 rounded-2xl bg-slate-100 flex items-center justify-center mb-4">
                <BarChart3 size={28} className="text-slate-300" />
              </div>
              <h2 className="text-base font-semibold text-slate-600 mb-1">Ready to Solve</h2>
              <p className="text-sm text-slate-400 max-w-md text-center">
                Problem instance loaded successfully. Hit <strong className="text-slate-600">Run Solver</strong> to generate an optimized exam timetable.
              </p>
            </div>
          )}

          {/* ── SOLUTION VIEW ── */}
          {hasSolution && (
            <>
              {/* ── VALIDATION ── */}
              <div className="flex flex-col sm:flex-row items-start sm:items-center gap-3 anim-fade-up anim-d1">
                <ConstraintBadge hardViolations={solverResult.hardViolations} softPenalty={solverResult.softPenalty} />
                <div className="flex items-center gap-2 px-4 py-2.5 rounded-xl bg-blue-50 border border-blue-200 shadow-sm">
                  <Shield size={16} className="text-blue-600" />
                  <span className="text-sm font-medium text-blue-800">
                    {assignedCount}/{totalExams} exams placed
                  </span>
                </div>
              </div>

              {/* ── TIMETABLE ── */}
              <div className="anim-fade-up anim-d2">
                <div className="flex items-center gap-2 mb-3">
                  <h2 className="text-sm font-semibold text-slate-800">Schedule Grid</h2>
                  <span className="text-[10px] text-slate-400 font-medium uppercase tracking-wide">
                    {numDays} Days · {periodsPerDay} Periods/Day · {problemData.rooms.length} Rooms
                  </span>
                </div>
                <TimetableGrid
                  solution={solverResult.solution}
                  timeslots={problemData.timeslots}
                  rooms={problemData.rooms}
                  exams={problemData.exams}
                  instructors={problemData.instructors}
                />
              </div>

              {/* ── UNASSIGNED ── */}
              <div className="anim-fade-up anim-d3">
                <UnassignedPool examIds={solverResult.unassigned} exams={problemData.exams} />
              </div>

              {/* ── LEGEND ── */}
              <div className="anim-fade-up anim-d4 rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
                <h3 className="text-xs font-semibold text-slate-600 uppercase tracking-wider mb-3">Exam Legend</h3>
                <div className="flex flex-wrap gap-2">
                  {problemData.exams.map((exam) => {
                    const isUnassigned = solverResult.unassigned.includes(exam.id);
                    return (
                      <div
                        key={exam.id}
                        className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-md border text-[11px] font-medium ${
                          isUnassigned ? "bg-slate-100 border-slate-200 text-slate-400 line-through" : examColor(exam.id)
                        }`}
                      >
                        {exam.code}
                        <span className="opacity-50 font-normal">— {exam.name}</span>
                      </div>
                    );
                  })}
                </div>
              </div>
            </>
          )}
        </main>
      </div>

      {/* ── MODALS / OVERLAYS ── */}
      <ImportModal isOpen={importOpen} onClose={() => setImportOpen(false)} onImport={handleImport} />
      {solverRunning && <SolverOverlay elapsedSeconds={elapsedSeconds} stage={solverStage} />}
    </>
  );
}