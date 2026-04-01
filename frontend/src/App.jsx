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
  Target,
  Timer,
  XCircle,
  WifiOff,
  FlaskConical,
  Database,
  Settings,
  SlidersHorizontal,
  ToggleLeft,
  ToggleRight,
  RotateCcw,
  Gauge,
  Search,
  UserCheck,
  ChevronUp,
  ArrowUpDown,
  Minus,
  Plus,
} from "lucide-react";

import { exportScheduleToExcel } from "./utils/excelExport";


/* ────────────────────────────────────────────────────────────
   CONFIGURATION
   ──────────────────────────────────────────────────────────── */

const API_BASE_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";

const CARTER_DATASETS = [
  { id: "ear-f-83-2", label: "ear-f-83-2", exams: 190, students: "16.9K" },
  { id: "hec-s-92-2", label: "hec-s-92-2", exams: 81,  students: "2.8K"  },
  { id: "pur-s-93-2", label: "pur-s-93-2", exams: 2419, students: "30.0K" },
  { id: "sta-f-83-2", label: "sta-f-83-2", exams: 139, students: "5.7K"  },
  { id: "uta-s-92-2", label: "uta-s-92-2", exams: 622, students: "21.3K" },
  { id: "yor-f-83-2", label: "yor-f-83-2", exams: 181, students: "11.5K" },
];

const WEEKDAY_NAMES = [
  "Monday", "Tuesday", "Wednesday", "Thursday",
  "Friday", "Saturday", "Sunday",
];

const DEFAULT_SOLVER_CONFIG = {
  w1: 1,
  w2: 5,
  w3: 2,
  w4: 3,
  enable_s3: true,
  enable_s4: true,
  time_limit: 120,
};

const CONSTRAINT_DEFS = [
  {
    key: "w1",
    id: "S1",
    label: "Instructor Preference",
    desc: "Penalizes assigning instructors to timeslots they dislike",
    min: 0, max: 10, step: 1,
    color: "blue",
  },
  {
    key: "w2",
    id: "S2",
    label: "Workload Fairness",
    desc: "Minimizes gap between busiest and least-busy instructor",
    min: 0, max: 10, step: 1,
    color: "violet",
  },
  {
    key: "w3",
    id: "S3",
    label: "Consecutive Invigilation",
    desc: "Penalizes back-to-back invigilation in adjacent timeslots",
    min: 0, max: 10, step: 1,
    color: "amber",
    toggleKey: "enable_s3",
    toggleWarn: "Disabling improves performance on large instances (120+ exams)",
  },
  {
    key: "w4",
    id: "S4",
    label: "Student Day Gap",
    desc: "Penalizes students having exams on consecutive days",
    min: 0, max: 10, step: 1,
    color: "emerald",
    toggleKey: "enable_s4",
    toggleWarn: "Disabling improves performance on instances with 10K+ students",
  },
];


/* ────────────────────────────────────────────────────────────
   DATA BRIDGE — normalizes the backend's Solution.to_dict()
   ──────────────────────────────────────────────────────────── */

function normalizeSolution(rawSolution) {
  const exam_time = {};
  const exam_room = {};
  const assigned_invigilators = {};

  for (const [eid, tid] of Object.entries(rawSolution.exam_time)) {
    exam_time[parseInt(eid, 10)] = typeof tid === "string" ? parseInt(tid, 10) : tid;
  }
  for (const [eid, rid] of Object.entries(rawSolution.exam_room)) {
    // rid is now a list of room IDs (multi-room support)
    exam_room[parseInt(eid, 10)] = Array.isArray(rid)
      ? rid.map((r) => (typeof r === "string" ? parseInt(r, 10) : r))
      : [typeof rid === "string" ? parseInt(rid, 10) : rid]; // legacy fallback
  }
  for (const [eid, ids] of Object.entries(rawSolution.assigned_invigilators)) {
    assigned_invigilators[parseInt(eid, 10)] = Array.isArray(ids)
      ? ids.map((id) => (typeof id === "string" ? parseInt(id, 10) : id))
      : [];
  }

  return { exam_time, exam_room, assigned_invigilators };
}


/* ────────────────────────────────────────────────────────────
   UTILITY — Derive grid structure dynamically from timeslot data.

   Day label wrapping: dayIndex % 7 maps to weekday names so
   day 7 → "Monday", day 8 → "Tuesday", etc. For multi-week
   schedules, a "Wk N" suffix disambiguates repeated names.
   ──────────────────────────────────────────────────────────── */

