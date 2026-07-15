"use client";
import { useEffect, useState } from "react";
import { api } from "../../lib/api";
import { useAuth } from "../../lib/useAuth";
import Sidebar from "../components/Sidebar";

const STATUS_ICON: Record<string, string> = {
  approved: "✅", rejected: "❌", pending: "⬜",
};

export default function ComplianceDashboardPage() {
  useAuth();
  const [summary, setSummary] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.complianceSummary().then((data) => {
      setSummary(data);
      setLoading(false);
    });
  }, []);

  return (
    <Sidebar>
      <main style={{ padding: 32, flex: 1, maxWidth: 800 }}>
        <h1>Compliance Dashboard</h1>
        <p style={{ fontSize: 12, color: "#999", marginTop: -8 }}>
          All compliance items are owned by HR, across onboarding and offboarding.
        </p>

        {loading && <p>Loading...</p>}

        {!loading && summary && (
          <>
            <div style={{ display: "flex", gap: 16, margin: "16px 0" }}>
              <div style={{ border: "1px solid #ddd", borderRadius: 8, padding: 16 }}>
                <div style={{ fontSize: 13, color: "#666" }}>Overall Completion</div>
                <div style={{ fontSize: 26, fontWeight: 600 }}>{summary.overall_completion_pct}%</div>
              </div>
              <div style={{ border: "1px solid #ddd", borderRadius: 8, padding: 16 }}>
                <div style={{ fontSize: 13, color: "#666" }}>Approved Items</div>
                <div style={{ fontSize: 26, fontWeight: 600 }}>{summary.approved_items} / {summary.total_items}</div>
              </div>
            </div>

            <table style={{ borderCollapse: "collapse", width: "100%", marginTop: 16 }}>
              <thead>
                <tr style={{ textAlign: "left", borderBottom: "2px solid #eee" }}>
                  <th>Employee</th><th>Department</th><th>Workflow</th><th>Items</th><th>Completion</th>
                </tr>
              </thead>
              <tbody>
                {summary.employees.map((e: any) => (
                  <tr key={`${e.employee_id}-${e.workflow_type}`} style={{ borderBottom: "1px solid #f5f5f5" }}>
                    <td style={{ padding: "8px 0" }}>{e.employee_name}</td>
                    <td>{e.department}</td>
                    <td>{e.workflow_type}</td>
                    <td>
                      {e.items.map((i: any) => (
                        <span key={i.task_name} title={i.task_name} style={{ marginRight: 4 }}>
                          {STATUS_ICON[i.status]}
                        </span>
                      ))}
                    </td>
                    <td>{e.completion_pct}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        )}
      </main>
    </Sidebar>
  );
}
