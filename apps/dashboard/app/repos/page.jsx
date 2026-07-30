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
      <h1>Connected repositories</h1>
      <table>
        <thead>
          <tr>
            <th>Repository</th>
            <th>Default branch</th>
          </tr>
        </thead>
        <tbody>
          {repos.map((r) => (
            <tr key={r.id}>
              <td>
                <a href={`https://github.com/${r.full_name}`} target="_blank" rel="noreferrer">
                  {r.full_name}
                </a>
              </td>
              <td className="muted">{r.default_branch}</td>
            </tr>
          ))}
          {repos.length === 0 && (
            <tr>
              <td colSpan="2" className="muted">
                No repos connected — install the GitHub App on a repository.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </>
  );
}
