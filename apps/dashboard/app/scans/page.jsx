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
            <th>Ref</th>
            <th>Commit</th>
            <th>Status</th>
            <th>Cost</th>
            <th>When</th>
          </tr>
        </thead>
        <tbody>
          {scans.map((s) => (
            <tr key={s.id}>
              <td><a href={`/scans/${s.id}`}>{s.repo}</a></td>
              <td className="muted">{s.ref?.replace("refs/heads/", "")}</td>
              <td className="mono">{s.commit_sha}</td>
              <td><span className={`badge ${s.status}`}>{s.status}</span></td>
              <td>${s.cost_usd.toFixed(4)}</td>
              <td className="muted">{s.created_at?.slice(0, 16).replace("T", " ")}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}
