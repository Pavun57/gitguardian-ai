"use client";

import { useEffect, useState } from "react";
import { api } from "../../lib/api";

export default function SettingsPage() {
  const [installationId, setInstallationId] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [slackUrl, setSlackUrl] = useState("");
  const [keys, setKeys] = useState([]);
  const [flash, setFlash] = useState(null);
  const [error, setError] = useState(null);

  const load = () => api("/api/keys").then(setKeys).catch(() => {});
  useEffect(() => {
    load();
  }, []);

  const saveKey = async () => {
    setFlash(null);
    setError(null);
    try {
      const r = await api("/api/keys", {
        method: "POST",
        body: JSON.stringify({ installation_id: parseInt(installationId), api_key: apiKey }),
      });
      setFlash(`Key stored (${r.fingerprint}). It is encrypted at rest and never displayed again.`);
      setApiKey("");
      load();
    } catch (e) {
      setError(e.message);
    }
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
        <h2>Installation</h2>
        <label>GitHub App installation ID</label>
        <input
          type="text"
          value={installationId}
          onChange={(e) => setInstallationId(e.target.value)}
          placeholder="e.g. 51234567 — from github.com/settings/installations"
        />
      </div>

      <div className="panel">
        <h2>Connect your coding agent (BYOK)</h2>
        <p className="muted" style={{ marginBottom: 10 }}>
          Paste your Anthropic API key. Fixes are generated with <em>your</em> key —
          encrypted at rest (Fernet), never shown again, scrubbed from logs.
        </p>
        <label>Anthropic API key</label>
        <input
          type="password"
          value={apiKey}
          onChange={(e) => setApiKey(e.target.value)}
          placeholder="sk-ant-..."
        />
        <button onClick={saveKey} disabled={!installationId || !apiKey}>
          Store key
        </button>

        {keys.length > 0 && (
          <table style={{ marginTop: 16 }}>
            <thead>
              <tr>
                <th>Installation</th>
                <th>Provider</th>
                <th>Key</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {keys.map((k) => (
                <tr key={k.installation_id}>
                  <td className="mono">{k.installation_id}</td>
                  <td>{k.provider}</td>
                  <td className="mono">{k.fingerprint}</td>
                  <td>
                    <button
                      className="danger"
                      onClick={() =>
                        api(`/api/keys/${k.installation_id}`, { method: "DELETE" }).then(load)
                      }
                    >
                      Remove
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