function buildDayMap(timeslots) {
  const dayMap = {};
  const allDays = [...new Set(timeslots.map((ts) => ts.day))].sort((a, b) => a - b);
  const totalWeeks = allDays.length > 0 ? Math.floor(allDays[allDays.length - 1] / 7) + 1 : 1;
  const needsWeekSuffix = totalWeeks > 1;

  timeslots.forEach((ts) => {
    if (!dayMap[ts.day]) {
      const weekdayName = WEEKDAY_NAMES[ts.day % 7];
      const weekNum = Math.floor(ts.day / 7) + 1;
      const label = needsWeekSuffix
        ? `${weekdayName} W${weekNum}`
        : weekdayName;
      dayMap[ts.day] = { label, periods: [] };
    }
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

/**
 * Build a fresh timeslots array from (numDays, periodsPerDay).
 * Follows the same {id, day, period, dayLabel, periodLabel} schema
 * that the backend serializer produces.
 */
function generateTimeslots(numDays, periodsPerDay) {
  const _WD = ["Monday", "Tuesday", "Wednesday", "Thursday",
               "Friday", "Saturday", "Sunday"];
  const _PS = ["08:00", "09:30", "11:00", "12:30", "14:00",
               "15:30", "17:00", "18:30", "20:00"];
  const _PE = ["09:30", "11:00", "12:30", "14:00", "15:30",
               "17:00", "18:30", "20:00", "21:30"];
  const totalWeeks = Math.floor((numDays - 1) / 7) + 1;
  const needsWeekSuffix = totalWeeks > 1;

  const slots = [];
  let id = 0;
  for (let d = 0; d < numDays; d++) {
    const weekdayName = _WD[d % 7];
    const weekNum = Math.floor(d / 7) + 1;
    const dayLabel = needsWeekSuffix
      ? `${weekdayName} W${weekNum}`
      : weekdayName;

    for (let p = 0; p < periodsPerDay; p++) {
      const periodLabel = p < _PS.length
        ? `${_PS[p]} – ${_PE[p]}`
        : `Period ${p + 1}`;
      slots.push({ id, day: d, period: p, dayLabel, periodLabel });
      id++;
    }
  }
  return slots;
}


/* ────────────────────────────────────────────────────────────
   COMPONENTS
   ──────────────────────────────────────────────────────────── */

function Toast({ toast, onDismiss }) {
  if (!toast) return null;

  const styles = {
    error:   { bg: "bg-red-50 border-red-200",    icon: <XCircle size={18} className="text-red-500" />,    text: "text-red-800",    sub: "text-red-600" },
    warning: { bg: "bg-amber-50 border-amber-200", icon: <AlertTriangle size={18} className="text-amber-500" />, text: "text-amber-800", sub: "text-amber-600" },
    success: { bg: "bg-emerald-50 border-emerald-200", icon: <CheckCircle2 size={18} className="text-emerald-500" />, text: "text-emerald-800", sub: "text-emerald-600" },
    network: { bg: "bg-slate-100 border-slate-300", icon: <WifiOff size={18} className="text-slate-500" />, text: "text-slate-800", sub: "text-slate-600" },
  };

  const s = styles[toast.type] || styles.error;

  return (
    <div className="fixed top-20 right-4 sm:right-6 lg:right-10 z-40" style={{ animation: "toastIn .35s cubic-bezier(.16,1,.3,1)" }}>
      <div className={`flex items-start gap-3 px-4 py-3.5 rounded-xl border shadow-lg w-[380px] max-w-[calc(100vw-2rem)] ${s.bg}`}>
        <div className="mt-0.5 shrink-0">{s.icon}</div>
        <div className="flex-1 min-w-0">
          <p className={`text-sm font-semibold ${s.text}`}>{toast.title}</p>
          {toast.message && <p className={`text-xs mt-0.5 ${s.sub}`}>{toast.message}</p>}
        </div>
        <button onClick={onDismiss} className="p-1 rounded-md hover:bg-black/5 transition-colors shrink-0">
          <X size={14} className="text-slate-400" />
        </button>
      </div>
    </div>
  );
}


/* ── Tabbed Import Modal ───────────────────────────────────── */

function ImportModal({
  isOpen,
  onClose,
  onLoadBenchmark,
  onLoadOkan,
  onUploadFile,
  isParsing,
  selectedDataset,
  onDatasetChange,
  activeSource,
}) {
  const [activeTab, setActiveTab] = useState("upload");
  const [isDragging, setIsDragging] = useState(false);
  const [selectedFile, setSelectedFile] = useState(null);
  const fileInputRef = useRef(null);

  if (!isOpen) return null;

  const tabs = [
    { id: "upload",    label: "Import Template", icon: FileSpreadsheet },
    { id: "okan",      label: "Okan Benchmark",  icon: Database },
    { id: "benchmark", label: "Carter Benchmarks", icon: FlaskConical },
  ];

  const handleFileDrop = (e) => {
    e.preventDefault();
    setIsDragging(false);
    const file = e.dataTransfer.files[0];
    if (file && file.name.toLowerCase().endsWith(".xlsx")) {
      setSelectedFile(file);
    }
  };

  const handleFileChange = (e) => {
    const file = e.target.files[0];
    if (file) setSelectedFile(file);
  };

  const handleUploadSubmit = () => {
    if (selectedFile) {
      onUploadFile(selectedFile);
    }
  };

  const handleDownloadTemplate = async () => {
    try {
      const response = await fetch(`${API_BASE_URL}/template/download`);

      if (!response.ok) {
        const errorText = await response.text().catch(() => "");
        throw new Error(
          response.status === 404
            ? "Template file not found on the server."
            : `Server returned ${response.status}: ${errorText}`
        );
      }

      const blob = await response.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "exam_template.xlsx";
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(url);
    } catch (err) {
      const isNetworkError =
        err instanceof TypeError && err.message === "Failed to fetch";
      alert(
        isNetworkError
          ? `Could not connect to ${API_BASE_URL}. Make sure the backend is running.`
          : `Download failed: ${err.message}`
      );
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-slate-900/60 backdrop-blur-sm" onClick={onClose} />
      <div
        className="relative w-full max-w-lg mx-4 bg-white rounded-2xl shadow-2xl overflow-hidden"
        style={{ animation: "modalIn .25s cubic-bezier(.16,1,.3,1)" }}
      >
        {/* ── Header ── */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-100">
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-lg bg-blue-600 flex items-center justify-center">
              <Database size={16} className="text-white" />
            </div>
            <h2 className="text-lg font-semibold text-slate-900 tracking-tight">Import Problem Instance</h2>
          </div>
          <button onClick={onClose} className="p-1.5 rounded-lg hover:bg-slate-100 transition-colors">
            <X size={18} className="text-slate-400" />
          </button>
        </div>

        {/* ── Tab Bar ── */}
        <div className="flex border-b border-slate-100">
          {tabs.map((tab) => {
            const Icon = tab.icon;
            const isActive = activeTab === tab.id;
            return (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={`flex-1 flex items-center justify-center gap-2 px-4 py-3 text-xs font-medium transition-all relative
                  ${isActive
                    ? "text-blue-600"
                    : "text-slate-400 hover:text-slate-600"
                  }`}
              >
                <Icon size={14} />
                {tab.label}
                {isActive && (
                  <span className="absolute bottom-0 left-4 right-4 h-[2px] bg-blue-600 rounded-full" />
                )}
              </button>
            );
          })}
        </div>

        {/* ── Tab Content ── */}
        <div className="p-6">

          {/* ── TAB: Import Template (.xlsx Upload) ── */}
          {activeTab === "upload" && (
            <>
              {/* Drag-and-drop zone */}
              <div
                onDragOver={(e) => { e.preventDefault(); setIsDragging(true); }}
                onDragLeave={() => setIsDragging(false)}
                onDrop={handleFileDrop}
                onClick={() => fileInputRef.current?.click()}
                className={`
                  relative flex flex-col items-center justify-center gap-3 p-10 rounded-xl border-2 border-dashed
                  transition-all duration-200 cursor-pointer
                  ${isDragging
                    ? "border-blue-500 bg-blue-50 scale-[1.01]"
                    : selectedFile
                      ? "border-emerald-400 bg-emerald-50/50"
                      : "border-slate-200 bg-slate-50/50 hover:border-slate-300 hover:bg-slate-50"
                  }
                `}
              >
                <input
                  ref={fileInputRef}
                  type="file"
                  accept=".xlsx"
                  className="hidden"
                  onChange={handleFileChange}
                />
                <div className={`w-14 h-14 rounded-2xl flex items-center justify-center ${selectedFile ? "bg-emerald-100" : "bg-slate-100"}`}>
                  <FileSpreadsheet size={26} className={selectedFile ? "text-emerald-600" : "text-slate-400"} />
                </div>
                <div className="text-center">
                  {selectedFile ? (
                    <>
                      <p className="text-sm font-semibold text-emerald-700">{selectedFile.name}</p>
                      <p className="text-xs text-emerald-600/70 mt-1">
                        {(selectedFile.size / 1024).toFixed(1)} KB · Click to change
                      </p>
                    </>
                  ) : (
                    <>
                      <p className="text-sm font-medium text-slate-700">
                        Drop your <span className="text-blue-600">.xlsx</span> template here
                      </p>
                      <p className="text-xs text-slate-400 mt-1">or click to browse — max 10 MB</p>
                    </>
                  )}
                </div>
              </div>

              {/* Download Empty Template */}
              <div className="mt-3 flex items-center justify-between">
                <p className="text-[11px] text-slate-400">Need the template format?</p>
                <button
                  onClick={handleDownloadTemplate}
                  className="flex items-center gap-1.5 px-3 py-1.5 text-[11px] font-medium text-emerald-700 bg-emerald-50 border border-emerald-200 rounded-lg hover:bg-emerald-100 transition-colors"
                >
                  <Download size={12} />
                  Download Empty Template
                </button>
              </div>

              <div className="mt-4 p-3 rounded-lg bg-slate-50 border border-slate-200 mb-5">
                <div className="flex gap-2">
                  <Info size={14} className="text-slate-400 mt-0.5 shrink-0" />
                  <p className="text-[11px] text-slate-500 leading-relaxed">
                    Upload an <strong>.xlsx</strong> file in the standard template format. The backend will parse it via
                    <code className="bg-slate-200/60 px-1 py-0.5 rounded text-[10px] mx-0.5">POST /upload</code>
                    and return a fully hydrated problem instance.
                  </p>
                </div>
              </div>

              <div className="flex justify-end gap-2.5">
                <button onClick={onClose} className="px-4 py-2 text-sm font-medium text-slate-600 bg-slate-100 rounded-lg hover:bg-slate-200 transition-colors">
                  Cancel
                </button>
                <button
                  onClick={handleUploadSubmit}
                  disabled={!selectedFile || isParsing}
                  className="flex items-center gap-2 px-4 py-2 text-sm font-medium text-white bg-blue-600 rounded-lg hover:bg-blue-700 transition-colors shadow-sm disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {isParsing ? <Loader2 size={14} className="animate-spin" /> : <Upload size={14} />}
                  {isParsing ? "Uploading…" : "Upload & Parse"}
                </button>
              </div>
            </>
          )}

          {/* ── TAB: Okan Benchmark ── */}
          {activeTab === "okan" && (
            <>
              {/* KVKK/GDPR Privacy Notice */}
              <div className="mb-5 p-4 rounded-xl bg-blue-50 border border-blue-200 flex gap-3">
                <Shield size={18} className="text-blue-600 mt-0.5 shrink-0" />
                <div>
                  <p className="text-sm font-semibold text-blue-800 mb-0.5">Privacy Notice</p>
                  <p className="text-xs text-blue-700 leading-relaxed">
                    Okan University dataset. Personal data has been fully anonymized to comply with KVKK/GDPR privacy regulations.
                  </p>
                </div>
              </div>

              <div className="flex justify-end gap-2.5">
                <button onClick={onClose} className="px-4 py-2 text-sm font-medium text-slate-600 bg-slate-100 rounded-lg hover:bg-slate-200 transition-colors">
                  Cancel
                </button>
                <button
                  onClick={onLoadOkan}
                  disabled={isParsing}
                  className="flex items-center gap-2 px-4 py-2 text-sm font-medium text-white bg-violet-600 rounded-lg hover:bg-violet-700 transition-colors shadow-sm disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {isParsing ? <Loader2 size={14} className="animate-spin" /> : <Database size={14} />}
                  {isParsing ? "Parsing…" : "Load Okan Benchmark"}
                </button>
              </div>
            </>
          )}

          {/* ── TAB: Carter Benchmarks ── */}
          {activeTab === "benchmark" && (
            <>
              <div className="mb-4">
                <label className="block text-xs font-medium text-slate-600 mb-2">
                  Select a Carter benchmark dataset
                </label>
                <div className="relative">
                  <select
                    value={selectedDataset}
                    onChange={(e) => onDatasetChange(e.target.value)}
                    className="w-full appearance-none px-3.5 py-2.5 pr-10 text-sm font-medium text-slate-800 bg-white border border-slate-200 rounded-lg hover:border-slate-300 focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-400 transition-all cursor-pointer"
                  >
                    {CARTER_DATASETS.map((ds) => (
                      <option key={ds.id} value={ds.id}>
                        {ds.label}    —    {ds.exams} exams  ·  {ds.students} students
                      </option>
                    ))}
                  </select>
                  <ChevronDown size={16} className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 pointer-events-none" />
                </div>
              </div>

              {/* Dataset info card */}
              {(() => {
                const ds = CARTER_DATASETS.find((d) => d.id === selectedDataset);
                return ds ? (
                  <div className="p-3.5 rounded-lg bg-blue-50/60 border border-blue-200/60 mb-5">
                    <div className="flex items-center gap-2 mb-1.5">
                      <FlaskConical size={14} className="text-blue-600" />
                      <span className="text-sm font-semibold text-blue-800">{ds.label}</span>
                    </div>
                    <div className="flex gap-4 text-xs text-blue-700/80">
                      <span>{ds.exams} exams</span>
                      <span>{ds.students} students</span>
                    </div>
                  </div>
                ) : null;
              })()}

              <div className="p-3 rounded-lg bg-slate-50 border border-slate-200 mb-5">
                <div className="flex gap-2">
                  <Info size={14} className="text-slate-400 mt-0.5 shrink-0" />
                  <p className="text-[11px] text-slate-500 leading-relaxed">
                    Benchmark <strong>.crs</strong> and <strong>.stu</strong> file pairs must be present in the backend's
                    <code className="bg-slate-200/60 px-1 py-0.5 rounded text-[10px] mx-0.5">data/instances/carter/</code>
                    directory. Rooms, timeslots, and instructors are generated synthetically.
                  </p>
                </div>
              </div>

              <div className="flex justify-end gap-2.5">
                <button onClick={onClose} className="px-4 py-2 text-sm font-medium text-slate-600 bg-slate-100 rounded-lg hover:bg-slate-200 transition-colors">
                  Cancel
                </button>
                <button
                  onClick={onLoadBenchmark}
                  disabled={isParsing}
                  className="flex items-center gap-2 px-4 py-2 text-sm font-medium text-white bg-blue-600 rounded-lg hover:bg-blue-700 transition-colors shadow-sm disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {isParsing ? <Loader2 size={14} className="animate-spin" /> : <FlaskConical size={14} />}
                  {isParsing ? "Parsing…" : "Load Benchmark"}
                </button>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}


function SolverOverlay({ elapsedSeconds, stage }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/70 backdrop-blur-sm">
      {/* BURADAKİ CLASS'LARA flex, flex-col ve items-center EKLENDİ */}
      <div
        className="flex flex-col items-center justify-center bg-white rounded-2xl shadow-2xl p-8 w-full max-w-sm mx-4 text-center"
        style={{ animation: "modalIn .3s cubic-bezier(.16,1,.3,1)" }}
      >
        <div className="relative w-20 h-20 mb-5">
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
    rose:    "bg-rose-50 text-rose-600",
    cyan:    "bg-cyan-50 text-cyan-600",
    slate:   "bg-slate-100 text-slate-600",
  };
  return (
    <div className="flex items-center gap-3 p-3.5 rounded-xl bg-white border border-slate-200/80 shadow-sm">
      <div className={`w-9 h-9 rounded-lg flex items-center justify-center ${accents[accent] || accents.slate}`}>
        <Icon size={18} />
      </div>
      <div>
        <p className="text-xs text-slate-500 leading-none">{label}</p>
        <p className="text-lg font-bold text-slate-800 leading-tight mt-0.5">{value}</p>
      </div>
    </div>
  );
}


function TimeslotEditorCard({ days, periods, onDaysChange, onPeriodsChange, isModified, disabled }) {
  const clampDays = (v) => Math.max(1, Math.min(99, v));
  const clampPeriods = (v) => Math.max(1, Math.min(9, v));

  return (
    <div className={`flex items-center gap-3 p-3.5 rounded-xl bg-white border shadow-sm transition-colors ${isModified ? "border-amber-300 ring-1 ring-amber-200/50" : "border-slate-200/80"}`}>
      <div className={`w-9 h-9 rounded-lg flex items-center justify-center shrink-0 ${isModified ? "bg-amber-100 text-amber-600" : "bg-amber-50 text-amber-600"}`}>
        <Clock size={18} />
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-1.5 mb-1">
          <p className="text-xs text-slate-500 leading-none">Timeslots</p>
          {isModified && (
            <span className="px-1 py-px text-[8px] font-bold uppercase tracking-wider bg-amber-100 text-amber-600 rounded">
              edited
            </span>
          )}
        </div>
        <div className="flex items-center gap-1.5">
          {/* Days stepper */}
          <div className="flex items-center">
            <button
              onClick={() => onDaysChange(clampDays(days - 1))}
              disabled={disabled || days <= 1}
              className="w-5 h-5 flex items-center justify-center rounded-l-md bg-slate-100 border border-slate-200 text-slate-500 hover:bg-slate-200 hover:text-slate-700 transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
            >
              <Minus size={10} strokeWidth={2.5} />
            </button>
            <input
              type="number"
              value={days}
              min={1}
              max={99}
              disabled={disabled}
              onChange={(e) => {
                const v = parseInt(e.target.value, 10);
                if (!isNaN(v)) onDaysChange(clampDays(v));
              }}
              className="w-8 h-5 text-center text-sm font-bold text-slate-800 border-y border-slate-200 bg-white focus:outline-none focus:ring-1 focus:ring-amber-400 disabled:opacity-50 tabular-nums [appearance:textfield] [&::-webkit-outer-spin-button]:appearance-none [&::-webkit-inner-spin-button]:appearance-none"
            />
            <button
              onClick={() => onDaysChange(clampDays(days + 1))}
              disabled={disabled || days >= 99}
              className="w-5 h-5 flex items-center justify-center rounded-r-md bg-slate-100 border border-slate-200 text-slate-500 hover:bg-slate-200 hover:text-slate-700 transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
            >
              <Plus size={10} strokeWidth={2.5} />
            </button>
          </div>

          <span className="text-xs text-slate-400 font-medium">d</span>
          <span className="text-sm font-bold text-slate-400">×</span>

          {/* Periods stepper */}
          <div className="flex items-center">
            <button
              onClick={() => onPeriodsChange(clampPeriods(periods - 1))}
              disabled={disabled || periods <= 1}
              className="w-5 h-5 flex items-center justify-center rounded-l-md bg-slate-100 border border-slate-200 text-slate-500 hover:bg-slate-200 hover:text-slate-700 transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
            >
              <Minus size={10} strokeWidth={2.5} />
            </button>
            <input
              type="number"
              value={periods}
              min={1}
              max={9}
              disabled={disabled}
              onChange={(e) => {
                const v = parseInt(e.target.value, 10);
                if (!isNaN(v)) onPeriodsChange(clampPeriods(v));
              }}
              className="w-8 h-5 text-center text-sm font-bold text-slate-800 border-y border-slate-200 bg-white focus:outline-none focus:ring-1 focus:ring-amber-400 disabled:opacity-50 tabular-nums [appearance:textfield] [&::-webkit-outer-spin-button]:appearance-none [&::-webkit-inner-spin-button]:appearance-none"
            />
            <button
              onClick={() => onPeriodsChange(clampPeriods(periods + 1))}
              disabled={disabled || periods >= 9}
              className="w-5 h-5 flex items-center justify-center rounded-r-md bg-slate-100 border border-slate-200 text-slate-500 hover:bg-slate-200 hover:text-slate-700 transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
            >
              <Plus size={10} strokeWidth={2.5} />
            </button>
          </div>

          <span className="text-xs text-slate-400 font-medium">p</span>

          {/* Total slot count */}
          <span className="ml-1 px-1.5 py-px text-[10px] font-mono font-medium text-slate-400 bg-slate-50 rounded border border-slate-100">
            ={days * periods}
          </span>
        </div>
      </div>
    </div>
  );
}


function ExamChip({ exam, instructors, invigilatorIds, roomCount }) {
  const invNames = (invigilatorIds || [])
    .map((id) => instructors.find((i) => i.id === id)?.name ?? `#${id}`)
    .join(", ");

  const isMultiRoom = roomCount > 1;

  return (
    <div className={`p-2 rounded-lg border ${examColor(exam.id)} text-left w-full`}>
      <div className="flex items-center justify-between">
        <span className="text-xs font-bold tracking-wide">{exam.code}</span>
        <div className="flex items-center gap-1">
          {isMultiRoom && (
            <span
              className="text-[9px] font-bold px-1 py-px rounded bg-white/60 border border-current opacity-70"
              title={`Split across ${roomCount} rooms`}
            >
              🚪{roomCount}
            </span>
          )}
          <span className="text-[10px] opacity-60">{exam.studentCount} std</span>
        </div>
      </div>
      <p className="text-[10px] mt-0.5 opacity-70 truncate">{exam.name}</p>
      {invNames && (
        <p className="text-[10px] mt-1 opacity-60 truncate" title={invNames}>
          👁 {invNames}
        </p>
      )}
    </div>
  );
}


function TimetableGrid({ solution, timeslots, rooms, exams, instructors }) {
  const { dayMap, sortedDays } = buildDayMap(timeslots);

  const cellLookup = {};
  Object.entries(solution.exam_time).forEach(([eid, tid]) => {
    const roomIds = solution.exam_room[eid] ?? []; // now always an array
    roomIds.forEach((rid) => {
      cellLookup[`${rid}-${tid}`] = Number(eid);
    });
  });

  return (
    <div className="overflow-x-auto rounded-xl border border-slate-200/80 shadow-sm bg-white">
      <table className="w-full border-collapse min-w-[900px]">
        <thead>
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
                          roomCount={(solution.exam_room[examId] ?? []).length}
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


/* ── Solver Configuration Panel ────────────────────────────── */

function SolverConfigPanel({ config, onChange, onReset, disabled }) {
  const [expanded, setExpanded] = useState(true);

  const updateField = (key, value) => {
    onChange({ ...config, [key]: value });
  };

  const isDirty = JSON.stringify(config) !== JSON.stringify(DEFAULT_SOLVER_CONFIG);

  return (
    <div className="rounded-xl border border-slate-200 bg-white shadow-sm overflow-hidden anim-fade-up anim-d1">
      {/* ── Header (always visible) ── */}
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center justify-between px-5 py-3.5 hover:bg-slate-50/50 transition-colors"
      >
        <div className="flex items-center gap-2.5">
          <div className="w-7 h-7 rounded-lg bg-slate-800 flex items-center justify-center">
            <SlidersHorizontal size={14} className="text-white" />
          </div>
          <div className="text-left">
            <h3 className="text-sm font-semibold text-slate-800 leading-none">Solver Configuration</h3>
            <p className="text-[10px] text-slate-400 mt-0.5">Constraint weights, toggles, and time limit</p>
          </div>
          {isDirty && (
            <span className="px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wider bg-blue-100 text-blue-600 rounded-full">
              Modified
            </span>
          )}
        </div>
        <ChevronDown
          size={16}
          className={`text-slate-400 transition-transform duration-200 ${expanded ? "rotate-180" : ""}`}
        />
      </button>

      {/* ── Expanded content ── */}
      {expanded && (
        <div className="border-t border-slate-100 px-5 py-4 space-y-5">

          {/* ── Weight sliders ── */}
          <div className="space-y-4">
            <p className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider">Soft constraint weights</p>

            {CONSTRAINT_DEFS.map((c) => {
              const val = config[c.key];
              const hasToggle = !!c.toggleKey;
              const isEnabled = hasToggle ? config[c.toggleKey] : true;
              const barColors = {
                blue:    "bg-blue-500",
                violet:  "bg-violet-500",
                amber:   "bg-amber-500",
                emerald: "bg-emerald-500",
              };
              const dotColors = {
                blue:    "text-blue-500",
                violet:  "text-violet-500",
                amber:   "text-amber-500",
                emerald: "text-emerald-500",
              };

              return (
                <div key={c.key} className={`transition-opacity duration-200 ${!isEnabled && hasToggle ? "opacity-40" : ""}`}>
                  <div className="flex items-center justify-between mb-1.5">
                    <div className="flex items-center gap-2">
                      <span className={`w-1.5 h-1.5 rounded-full ${barColors[c.color]}`} />
                      <span className="text-xs font-semibold text-slate-700">{c.id}</span>
                      <span className="text-xs text-slate-500">{c.label}</span>
                    </div>
                    <div className="flex items-center gap-2">
                      <span className="text-xs font-mono font-bold text-slate-800 w-5 text-right tabular-nums">{val}</span>
                      {hasToggle && (
                        <button
                          onClick={() => updateField(c.toggleKey, !isEnabled)}
                          disabled={disabled}
                          className="p-0.5 rounded transition-colors hover:bg-slate-100 disabled:opacity-50"
                          title={isEnabled ? "Disable this constraint" : "Enable this constraint"}
                        >
                          {isEnabled
                            ? <ToggleRight size={20} className={dotColors[c.color]} />
                            : <ToggleLeft size={20} className="text-slate-300" />
                          }
                        </button>
                      )}
                    </div>
                  </div>

                  {/* Slider track */}
                  <div className="relative flex items-center gap-3">
                    <input
                      type="range"
                      min={c.min}
                      max={c.max}
                      step={c.step}
                      value={val}
                      disabled={disabled || (!isEnabled && hasToggle)}
                      onChange={(e) => updateField(c.key, parseInt(e.target.value, 10))}
                      className="flex-1 h-1.5 appearance-none bg-slate-200 rounded-full cursor-pointer disabled:cursor-not-allowed
                        [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-3.5 [&::-webkit-slider-thumb]:h-3.5
                        [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-white [&::-webkit-slider-thumb]:border-2
                        [&::-webkit-slider-thumb]:border-slate-300 [&::-webkit-slider-thumb]:shadow-sm [&::-webkit-slider-thumb]:hover:border-slate-400
                        [&::-webkit-slider-thumb]:transition-all"
                    />
                    {/* Scale labels */}
                    <div className="flex items-center gap-1 text-[9px] text-slate-300 font-mono shrink-0 w-12 justify-end">
                      <span>{c.min}</span>
                      <span>—</span>
                      <span>{c.max}</span>
                    </div>
                  </div>

                  <p className="text-[10px] text-slate-400 mt-1">{c.desc}</p>

                  {hasToggle && !isEnabled && (
                    <p className="text-[10px] text-amber-600 mt-1 flex items-center gap-1">
                      <AlertTriangle size={10} />
                      {c.toggleWarn}
                    </p>
                  )}
                </div>
              );
            })}
          </div>

          {/* ── Divider ── */}
          <div className="border-t border-slate-100" />

          {/* ── Time limit ── */}
          <div>
            <p className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider mb-3">Solver limits</p>
            <div className="flex items-center gap-3">
              <div className="flex items-center gap-2 flex-1">
                <Gauge size={14} className="text-slate-400 shrink-0" />
                <label className="text-xs font-medium text-slate-600 shrink-0">Time limit</label>
                <div className="flex items-center gap-1.5 flex-1">
                  <input
                    type="range"
                    min={30}
                    max={1200}
                    step={30}
                    value={config.time_limit}
                    disabled={disabled}
                    onChange={(e) => updateField("time_limit", parseInt(e.target.value, 10))}
                    className="flex-1 h-1.5 appearance-none bg-slate-200 rounded-full cursor-pointer disabled:cursor-not-allowed
                      [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-3.5 [&::-webkit-slider-thumb]:h-3.5
                      [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-white [&::-webkit-slider-thumb]:border-2
                      [&::-webkit-slider-thumb]:border-slate-300 [&::-webkit-slider-thumb]:shadow-sm"
                  />
                </div>
              </div>
              <div className="flex items-center gap-1 px-2.5 py-1.5 rounded-lg bg-slate-100 border border-slate-200">
                <span className="text-sm font-mono font-bold text-slate-800 tabular-nums">{config.time_limit}</span>
                <span className="text-[10px] text-slate-400">sec</span>
              </div>
            </div>
            <p className="text-[10px] text-slate-400 mt-1.5 ml-6">
              Maximum wall-clock time for the CP-SAT solver. Longer limits allow more optimization but increase wait time.
            </p>
          </div>

          {/* ── Footer actions ── */}
          <div className="flex items-center justify-between pt-1">
            <button
              onClick={onReset}
              disabled={!isDirty || disabled}
              className="flex items-center gap-1.5 px-3 py-1.5 text-[11px] font-medium text-slate-500 hover:text-slate-700 hover:bg-slate-100 rounded-lg transition-all disabled:opacity-30 disabled:cursor-not-allowed"
            >
              <RotateCcw size={12} />
              Reset to defaults
            </button>
            <div className="flex items-center gap-3 text-[10px] text-slate-400">
              <span>F = {config.w1}·S1 + {config.w2}·S2{config.enable_s3 ? ` + ${config.w3}·S3` : ""}{config.enable_s4 ? ` + ${config.w4}·S4` : ""}</span>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}


/* ── Instructor Workload Panel ─────────────────────────────── */

function WorkloadPanel({ solution, instructors }) {
  const [search, setSearch] = useState("");
  const [sortBy, setSortBy] = useState("load-desc"); // load-desc, load-asc, name
  const [expanded, setExpanded] = useState(true);

  // Compute load per instructor from assigned_invigilators
  const workloadMap = {};
  for (const inst of instructors) workloadMap[inst.id] = 0;
  if (solution?.assigned_invigilators) {
    for (const invIds of Object.values(solution.assigned_invigilators)) {
      if (Array.isArray(invIds)) {
        for (const id of invIds) {
          workloadMap[id] = (workloadMap[id] ?? 0) + 1;
        }
      }
    }
  }

  const maxLoad = Math.max(1, ...Object.values(workloadMap));
  const totalAssignments = Object.values(workloadMap).reduce((a, b) => a + b, 0);
  const activeCount = Object.values(workloadMap).filter((v) => v > 0).length;

  // Build sortable list
  let rows = instructors.map((inst) => ({
    id: inst.id,
    name: inst.name || `Instructor ${inst.id}`,
    is_phd: inst.is_phd,
    load: workloadMap[inst.id] ?? 0,
  }));

  // Filter
  if (search) {
    const q = search.toLowerCase();
    rows = rows.filter((r) => r.name.toLowerCase().includes(q) || String(r.id).includes(q));
  }

  // Sort
  if (sortBy === "load-desc") rows.sort((a, b) => b.load - a.load);
  else if (sortBy === "load-asc") rows.sort((a, b) => a.load - b.load);
  else rows.sort((a, b) => a.name.localeCompare(b.name));

  const barColor = (load) => {
    const ratio = load / maxLoad;
    if (ratio >= 0.85) return "bg-red-400";
    if (ratio >= 0.6)  return "bg-amber-400";
    return "bg-blue-400";
  };

  return (
    <div className="rounded-xl border border-slate-200 bg-white shadow-sm overflow-hidden">
      {/* Header — always visible */}
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center justify-between px-5 py-3.5 hover:bg-slate-50/50 transition-colors"
      >
        <div className="flex items-center gap-2.5">
          <div className="w-7 h-7 rounded-lg bg-violet-600 flex items-center justify-center">
            <UserCheck size={14} className="text-white" />
          </div>
          <div className="text-left">
            <h3 className="text-sm font-semibold text-slate-800 leading-none">Instructor Workload</h3>
            <p className="text-[10px] text-slate-400 mt-0.5">
              {activeCount}/{instructors.length} assigned · {totalAssignments} total duties
            </p>
          </div>
        </div>
        <ChevronUp
          size={16}
          className={`text-slate-400 transition-transform duration-200 ${expanded ? "" : "rotate-180"}`}
        />
      </button>

      {expanded && (
        <div className="border-t border-slate-100">
          {/* Toolbar: search + sort */}
          <div className="px-4 py-3 flex items-center gap-2.5 border-b border-slate-100 bg-slate-50/40">
            <div className="relative flex-1 max-w-xs">
              <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-400 pointer-events-none" />
              <input
                type="text"
                placeholder="Search instructor…"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="w-full pl-7.5 pr-3 py-1.5 text-xs text-slate-700 bg-white border border-slate-200 rounded-lg placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-violet-500/20 focus:border-violet-300 transition-all"
                style={{ paddingLeft: "1.75rem" }}
              />
            </div>
            <div className="flex items-center gap-1">
              {[
                { id: "load-desc", label: "Highest" },
                { id: "load-asc",  label: "Lowest" },
                { id: "name",      label: "A–Z" },
              ].map((opt) => (
                <button
                  key={opt.id}
                  onClick={() => setSortBy(opt.id)}
                  className={`px-2.5 py-1 text-[10px] font-medium rounded-md transition-all ${
                    sortBy === opt.id
                      ? "bg-violet-100 text-violet-700 border border-violet-200"
                      : "text-slate-400 hover:text-slate-600 hover:bg-slate-100 border border-transparent"
                  }`}
                >
                  {opt.label}
                </button>
              ))}
            </div>
          </div>

          {/* Instructor list — scrollable */}
          <div className="max-h-[360px] overflow-y-auto">
            {rows.length === 0 ? (
              <div className="px-5 py-8 text-center text-xs text-slate-400">
                No instructors match your search.
              </div>
            ) : (
              <div className="divide-y divide-slate-100">
                {rows.map((inst, idx) => (
                  <div key={inst.id} className="px-5 py-2.5 flex items-center gap-3 hover:bg-slate-50/50 transition-colors">
                    {/* Rank badge */}
                    <span className="w-6 text-right text-[10px] font-mono text-slate-300 tabular-nums shrink-0">
                      {idx + 1}
                    </span>

                    {/* Name + title */}
                    <div className="flex-1 min-w-0">
                      <p className="text-xs font-medium text-slate-700 truncate">{inst.name}</p>
                      <p className="text-[10px] text-slate-400">
                        {inst.is_phd ? "Research Asst." : "Faculty"} · ID {inst.id}
                      </p>
                    </div>

                    {/* Load bar + count */}
                    <div className="flex items-center gap-2.5 shrink-0 w-36">
                      <div className="flex-1 h-1.5 bg-slate-100 rounded-full overflow-hidden">
                        <div
                          className={`h-full rounded-full transition-all duration-500 ${barColor(inst.load)}`}
                          style={{ width: `${maxLoad > 0 ? (inst.load / maxLoad) * 100 : 0}%` }}
                        />
                      </div>
                      <span className="text-xs font-bold text-slate-700 tabular-nums w-6 text-right">
                        {inst.load}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Footer stats */}
          <div className="px-5 py-2.5 border-t border-slate-100 bg-slate-50/40 flex items-center justify-between text-[10px] text-slate-400">
            <span>
              Load range: <span className="font-mono font-medium text-slate-600">{Math.min(...Object.values(workloadMap))}</span>
              –<span className="font-mono font-medium text-slate-600">{maxLoad}</span>
              {" "}(gap: <span className="font-mono font-medium text-slate-600">{maxLoad - Math.min(...Object.values(workloadMap))}</span>)
            </span>
            <span>
              Avg: <span className="font-mono font-medium text-slate-600">{instructors.length > 0 ? (totalAssignments / instructors.length).toFixed(1) : 0}</span> duties/instructor
            </span>
          </div>
        </div>
      )}
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
  const [isParsing, setIsParsing] = useState(false);

  // ── Selected dataset — persists across Import and Solve ──
  const [selectedDataset, setSelectedDataset] = useState("hec-s-92-2");

  // ── Active data source: "carter" | "okan" | "upload" ──
  const [activeSource, setActiveSource] = useState(null);

  // ── Cached uploaded instance payload for generic /solve ──
  const [uploadedInstancePayload, setUploadedInstancePayload] = useState(null);

  // ── Solver configuration — sent as `config` in the API payload ──
  const [solverConfig, setSolverConfig] = useState({ ...DEFAULT_SOLVER_CONFIG });

  // ── Editable timeslot dimensions — override what was parsed ──
  const [editDays, setEditDays] = useState(0);
  const [editPeriods, setEditPeriods] = useState(0);
  const [parsedDays, setParsedDays] = useState(0);
  const [parsedPeriods, setParsedPeriods] = useState(0);

  // ── Problem instance: null = nothing loaded yet ──
  const [problemData, setProblemData] = useState(null);

  // ── Solver state ──
  const [solverRunning, setSolverRunning] = useState(false);
  const [solverStage, setSolverStage] = useState("");
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const [solverResult, setSolverResult] = useState(null);
  const elapsedRef = useRef(null);
  const stageRef = useRef(null);

  // ── Toast state ──
  const [toast, setToast] = useState(null);
  const toastTimerRef = useRef(null);

  const dataLoaded = problemData !== null;
  const hasSolution = solverResult !== null && !solverResult.failed;

  // ── Toast helpers ──
  const showToast = useCallback((type, title, message, duration = 6000) => {
    if (toastTimerRef.current) clearTimeout(toastTimerRef.current);
    setToast({ type, title, message });

    if (type !== "error") {
      toastTimerRef.current = setTimeout(() => setToast(null), duration);
    }
  }, []);

  const dismissToast = useCallback(() => {
    if (toastTimerRef.current) clearTimeout(toastTimerRef.current);
    setToast(null);
  }, []);

  // ── Sync editable timeslot dims when a new dataset loads ──
  useEffect(() => {
    if (problemData?.timeslots) {
      const days = new Set(problemData.timeslots.map((ts) => ts.day)).size;
      const periods = new Set(problemData.timeslots.map((ts) => ts.period)).size;
      setEditDays(days);
      setEditPeriods(periods);
      setParsedDays(days);
      setParsedPeriods(periods);
    }
  }, [problemData]);

  const timeslotsModified = editDays !== parsedDays || editPeriods !== parsedPeriods;

  /* ──────────────────────────────────────────────────────────
     IMPORT: POST /benchmark/carter/parse → hydrates problemData
     ────────────────────────────────────────────────────────── */

  const handleLoadBenchmark = useCallback(async () => {
    setIsParsing(true);
    dismissToast();

    try {
      const response = await fetch(`${API_BASE_URL}/benchmark/carter/parse`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ dataset: selectedDataset }),
      });

      if (!response.ok) {
        const errorText = await response.text().catch(() => "");
        throw new Error(
          response.status === 404
            ? `Dataset "${selectedDataset}" not found. Ensure .crs and .stu files exist in data/instances/carter/.`
            : `Server returned ${response.status}: ${errorText}`
        );
      }

      const data = await response.json();

      if (!data.instance) {
        throw new Error("Backend returned no instance data.");
      }

      setProblemData(data.instance);
      setActiveSource("carter");
      setUploadedInstancePayload(null);
      setSolverResult(null);
      setImportOpen(false);

      const inst = data.instance;
      showToast(
        "success",
        `Loaded ${selectedDataset}`,
        `${inst.exams.length} exams, ${inst.rooms.length} rooms, ${inst.timeslots.length} timeslots, ${inst.instructors.length} instructors.`
      );

    } catch (err) {
      const isNetworkError = err instanceof TypeError && err.message === "Failed to fetch";
      if (isNetworkError) {
        showToast("network", "Server Unreachable", `Could not connect to ${API_BASE_URL}. Make sure the backend is running.`, 10000);
      } else {
        showToast("error", "Import Failed", err.message || "An unexpected error occurred.", 10000);
      }
    } finally {
      setIsParsing(false);
    }
  }, [selectedDataset, dismissToast, showToast]);

  /* ──────────────────────────────────────────────────────────
     OKAN IMPORT: POST /benchmark/okan/parse → hydrates problemData
     ────────────────────────────────────────────────────────── */

  const handleLoadOkan = useCallback(async () => {
    setIsParsing(true);
    dismissToast();

    try {
      const response = await fetch(`${API_BASE_URL}/benchmark/okan/parse`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      });

      if (!response.ok) {
        const errorText = await response.text().catch(() => "");
        throw new Error(
          response.status === 404
            ? `Okan benchmark file not found. Ensure okan_benchmark.xlsx exists in data/instances/.`
            : `Server returned ${response.status}: ${errorText}`
        );
      }

      const data = await response.json();

      if (!data.instance) {
        throw new Error("Backend returned no instance data.");
      }

      setProblemData(data.instance);
      setActiveSource("okan");
      setUploadedInstancePayload(null);
      setSolverResult(null);
      setImportOpen(false);

      const inst = data.instance;
      showToast(
        "success",
        "Loaded Okan Benchmark",
        `${inst.exams.length} exams, ${inst.rooms.length} rooms, ${inst.timeslots.length} timeslots, ${inst.instructors.length} instructors.`
      );

    } catch (err) {
      const isNetworkError = err instanceof TypeError && err.message === "Failed to fetch";
      if (isNetworkError) {
        showToast("network", "Server Unreachable", `Could not connect to ${API_BASE_URL}. Make sure the backend is running.`, 10000);
      } else {
        showToast("error", "Okan Import Failed", err.message || "An unexpected error occurred.", 10000);
      }
    } finally {
      setIsParsing(false);
    }
  }, [dismissToast, showToast]);

  /* ──────────────────────────────────────────────────────────
     UPLOAD: POST /upload (multipart FormData) → hydrates problemData
     ────────────────────────────────────────────────────────── */

  const handleUploadFile = useCallback(async (file) => {
    setIsParsing(true);
    dismissToast();

    try {
      const formData = new FormData();
      formData.append("file", file);

      const response = await fetch(`${API_BASE_URL}/upload`, {
        method: "POST",
        body: formData,
        // Do NOT set Content-Type — browser sets multipart/form-data with boundary automatically
      });

      if (!response.ok) {
        const errorText = await response.text().catch(() => "");
        throw new Error(
          response.status === 400
            ? `Invalid file: ${errorText || "Only .xlsx files are accepted."}`
            : response.status === 422
              ? `Template validation failed: ${errorText}`
              : `Server returned ${response.status}: ${errorText}`
        );
      }

      const data = await response.json();

      if (!data.instance) {
        throw new Error("Backend returned no instance data.");
      }

      // Preserve the raw instance payload for the generic /solve endpoint
      setProblemData(data.instance);
      setUploadedInstancePayload(data.instance);
      setActiveSource("upload");
      setSolverResult(null);
      setImportOpen(false);

      const inst = data.instance;
      showToast(
        "success",
        `Parsed ${file.name}`,
        `${inst.exams.length} exams, ${inst.rooms.length} rooms, ${inst.timeslots.length} timeslots, ${inst.instructors.length} instructors.`
      );

    } catch (err) {
      const isNetworkError = err instanceof TypeError && err.message === "Failed to fetch";
      if (isNetworkError) {
        showToast("network", "Server Unreachable", `Could not connect to ${API_BASE_URL}. Make sure the backend is running.`, 10000);
      } else {
        showToast("error", "Upload Failed", err.message || "An unexpected error occurred.", 10000);
      }
    } finally {
      setIsParsing(false);
    }
  }, [dismissToast, showToast]);

  /* ──────────────────────────────────────────────────────────
     SOLVER — routes to the correct endpoint based on activeSource:
       "upload"  → POST /solve         (generic, sends full instance)
       "okan"    → POST /benchmark/okan/solve
       "carter"  → POST /benchmark/carter/solve
     ────────────────────────────────────────────────────────── */

  const runSolver = useCallback(async () => {
    if (!dataLoaded) return;

    setSolverRunning(true);
    setSolverResult(null);
    setElapsedSeconds(0);
    dismissToast();

    const tickInterval = setInterval(() => {
      setElapsedSeconds((s) => s + 1);
    }, 1000);
    elapsedRef.current = tickInterval;

    const stages = [
      "Sending problem to solver…",
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

    try {
      let response;

      // Helper: build a full instance payload for the generic /solve path.
      // Used when timeslots have been edited OR for the upload source.
      const buildInstancePayload = () => {
        // Generate timeslots from the user-edited dimensions
        const newTimeslots = generateTimeslots(editDays, editPeriods);
        const newTimeslotIds = new Set(newTimeslots.map((ts) => ts.id));

        return {
          exams: problemData.exams.map((e) => ({
            id: e.id,
            student_ids: Array.from({ length: e.studentCount }, (_, i) => i),
            lecturer_id: e.lecturer_id ?? 0,
            required_invigilators: e.required_invigilators ?? 1,
            code: e.code,
            name: e.name,
          })),
          timeslots: newTimeslots,
          rooms: problemData.rooms.map((r) => ({
            id: r.id,
            capacity: r.capacity,
            label: r.label,
          })),
          instructors: problemData.instructors.map((inst) => {
            // Rebuild preferences keyed to new timeslot IDs.
            // Carry over existing preferences where the ID still exists;
            // default new timeslot IDs to true (no penalty).
            const oldPrefs = inst.preferences ?? {};
            const prefs = {};
            for (const ts of newTimeslots) {
              const key = String(ts.id);
              prefs[key] = key in oldPrefs ? oldPrefs[key] : true;
            }
            return {
              id: inst.id,
              is_phd: inst.is_phd,
              preferences: prefs,
              name: inst.name,
            };
          }),
        };
      };

      // When the user has modified timeslot dimensions, ALL sources
      // are routed through the generic /solve path so the override
      // takes effect.  Otherwise, keep the original benchmark paths.
      if (timeslotsModified || (activeSource === "upload" && uploadedInstancePayload)) {
        const instanceForSolver = buildInstancePayload();

        response = await fetch(`${API_BASE_URL}/solve`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            instance: instanceForSolver,
            config: solverConfig,
          }),
        });

      } else if (activeSource === "okan") {
        response = await fetch(`${API_BASE_URL}/benchmark/okan/solve`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ config: solverConfig }),
        });

      } else {
        // Carter (default)
        response = await fetch(`${API_BASE_URL}/benchmark/carter/solve`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            dataset: selectedDataset,
            config: solverConfig,
          }),
        });
      }

      if (!response.ok) {
        const errorText = await response.text().catch(() => "");
        throw new Error(
          response.status === 422
            ? `Validation error: ${errorText || "check input data format."}`
            : `Server returned ${response.status}${errorText ? `: ${errorText}` : ""}`
        );
      }

      const data = await response.json();

      if (data.instance) {
        setProblemData(data.instance);
      }

      if (data.status === "failed" || data.status === "infeasible") {
        setSolverResult({ failed: true });
        showToast(
          "error",
          "Solver Failed",
          data.message || "Could not find a feasible solution.",
          10000
        );
        return;
      }

      const normalizedSolution = normalizeSolution(data.solution);

      const instanceExams = data.instance?.exams || problemData?.exams || [];
      const placedIds = new Set(Object.keys(normalizedSolution.exam_time).map(Number));
      const unassigned = instanceExams
        .map((e) => e.id)
        .filter((id) => !placedIds.has(id));

      const stats = data.stats || {};

      setSolverResult({
        failed: false,
        solution: normalizedSolution,
        unassigned,
        hardViolations: stats.hard_violations ?? 0,
        softPenalty: stats.soft_penalty ?? stats.penalty ?? 0,
        objective: stats.objective ?? null,
        solveTime: stats.solve_time ?? null,
      });

      const violationMsg = (stats.hard_violations ?? 0) === 0
        ? "All hard constraints satisfied."
        : `${stats.hard_violations} hard constraint violation(s) detected.`;
      showToast("success", "Solution Found", violationMsg);

    } catch (err) {
      setSolverResult(null);
      const isNetworkError = err instanceof TypeError && err.message === "Failed to fetch";
      if (isNetworkError) {
        showToast("network", "Server Unreachable", `Could not connect to ${API_BASE_URL}. Make sure the backend is running.`, 10000);
      } else {
        showToast("error", "Solver Error", err.message || "An unexpected error occurred.", 10000);
      }
    } finally {
      clearInterval(tickInterval);
      clearInterval(stageInterval);
      elapsedRef.current = null;
      stageRef.current = null;
      setSolverRunning(false);
    }
  }, [dataLoaded, activeSource, selectedDataset, solverConfig, problemData, uploadedInstancePayload, editDays, editPeriods, timeslotsModified, dismissToast, showToast]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (elapsedRef.current) clearInterval(elapsedRef.current);
      if (stageRef.current) clearInterval(stageRef.current);
      if (toastTimerRef.current) clearTimeout(toastTimerRef.current);
    };
  }, []);

  // ── Derived display values ──
  const numDays = dataLoaded ? editDays : 0;
  const periodsPerDay = dataLoaded ? editPeriods : 0;
  const assignedCount = hasSolution ? Object.keys(solverResult.solution.exam_time).length : 0;
  const totalExams = dataLoaded ? problemData.exams.length : 0;

  // ── Label for the active dataset badge ──
  const activeDatasetLabel =
    activeSource === "okan"
      ? "Okan Benchmark"
      : activeSource === "upload"
        ? "Uploaded File"
        : selectedDataset;

  return (
    <>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=DM+Sans:ital,opsz,wght@0,9..40,300;0,9..40,400;0,9..40,500;0,9..40,600;0,9..40,700&family=JetBrains+Mono:wght@400;500;600&display=swap');
        *, *::before, *::after { box-sizing: border-box; margin: 0; }
        body { font-family: 'DM Sans', system-ui, sans-serif; background: #f1f5f9; min-height: 100vh; }
        code, .font-mono { font-family: 'JetBrains Mono', monospace; }
        @keyframes modalIn { from { opacity:0; transform: scale(.96) translateY(8px); } to { opacity:1; transform: scale(1) translateY(0); } }
        @keyframes toastIn { from { opacity:0; transform: translateX(20px); } to { opacity:1; transform: translateX(0); } }
        @keyframes pulse { 0%,100%{ opacity:.3; transform:scale(.8); } 50%{ opacity:1; transform:scale(1.1); } }
        @keyframes fadeUp { from { opacity:0; transform:translateY(12px); } to { opacity:1; transform:translateY(0); } }
        @keyframes indeterminateSpin { 0%{ transform:rotate(0deg); } 100%{ transform:rotate(360deg); } }
        .indeterminate-spin { animation: indeterminateSpin 1.4s linear infinite; }
        .anim-fade-up { animation: fadeUp .45s cubic-bezier(.16,1,.3,1) both; }
        .anim-d1 { animation-delay: .06s; }
        .anim-d2 { animation-delay: .12s; }
        .anim-d3 { animation-delay: .18s; }
        .anim-d4 { animation-delay: .24s; }
        .anim-d5 { animation-delay: .30s; }
        ::-webkit-scrollbar { height: 6px; width: 6px; }
        ::-webkit-scrollbar-track { background: transparent; }
        ::-webkit-scrollbar-thumb { background: #cbd5e1; border-radius: 999px; }
      `}</style>

      <div className="min-h-screen bg-slate-100">
        {/* ── HEADER ── */}
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

              <div className="flex items-center gap-2.5">
                {/* Show active dataset badge when loaded */}
                {dataLoaded && (
                  <div className="hidden sm:flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg bg-slate-100 border border-slate-200 text-[11px] font-medium text-slate-500">
                    <FlaskConical size={12} />
                    {activeDatasetLabel}
                  </div>
                )}

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
                  onClick={() => exportScheduleToExcel(problemData, solverResult, activeDatasetLabel)}
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

        {/* ── MAIN CONTENT ── */}
        <main className="w-full px-4 sm:px-6 lg:px-10 py-6 space-y-5">

          {/* ── INSTANCE STAT CARDS ── */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 anim-fade-up">
            <StatCard icon={BookOpen} label="Total Exams"   value={dataLoaded ? totalExams : "—"} accent="blue" />
            <StatCard icon={DoorOpen} label="Rooms"         value={dataLoaded ? problemData.rooms.length : "—"} accent="emerald" />
            {dataLoaded ? (
              <TimeslotEditorCard
                days={editDays}
                periods={editPeriods}
                onDaysChange={setEditDays}
                onPeriodsChange={setEditPeriods}
                isModified={timeslotsModified}
                disabled={solverRunning}
              />
            ) : (
              <StatCard icon={Clock} label="Timeslots" value="—" accent="amber" />
            )}
            <StatCard icon={Users}    label="Instructors"   value={dataLoaded ? problemData.instructors.length : "—"} accent="violet" />
          </div>

          {/* ── SOLVER CONFIG PANEL — visible once data loaded ── */}
          {dataLoaded && (
            <SolverConfigPanel
              config={solverConfig}
              onChange={setSolverConfig}
              onReset={() => setSolverConfig({ ...DEFAULT_SOLVER_CONFIG })}
              disabled={solverRunning}
            />
          )}

          {/* ── SOLVER STATS ROW ── */}
          {hasSolution && (
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 anim-fade-up">
              <StatCard
                icon={Target}
                label="Objective"
                value={solverResult.objective != null ? solverResult.objective : "—"}
                accent="cyan"
              />
              <StatCard
                icon={AlertTriangle}
                label="Hard Violations"
                value={solverResult.hardViolations}
                accent={solverResult.hardViolations === 0 ? "emerald" : "rose"}
              />
              <StatCard
                icon={BarChart3}
                label="Soft Penalty"
                value={solverResult.softPenalty}
                accent="amber"
              />
              <StatCard
                icon={Timer}
                label="Solve Time"
                value={solverResult.solveTime != null ? `${solverResult.solveTime.toFixed(2)}s` : `${elapsedSeconds}s`}
                accent="violet"
              />
            </div>
          )}

          {/* ── EMPTY STATE ── */}
          {!dataLoaded && (
            <div className="anim-fade-up anim-d1 flex flex-col items-center justify-center py-20 rounded-xl bg-white border border-dashed border-slate-300 shadow-sm">
              <div className="w-16 h-16 rounded-2xl bg-slate-100 flex items-center justify-center mb-4">
                <PackageOpen size={28} className="text-slate-300" />
              </div>
              <h2 className="text-base font-semibold text-slate-600 mb-1">No Data Loaded</h2>
              <p className="text-sm text-slate-400 max-w-md text-center mb-5">
                Load a Carter benchmark dataset or upload your own instance file to get started.
              </p>
              <button
                onClick={() => setImportOpen(true)}
                className="flex items-center gap-2 px-4 py-2.5 text-sm font-medium text-blue-700 bg-blue-50 border border-blue-200 rounded-lg hover:bg-blue-100 transition-colors"
              >
                <FlaskConical size={15} />
                Load Benchmark
              </button>
            </div>
          )}

          {/* ── READY STATE ── */}
          {dataLoaded && !hasSolution && !solverRunning && (
            <div className="anim-fade-up anim-d1 flex flex-col items-center justify-center py-16 rounded-xl bg-white border border-slate-200 shadow-sm">
              <div className="w-16 h-16 rounded-2xl bg-slate-100 flex items-center justify-center mb-4">
                <BarChart3 size={28} className="text-slate-300" />
              </div>
              <h2 className="text-base font-semibold text-slate-600 mb-1">Ready to Solve</h2>
              <p className="text-sm text-slate-400 max-w-md text-center">
                <strong className="text-slate-600">{activeDatasetLabel}</strong> loaded successfully. Hit <strong className="text-slate-600">Run Solver</strong> to generate an optimized timetable.
              </p>
            </div>
          )}

          {/* ── SOLUTION VIEW ── */}
          {hasSolution && (
            <>
              <div className="flex flex-col sm:flex-row items-start sm:items-center gap-3 anim-fade-up anim-d1">
                <ConstraintBadge hardViolations={solverResult.hardViolations} softPenalty={solverResult.softPenalty} />
                <div className="flex items-center gap-2 px-4 py-2.5 rounded-xl bg-blue-50 border border-blue-200 shadow-sm">
                  <Shield size={16} className="text-blue-600" />
                  <span className="text-sm font-medium text-blue-800">
                    {assignedCount}/{totalExams} exams placed
                  </span>
                </div>
              </div>

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

              <div className="anim-fade-up anim-d3">
                <UnassignedPool examIds={solverResult.unassigned} exams={problemData.exams} />
              </div>

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

              {/* ── INSTRUCTOR WORKLOAD ── */}
              <div className="anim-fade-up anim-d5">
                <WorkloadPanel
                  solution={solverResult.solution}
                  instructors={problemData.instructors}
                />
              </div>
            </>
          )}
        </main>
      </div>

      <ImportModal
        isOpen={importOpen}
        onClose={() => setImportOpen(false)}
        onLoadBenchmark={handleLoadBenchmark}
        onLoadOkan={handleLoadOkan}
        onUploadFile={handleUploadFile}
        isParsing={isParsing}
        selectedDataset={selectedDataset}
        onDatasetChange={setSelectedDataset}
        activeSource={activeSource}
      />
      {solverRunning && <SolverOverlay elapsedSeconds={elapsedSeconds} stage={solverStage} />}
      <Toast toast={toast} onDismiss={dismissToast} />
    </>
  );
}