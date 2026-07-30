"use client";

import { useEffect, useState } from "react";
import { api } from "../../lib/api";

export default function ScansPage() {
  const [scans, setScans] = useState([]);

  useEffect(() => {
    api("/api/scans?limit=100").then(setScans).catch(() => {});
  }, []);

  return (
    <>
      <h1>Scan history</h1>
      <table>
        <thead>
          <tr>
            <th>Repo</th>
            <th>Branch</th>
            <th>Status</th>
            <th>Cost</th>
            <th>Trace</th>
            <th>When</th>
          </tr>
        </thead>
        <tbody>
          {scans.map((s) => (
            <tr key={s.id}>
              <td><a href={`/scans/${s.id}`}>{s.repo.split("/").pop()}</a></td>
              <td className="muted">{s.branch}</td>
              <td><span className={`badge ${s.status}`}>{s.status}</span></td>
              <td>${s.cost_usd.toFixed(4)}</td>
              <td>
                {s.trace_url ? (
                  <a href={s.trace_url} target="_blank" rel="noreferrer">view →</a>
                ) : (
                  <span className="muted">–</span>
                )}
              </td>
              <td className="muted">{s.created_at?.slice(0, 16).replace("T", " ")}</td>
            </tr>
          ))}
          {scans.length === 0 && (
            <tr>
              <td colSpan="6" className="muted">
                No scans yet — run <code>gitguardian commit -m "..."</code> in a repo.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </>
  );
}
