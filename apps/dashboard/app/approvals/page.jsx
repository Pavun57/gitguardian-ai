"use client";

import { useEffect, useState } from "react";
import { api } from "../../lib/api";

export default function ApprovalsPage() {
  const [items, setItems] = useState([]);
  const [flash, setFlash] = useState(null);

  const load = () => api("/api/approvals").then(setItems).catch(() => {});
  useEffect(() => {
    load();
  }, []);

  const act = async (fixId, action) => {
    try {
      const r = await api(`/api/fixes/${fixId}/${action}`, { method: "POST" });
      setFlash(`PR ${r.status}: ${r.pr}`);
      load();
    } catch (e) {
      setFlash(`Error: ${e.message}`);
    }
  };

  return (
    <>
      <h1>Approval queue</h1>
      <p className="muted" style={{ marginBottom: 16 }}>
        Fix PRs waiting for human review. Approving merges the PR; rejecting closes it.
      </p>
      {flash && <div className="flash">{flash}</div>}
      {items.map((i) => (
        <div className="panel" key={i.fix_id}>
          <div className="row">
            <span className={`badge ${i.severity}`}>{i.severity}</span>
            <strong>{i.rule_id}</strong>
            <span className="muted mono">{i.file_path}</span>
            <span className="muted">{i.repo}</span>
          </div>
          {i.explanation && <p style={{ margin: "10px 0" }}>{i.explanation}</p>}
          <div className="row" style={{ marginTop: 10 }}>
            <a href={i.pr_url} target="_blank" rel="noreferrer">
              Review PR #{i.pr_number} on GitHub →
            </a>
            <span className="spacer" style={{ flex: 1 }} />
            <button onClick={() => act(i.fix_id, "approve")}>✓ Approve & merge</button>
            <button className="danger" onClick={() => act(i.fix_id, "reject")}>
              ✗ Reject
            </button>
          </div>
        </div>
      ))}
      {items.length === 0 && (
        <p className="muted">Nothing waiting — all fixes reviewed.</p>
      )}
    </>
  );
}
