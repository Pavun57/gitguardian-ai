"use client";

import { useEffect, useState } from "react";
import { api } from "../lib/api";

export default function OverviewPage() {
  const [stats, setStats] = useState(null);
  const [scans, setScans] = useState([]);

  useEffect(() => {
    api("/api/stats").then(setStats).catch(() => {});
    api("/api/scans?limit=10").then(setScans).catch(() => {});
  }, []);

  return (
    <>
      <h1>Overview</h1>
      <div className="cards">
        <div className="card">
          <div className="num">{stats?.scans ?? "–"}</div>
          <div className="label">Scans</div>
        </div>
        <div className="card">
          <div className="num">{stats?.findings ?? "–"}</div>
          <div className="label">Findings</div>
        </div>
        <div className="card">
          <div className="num">{stats?.fixes ?? "–"}</div>
          <div className="label">Fixes generated</div>
        </div>
        <div className="card">
          <div className="num">{stats?.open_prs ?? "–"}</div>
          <div className="label">Open fix PRs</div>
        </div>
        <div className="card">
          <div className="num">${(stats?.cost_usd ?? 0).toFixed(3)}</div>
          <div className="label">LLM spend</div>
        </div>
      </div>

      <h2>Recent scans</h2>
      <table>
        <thead>
          <tr>
            <th>Repo</th>
            <th>Branch</th>
            <th>Status</th>
            <th>Cost</th>
            <th>When</th>
          </tr>
        </thead>
        <tbody>
          {scans.map((s) => (
            <tr key={s.id}>
              <td><a href={`/scans/${s.id}`}>{s.repo}</a></td>
              <td className="muted">{s.branch}</td>
              <td><span className={`badge ${s.status}`}>{s.status}</span></td>
              <td>${s.cost_usd.toFixed(4)}</td>
              <td className="muted">{s.created_at?.slice(0, 16).replace("T", " ")}</td>
            </tr>
          ))}
          {scans.length === 0 && (
            <tr><td colSpan="5" className="muted">No scans yet — push to a connected repo.</td></tr>
          )}
        </tbody>
      </table>
    </>
  );
}
