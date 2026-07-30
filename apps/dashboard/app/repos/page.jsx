"use client";

import { useEffect, useState } from "react";
import { api } from "../../lib/api";

export default function ReposPage() {
  const [repos, setRepos] = useState([]);

  useEffect(() => {
    api("/api/repos").then(setRepos).catch(() => {});
  }, []);

  return (
    <>
      <h1>Local repositories</h1>
      <p className="muted" style={{ marginBottom: 16 }}>
        Repos the pipeline has scanned. Use <code>gitguardian commit</code> in any local repo
        and it shows up here.
      </p>
      <table>
        <thead>
          <tr>
            <th>Path</th>
            <th>Last scan</th>
          </tr>
        </thead>
        <tbody>
          {repos.map((r) => (
            <tr key={r.path}>
              <td className="mono">{r.path}</td>
              <td className="muted">{r.last_scan?.slice(0, 16).replace("T", " ") ?? "never"}</td>
            </tr>
          ))}
          {repos.length === 0 && (
            <tr>
              <td colSpan="2" className="muted">
                No repos yet — run <code>gitguardian commit -m "..."</code> in a repo.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </>
  );
}
