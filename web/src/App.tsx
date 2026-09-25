import { Route, Routes } from "react-router-dom";
import { AudiencePage } from "@/pages/AudiencePage";
import { BroadcastPage } from "@/pages/BroadcastPage";
import { AdminPage } from "@/pages/AdminPage";

export default function App() {
  return (
    <>
      <Routes>
        <Route path="/" element={<AudiencePage />} />
        <Route path="/broadcast" element={<BroadcastPage />} />
        <Route path="/admin" element={<AdminPage />} />
        <Route path="/:sid" element={<AudiencePage />} />
        <Route path="/:sid/:lang" element={<AudiencePage />} />
      </Routes>
      <div
        id="toast-slot"
        className="fixed bottom-5 left-1/2 z-50 -translate-x-1/2 rounded-xl border border-edge bg-panel-2 px-4 py-2 text-sm text-slate-100 shadow-2xl opacity-0 transition-opacity"
      />
    </>
  );
}