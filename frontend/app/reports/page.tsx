"use client";
import { useEffect, useState } from "react";
import { api, API_BASE } from "../../lib/api";
import { useAuth } from "../../lib/useAuth";
import Sidebar from "../components/Sidebar";

export default function ReportsPage() {
  useAuth();
  const [employees, setEmployees] = useState<any[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [reportType, setReportType] = useState("onboarding");
  const [generating, setGenerating] = useState(false);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    api.listEmployees().then((all) => {
      setEmployees(all);
      if (all.length) setSelectedId(all[0].id);
    });
  }, []);

  useEffect(() => {
    setReady(false);
  }, [selectedId, reportType]);

  async function handleGenerate() {
    setGenerating(true);
    try {
      await api.generateReport(selectedId, reportType);
      setReady(true);
    } finally {
      setGenerating(false);
    }
  }

  const downloadUrl = `${API_BASE}/reports/${selectedId}/download?report_type=${reportType}`;

  return (
    <Sidebar>
      <main style={{ padding: 32, flex: 1, maxWidth: 600 }}>
        <h1>Reports Dashboard</h1>

        <div style={{ display: "flex", gap: 8, margin: "16px 0" }}>
          <select value={selectedId} onChange={(e) => setSelectedId(e.target.value)} style={{ padding: 8, fontSize: 14 }}>
            {employees.map((e) => (
              <option key={e.id} value={e.id}>{e.name} — {e.department}</option>
            ))}
          </select>
          <select value={reportType} onChange={(e) => setReportType(e.target.value)} style={{ padding: 8, fontSize: 14 }}>
            <option value="onboarding">Onboarding Report</option>
            <option value="offboarding">Offboarding Report</option>
          </select>
        </div>

        <button onClick={handleGenerate} disabled={!selectedId || generating}>
          {generating ? "Generating..." : "Generate Report"}
        </button>

        {ready && (
          <div style={{ marginTop: 16 }}>
            <a href={downloadUrl} target="_blank" rel="noreferrer">
              <button>Download PDF</button>
            </a>
          </div>
        )}
      </main>
    </Sidebar>
  );
}
