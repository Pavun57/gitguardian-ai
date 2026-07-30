"use client";

import { useEffect, useState } from "react";
import { api } from "../../../lib/api";

export default function ScanDetailPage({ params }) {
  const [scan, setScan] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    params.then((p) =>
      api(`/api/scans/${p.id}`).then(setScan).catch((e) => setError(e.message))
    );
  }, [params]);

  if (error) return <div className="flash error">{error}</div>;
  if (!scan) return <p className="muted">Loading…</p>;

  return (
    <>
      <h1>
        Scan — {scan.repo} <span className="muted mono">@{scan.commit_sha.slice(0, 7)}</span>
      </h1>
      <div className="panel row">
        <span className={`badge ${scan.status}`}>{scan.status}</span>
        <span className="muted">cost ${scan.cost_usd.toFixed(4)}</span>
        <span className="muted">{scan.created_at?.slice(0, 19).replace("T", " ")}</span>
      </div>
      {scan.error && <div className="flash error">{scan.error}</div>}

      <h2>Findings ({scan.findings.length})</h2>
      {scan.findings.map((f) => (
        <div className="panel" key={f.id}>
          <div className="row">
            <span className={`badge ${f.severity}`}>{f.severity}</span>
            <strong>{f.rule_id}</strong>
            <span className="muted mono">
              {f.file_path}:{f.start_line}
            </span>
            <span className="muted">({f.tool})</span>
          </div>
          {f.fix && (
            <div style={{ marginTop: 12 }}>
              <div className="row">
                <span className="muted">Fix:</span>
                <span className={`badge ${f.fix.status}`}>{f.fix.status}</span>
                <span className="muted">
                  {f.fix.attempts} attempt(s) · ${f.fix.cost_usd.toFixed(4)}
                </span>
              </div>
              {f.fix.explanation && <p style={{ marginTop: 8 }}>{f.fix.explanation}</p>}
            </div>
          )}
          {f.pr && (
            <div style={{ marginTop: 10 }}>
              <a href={f.pr.url} target="_blank" rel="noreferrer">
                PR #{f.pr.number} →
              </a>{" "}
              <span className={`badge ${f.pr.state}`}>{f.pr.state}</span>
            </div>
          )}
        </div>
      ))}
      {scan.findings.length === 0 && (
        <p className="muted">No findings — this push was clean.</p>
      )}
    </>
  );
}
