"use client";

import { useEffect, useState } from "react";
import { api } from "../../lib/api";

const AGENTS = {
  anthropic: {
    label: "Anthropic API key",
    hint: "Pay-per-token. Get a key at console.anthropic.com.",
    placeholder: "sk-ant-...",
    secret: true,
  },
  claude_code: {
    label: "Claude Code (subscription)",
    hint: "Uses your Claude plan — no API key. Run `claude setup-token` in your terminal and paste the token.",
    placeholder: "sk-ant-oat...",
    secret: true,
  },
  codex: {
    label: "Codex CLI (OpenAI)",
    hint: "Paste an OpenAI API key, or the contents of ~/.codex/auth.json after `codex login`.",
    placeholder: "sk-... or {...auth.json...}",
    secret: true,
  },
};

export default function SettingsPage() {
  const [installationId, setInstallationId] = useState("");
  const [provider, setProvider] = useState("claude_code");
  const [credential, setCredential] = useState("");
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
        body: JSON.stringify({
          installation_id: parseInt(installationId),
          provider,
          credential,
        }),
      });
      setFlash(
        `${AGENTS[r.provider].label} connected (${r.fingerprint}). Encrypted at rest, never displayed again.`
      );
      setCredential("");
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

  const agent = AGENTS[provider];

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
        <h2>Connect your coding agent</h2>
        <p className="muted" style={{ marginBottom: 10 }}>
          Choose how fixes are generated. Installed agents (Claude Code, Codex) bill your
          own subscription — no API key needed. Credentials are encrypted at rest.
        </p>

        <div className="row" style={{ marginBottom: 12, gap: 8 }}>
          {Object.entries(AGENTS).map(([key, a]) => (
            <button
              key={key}
              className={provider === key ? "" : "secondary"}
              onClick={() => setProvider(key)}
            >
              {a.label}
            </button>
          ))}
        </div>

        <p className="muted" style={{ marginBottom: 6 }}>{agent.hint}</p>
        <label>Credential</label>
        <input
          type={agent.secret ? "password" : "text"}
          value={credential}
          onChange={(e) => setCredential(e.target.value)}
          placeholder={agent.placeholder}
        />
        <button onClick={saveKey} disabled={!installationId || !credential}>
          Connect agent
        </button>

        {keys.length > 0 && (
          <table style={{ marginTop: 16 }}>
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
                <tr key={k.installation_id}>
                  <td className="mono">{k.installation_id}</td>
                  <td>{AGENTS[k.provider]?.label ?? k.provider}</td>
                  <td className="mono">{k.fingerprint}</td>
                  <td>
                    <button
                      className="danger"
                      onClick={() =>
                        api(`/api/keys/${k.installation_id}`, { method: "DELETE" }).then(load)
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
