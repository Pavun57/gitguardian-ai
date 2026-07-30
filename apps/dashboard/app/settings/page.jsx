"use client";

import { useEffect, useState } from "react";
import { api } from "../../lib/api";

const AGENTS = {
  claude_code: {
    label: "Claude Code",
    hint: "Uses your Claude subscription via the installed CLI. Log in once with `claude` in your terminal — we detect the rest.",
  },
  codex: {
    label: "Codex CLI",
    hint: "Uses your OpenAI/ChatGPT account via the installed CLI. Log in once with `codex login` — we detect the rest.",
  },
};

export default function SettingsPage() {
  const [installations, setInstallations] = useState([]);
  const [installationId, setInstallationId] = useState("");
  const [detect, setDetect] = useState(null);
  const [keys, setKeys] = useState([]);
  const [slackUrl, setSlackUrl] = useState("");
  const [testing, setTesting] = useState(null);
  const [testResult, setTestResult] = useState({});
  const [flash, setFlash] = useState(null);
  const [error, setError] = useState(null);

  const loadKeys = () => api("/api/keys").then(setKeys).catch(() => {});
  const loadInstallations = () =>
    api("/api/installations").then((rows) => {
      setInstallations(rows);
      if (rows.length && !installationId) setInstallationId(String(rows[0].id));
    }).catch(() => {});
  const loadDetect = () => api("/api/agents/detect").then(setDetect).catch(() => {});
  // Resilience: pull installations straight from the GitHub API — doesn't
  // depend on the installation webhook having been delivered.
  const syncGitHub = () => api("/api/github/sync", { method: "POST" }).then(loadInstallations).catch(() => {});

  useEffect(() => {
    syncGitHub();
    loadKeys();
    loadDetect();
    // After "Connect GitHub" opens a new tab and the user installs the app,
    // coming back to this tab refreshes the installations list automatically.
    const onFocus = () => {
      syncGitHub();
      loadDetect();
    };
    window.addEventListener("focus", onFocus);
    return () => window.removeEventListener("focus", onFocus);
  }, []);

  // While nothing is connected, keep polling so the page updates itself
  // the moment the installation lands (webhook or sync).
  useEffect(() => {
    if (installations.length > 0) return;
    const timer = setInterval(loadInstallations, 5000);
    return () => clearInterval(timer);
  }, [installations.length]);

  const connectGitHub = async () => {
    const { url } = await api("/api/github/connect-url");
    window.open(url, "_blank");
    setTimeout(syncGitHub, 5000);
  };

  const connectAgent = async (provider) => {
    setFlash(null);
    setError(null);
    try {
      const r = await api("/api/agents/connect", {
        method: "POST",
        body: JSON.stringify({
          installation_id: installationId ? parseInt(installationId) : null,
          provider,
        }),
      });
      setFlash(`${AGENTS[provider].label} connected (${r.mode}) — no keys to paste.`);
      loadKeys();
    } catch (e) {
      setError(e.message);
    }
  };

  const testAgent = async (provider) => {
    setTesting(provider);
    setError(null);
    try {
      const r = await api("/api/agents/test-connection", {
        method: "POST",
        body: JSON.stringify({
          installation_id: installationId ? parseInt(installationId) : null,
          provider,
        }),
      });
      setTestResult((prev) => ({ ...prev, [provider]: r }));
    } catch (e) {
      setTestResult((prev) => ({ ...prev, [provider]: { ok: false, error: e.message } }));
    }
    setTesting(null);
  };

  const saveSlack = async () => {
    setFlash(null);
    setError(null);
    try {
      await api("/api/slack", {
        method: "POST",
        body: JSON.stringify({ installation_id: parseInt(installationId), webhook_url: slackUrl }),
      });
      setFlash("Slack webhook stored.");
      setSlackUrl("");
    } catch (e) {
      setError(e.message);
    }
  };

  return (
    <>
      <h1>Settings</h1>
      {flash && <div className="flash">{flash}</div>}
      {error && <div className="flash error">{error}</div>}

      <div className="panel">
        <h2>GitHub</h2>
        {installations.length === 0 ? (
          <>
            <p className="muted" style={{ marginBottom: 12 }}>
              Connect GitHub to start scanning. You'll be sent to GitHub to authorize
              the app and choose repositories — no IDs to copy.
            </p>
            <button onClick={connectGitHub}>Connect GitHub →</button>
          </>
        ) : (
          <>
            <p className="muted" style={{ marginBottom: 10 }}>
              Connected installation (registered automatically via webhook):
            </p>
            <div className="row">
              <select
                value={installationId}
                onChange={(e) => setInstallationId(e.target.value)}
                style={{
                  background: "var(--bg)",
                  color: "var(--text)",
                  border: "1px solid var(--border)",
                  borderRadius: 6,
                  padding: "8px 12px",
                  fontFamily: "inherit",
                }}
              >
                {installations.map((i) => (
                  <option key={i.id} value={i.id}>
                    {i.account} (#{i.id})
                  </option>
                ))}
              </select>
              <button className="secondary" onClick={connectGitHub}>
                + Add another
              </button>
            </div>
          </>
        )}
      </div>

      <div className="panel">
        <h2>Connect your coding agent</h2>
        <p className="muted" style={{ marginBottom: 14 }}>
          Fixes are generated by your installed agent, billed to your own subscription.
          We auto-detect local CLIs and credentials — nothing to paste.
        </p>

        {Object.entries(AGENTS).map(([provider, a]) => {
          const d = detect?.[provider];
          const t = testResult[provider];
          return (
            <div className="panel" key={provider} style={{ background: "var(--bg)" }}>
              <div className="row">
                <strong>{a.label}</strong>
                <span className={`badge ${d?.connectable ? "success" : "failed"}`}>
                  {d ? (d.connectable ? "detected" : "not found") : "…"}
                </span>
              </div>
              <p className="muted" style={{ margin: "8px 0" }}>{a.hint}</p>
              {d && !d.connectable && (
                <p className="muted" style={{ marginBottom: 8 }}>
                  {!d.cli_installed && "CLI not on PATH. "}
                  {d.cli_installed && !d.credentials_found && "Not logged in. "}
                </p>
              )}
              <div className="row">
                <button
                  className="secondary"
                  disabled={!d?.connectable || testing === provider}
                  onClick={() => testAgent(provider)}
                >
                  {testing === provider ? "Testing…" : "Test connection"}
                </button>
                <button
                  disabled={!d?.connectable}
                  onClick={() => connectAgent(provider)}
                >
                  Connect
                </button>
              </div>
              {t && (
                <p style={{ marginTop: 8 }} className={t.ok ? "" : "flash error"}>
                  {t.ok
                    ? `✓ Working — responded in ${t.latency_seconds}s`
                    : `✗ ${t.error}`}
                </p>
              )}
            </div>
          );
        })}

        {keys.length > 0 && (
          <table style={{ marginTop: 8 }}>
            <thead>
              <tr>
                <th>Installation</th>
                <th>Agent</th>
                <th>Credential</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {keys.map((k) => (
                <tr key={k.installation_id ?? "global"}>
                  <td className="mono">{k.installation_id ?? "global"}</td>
                  <td>{AGENTS[k.provider]?.label ?? k.provider}</td>
                  <td className="mono">{k.fingerprint}</td>
                  <td>
                    <button
                      className="danger"
                      onClick={() =>
                        api(`/api/keys/${k.installation_id ?? "global"}`, { method: "DELETE" }).then(loadKeys)
                      }
                    >
                      Disconnect
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div className="panel">
        <h2>Slack notifications</h2>
        <label>Incoming webhook URL</label>
        <input
          type="text"
          value={slackUrl}
          onChange={(e) => setSlackUrl(e.target.value)}
          placeholder="https://hooks.slack.com/services/..."
        />
        <button onClick={saveSlack} disabled={!installationId || !slackUrl}>
          Save webhook
        </button>
      </div>
    </>
  );
}
