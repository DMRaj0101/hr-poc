"use client";
import { useEffect, useState } from "react";
import { api } from "../../lib/api";
import { useAuth } from "../../lib/useAuth";
import Sidebar from "../components/Sidebar";

const RISK_COLOR: Record<string, string> = {
  High: "#dc2626", Medium: "#eab308", Low: "#16a34a",
};

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div style={{ border: "1px solid #eee", borderRadius: 8, padding: 16, marginBottom: 16 }}>
      <h3 style={{ marginTop: 0 }}>{title}</h3>
      {children}
    </div>
  );
}

export default function AiDecisionsPage() {
  useAuth();
  const [employees, setEmployees] = useState<any[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [decisions, setDecisions] = useState<any>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    api.listEmployees().then((all) => {
      setEmployees(all);
      if (all.length) setSelectedId(all[0].id);
    });
  }, []);

  useEffect(() => {
    if (!selectedId) return;
    setLoading(true);
    api.employeeDecisions(selectedId).then((data) => {
      setDecisions(data);
      setLoading(false);
    });
  }, [selectedId]);

  return (
    <Sidebar>
      <main style={{ padding: 32, flex: 1, maxWidth: 750 }}>
        <h1>AI Decision Center</h1>
        <p style={{ fontSize: 12, color: "#999", marginTop: -8 }}>
          Every AI reasoning trail for one employee, in one place — no new AI calls happen here.
        </p>

        <select value={selectedId} onChange={(e) => setSelectedId(e.target.value)} style={{ padding: 8, fontSize: 14, margin: "16px 0" }}>
          {employees.map((e) => (
            <option key={e.id} value={e.id}>{e.name} — {e.department}</option>
          ))}
        </select>

        {loading && <p>Loading...</p>}

        {!loading && decisions && (
          <>
            <Section title="Role Classification">
              <p style={{ fontSize: 13 }}>
                <strong>{decisions.role_decision.predicted_role}</strong>
                {decisions.role_decision.source === "hrms_provided" ? (
                  <span style={{ marginLeft: 8, fontSize: 11, color: "#666" }}>(from HRMS — AI not used)</span>
                ) : (
                  <span style={{ marginLeft: 8, fontSize: 11, color: "#6366f1" }}>
                    (AI fallback — confidence {Math.round((decisions.role_decision.confidence || 0) * 100)}%)
                  </span>
                )}
              </p>
              <p style={{ fontSize: 13, color: "#666", fontStyle: "italic" }}>{decisions.role_decision.reasoning}</p>
            </Section>

            {decisions.access_decision && (
              <Section title="Access Recommendation">
                <p style={{ fontSize: 13, color: "#666", fontStyle: "italic" }}>{decisions.access_decision.reasoning}</p>
              </Section>
            )}

            {decisions.project_decision && (
              <Section title="Project Recommendation">
                <p style={{ fontSize: 13 }}>
                  Selected: <strong>{decisions.project_decision.selected?.[0] || "—"}</strong>
                </p>
                <p style={{ fontSize: 13, color: "#666", fontStyle: "italic" }}>{decisions.project_decision.reasoning}</p>
              </Section>
            )}

            {decisions.risk_decision && (
              <Section title="Risk Assessment">
                <p style={{ fontSize: 13 }}>
                  <strong style={{ color: RISK_COLOR[decisions.risk_decision.risk_level] }}>
                    {decisions.risk_decision.risk_level} risk
                  </strong>
                  {decisions.risk_decision.factors.length > 0 && ` — factors: ${decisions.risk_decision.factors.join(", ")}`}
                </p>
                <p style={{ fontSize: 13, color: "#666", fontStyle: "italic" }}>{decisions.risk_decision.reasoning}</p>
              </Section>
            )}

            <Section title="Decision Timeline">
              {decisions.timeline.map((t: any, idx: number) => (
                <div key={idx} style={{ fontSize: 13, marginBottom: 6 }}>
                  <strong>{t.agent}</strong> — {t.action}
                  {t.detail && <div style={{ color: "#666", fontStyle: "italic" }}>{t.detail}</div>}
                </div>
              ))}
            </Section>
          </>
        )}
      </main>
    </Sidebar>
  );
}
