"use client";
import { useEffect, useState } from "react";
import { api } from "../../lib/api";
import { useAuth } from "../../lib/useAuth";
import Sidebar from "../components/Sidebar";

const TASK_STATUS_COLOR: Record<string, string> = {
  approved: "#16a34a", rejected: "#dc2626", pending: "#eab308",
};

function TaskCard({ employeeId, task, workflow, onChanged }: { employeeId: string; task: any; workflow: "onboarding" | "offboarding"; onChanged: () => void }) {
  const [saving, setSaving] = useState(false);
  const [selection, setSelection] = useState<string[]>(task.selected_options || []);

  const isEditable = task.status === "pending" && (task.task_type === "multi_select" || task.task_type === "single_select");

  const updateSelection = workflow === "onboarding" ? api.updateTaskSelection : api.updateOffboardingTaskSelection;
  const decideTask = workflow === "onboarding" ? api.decideTask : api.decideOffboardingTask;

  async function saveSelection(next: string[]) {
    setSelection(next);
    setSaving(true);
    try {
      await updateSelection(employeeId, task.id, next);
    } finally {
      setSaving(false);
    }
  }

  function toggleOption(option: string) {
    if (task.task_type === "single_select") {
      saveSelection([option]);
    } else {
      const next = selection.includes(option) ? selection.filter((o) => o !== option) : [...selection, option];
      saveSelection(next);
    }
  }

  async function decide(status: "approved" | "rejected") {
    setSaving(true);
    try {
      await decideTask(employeeId, task.id, status);
      onChanged();
    } finally {
      setSaving(false);
    }
  }

  return (
    <div style={{ background: "#fafafa", border: "1px solid #f0f0f0", borderRadius: 6, padding: 10, marginBottom: 8 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <div style={{ fontSize: 13, fontWeight: 500 }}>
          {task.task_name}
          {!task.is_mandatory && <span style={{ fontSize: 11, color: "#999", marginLeft: 6 }}>(optional)</span>}
          {task.category === "compliance" && <span style={{ fontSize: 11, color: "#6366f1", marginLeft: 6 }}>compliance</span>}
        </div>
        <div style={{ fontSize: 12, fontWeight: 600, color: TASK_STATUS_COLOR[task.status] }}>{task.status}</div>
      </div>

      {task.ai_recommendation && (
        <div style={{ fontSize: 13, color: "#666", marginTop: 4, fontStyle: "italic" }}>
          {task.is_ai_generated ? "🤖 " : ""}{task.ai_recommendation}
        </div>
      )}

      {/* single_select: dropdown over the FULL catalog, AI's top pick pre-selected but changeable */}
      {task.task_type === "single_select" && task.options && (
        <div style={{ marginTop: 8 }}>
          <select
            value={selection[0] || ""}
            disabled={!isEditable || saving}
            onChange={(e) => toggleOption(e.target.value)}
            style={{ fontSize: 13, padding: 4, width: "100%" }}
          >
            <option value="" disabled>Select…</option>
            {task.options.map((opt: string) => (
              <option key={opt} value={opt}>{opt}</option>
            ))}
          </select>
        </div>
      )}

      {/* multi_select: editable checklist, AI's suggestion pre-checked but changeable */}
      {task.task_type === "multi_select" && task.options && (
        <div style={{ marginTop: 8, display: "flex", flexWrap: "wrap", gap: 6 }}>
          {task.options.map((opt: string) => (
            <label key={opt} style={{
              fontSize: 12, padding: "3px 8px", borderRadius: 4,
              background: selection.includes(opt) ? "#e0e7ff" : "#fff",
              border: "1px solid #ddd", cursor: isEditable ? "pointer" : "default",
            }}>
              <input
                type="checkbox"
                checked={selection.includes(opt)}
                disabled={!isEditable || saving}
                onChange={() => toggleOption(opt)}
                style={{ marginRight: 4 }}
              />
              {opt}
            </label>
          ))}
        </div>
      )}

      {task.status === "pending" && (
        <div style={{ marginTop: 8, display: "flex", gap: 8 }}>
          <button onClick={() => decide("approved")} disabled={saving} style={{ fontSize: 12, padding: "3px 10px" }}>
            Approve
          </button>
          <button onClick={() => decide("rejected")} disabled={saving} style={{ fontSize: 12, padding: "3px 10px" }}>
            Reject
          </button>
        </div>
      )}
    </div>
  );
}

export default function ApprovalsPage() {
  const { role } = useAuth();
  const [items, setItems] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);

  async function load() {
    if (!role) return;
    setLoading(true);
    const data = await api.approvalsForRole(role);
    setItems(data);
    setLoading(false);
  }

  useEffect(() => {
    load();
  }, [role]);

  return (
    <Sidebar>
      <main style={{ padding: 32, flex: 1, maxWidth: 800 }}>
        <h1>Approval Dashboard</h1>
        <p style={{ color: "#666", fontSize: 13 }}>
          Showing items for your role: <strong>{role}</strong> — AI suggests, you decide (and can change selections before approving).
        </p>

        {loading && <p>Loading...</p>}
        {!loading && items.length === 0 && <p>Nothing pending for {role}.</p>}

        {!loading && items.map((item) => (
          <div key={`${item.employee_id}-${item.workflow_type}`} style={{ border: "1px solid #eee", borderRadius: 8, padding: 16, marginBottom: 16 }}>
            <div style={{ fontWeight: 600 }}>{item.employee_name}</div>
            <div style={{ fontSize: 13, color: "#666" }}>
              {item.department} · {item.role || "Unclassified"}
              {item.experience_level && ` · ${item.experience_level}`} · {item.workflow_type}
            </div>

            {item.tasks.length > 0 && (
              <div style={{ marginTop: 12 }}>
                {item.tasks.map((t: any, idx: number) => (
                  <TaskCard key={idx} employeeId={item.employee_id} task={t} workflow={item.workflow_type} onChanged={load} />
                ))}
              </div>
            )}
          </div>
        ))}
      </main>
    </Sidebar>
  );
}
