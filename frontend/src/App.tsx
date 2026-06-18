import { Link, Navigate, Route, Routes } from "react-router-dom";
import Dashboard from "./dashboard/Dashboard";
import PipelineEditor from "./editor/PipelineEditor";
import CameraManager from "./cameras/CameraManager";
import EventStream from "./events/EventStream";
import ClipsBrowser from "./clips/ClipsBrowser";
import ExamplesGallery from "./examples/ExamplesGallery";

const navItems = [
  { to: "/dashboard", label: "Dashboard" },
  { to: "/editor", label: "Pipelines" },
  { to: "/examples", label: "Examples" },
  { to: "/cameras", label: "Cameras" },
  { to: "/clips", label: "Clips" },
  { to: "/events", label: "Events" },
];

export default function App() {
  return (
    <div className="flex h-screen flex-col">
      <header className="flex items-center gap-6 border-b border-slate-800 bg-slate-900 px-6 py-3">
        <span className="text-lg font-semibold">camera_dash</span>
        <nav className="flex gap-4">
          {navItems.map((n) => (
            <Link key={n.to} to={n.to} className="text-slate-300 hover:text-white">
              {n.label}
            </Link>
          ))}
        </nav>
      </header>
      <main className="flex-1 overflow-hidden">
        <Routes>
          <Route path="/" element={<Navigate to="/dashboard" replace />} />
          <Route path="/dashboard" element={<Dashboard />} />
          <Route path="/editor" element={<PipelineEditor />} />
          <Route path="/editor/:id" element={<PipelineEditor />} />
          <Route path="/cameras" element={<CameraManager />} />
          <Route path="/examples" element={<ExamplesGallery />} />
          <Route path="/clips" element={<ClipsBrowser />} />
          <Route path="/events" element={<EventStream />} />
        </Routes>
      </main>
    </div>
  );
}
