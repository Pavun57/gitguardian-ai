"use client";

import { useEffect, useRef, useState } from "react";
import { api } from "../../lib/api";

export default function SetupPage() {
  const [cfg, setCfg] = useState(null);
  const [form, setForm] = useState({ app_id: "", app_slug: "", webhook_secret: "", private_key: "" });
  const [flash, setFlash] = useState(null);
  const [error, setError] = useState(null);
  const manifestForm = useRef(null);
  const [manifest, setManifest] = useState("");

  const load = () => api("/api/github/config").then(setCfg).catch(() => {});
  useEffect(() => {
    load();
  }, []);

  const createApp = async () => {
    const m = await api("/api/github/manifest");
    setManifest(JSON.stringify(m));
    // Submit after state flushes
    setTimeout(() => manifestForm.current?.submit(), 50);
  };

  const save = async () => {
    setFlash(null);
    setError(null);
    try {
      await api("/api/github/config", {
        method: "POST",
        body: JSON.stringify({
          app_id: form.app_id || undefined,
          app_slug: form.app_slug || undefined,
          webhook_secret: form.webhook_secret || undefined,
          private_key: form.private_key || undefined,
        }),
      });
      setFlash("Credentials saved (encrypted at rest).");
      setForm({ app_id: "", app_slug: "", webhook_secret: "", private_key: "" });
      load();
    } catch (e) {
      setError(e.message);
    }
  };

  const set3 = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  return (
    <>
      <h1>Setup — GitHub App</h1>
      {flash && <div className="flash">{flash}</div>}
      {error && <div className="flash error">{error}</div>}

      <div className="panel">
        <h2>Step 1 — Create the GitHub App (one click)</h2>
        <p className="muted" style={{ marginBottom: 12 }}>
          This opens GitHub with everything pre-filled: permissions (Contents, PRs,
          Checks), events (push, installation), and webhook URL. Just review and
          click "Create GitHub App".
        </p>
        <form ref={manifestForm} method="post" action="https://github.com/settings/apps/new">
          <input type="hidden" name="manifest" value={manifest} />
          <button type="button" onClick={createApp}>
            Create GitHub App on GitHub →
          </button>
        </form>
      </div>

      <div className="panel">
        <h2>Step 2 — Paste the credentials GitHub gives you</h2>
        <p className="muted" style={{ marginBottom: 12 }}>
          After creating, GitHub shows the App ID and lets you generate a private key
          (downloads a .pem — open it in a text editor and paste the whole thing).
          Status:{" "}
          {cfg &&
            Object.entries(cfg.configured)
              .map(([k, v]) => `${v ? "✅" : "❌"} ${k.replace("github_", "")}`)
              .join("  ")}
        </p>
        <label>App ID</label>
        <input type="text" value={form.app_id} onChange={set3("app_id")} placeholder="e.g. 1234567" />
        <label>App slug (from the app's URL: github.com/apps/&lt;slug&gt;)</label>
        <input type="text" value={form.app_slug} onChange={set3("app_slug")} placeholder="e.g. gitguardian-ai-dev" />
        <label>Webhook secret (you choose this — any random string)</label>
        <input type="text" value={form.webhook_secret} onChange={set3("webhook_secret")} placeholder="openssl rand -hex 20" />
        <label>Private key (.pem contents)</label>
        <textarea
          rows={6}
          value={form.private_key}
          onChange={set3("private_key")}
          placeholder="-----BEGIN RSA PRIVATE KEY-----"
          style={{
            width: "100%",
            background: "var(--bg)",
            border: "1px solid var(--border)",
            borderRadius: 6,
            color: "var(--text)",
            padding: "8px 12px",
            fontFamily: "inherit",
            margin: "6px 0 12px",
          }}
        />
        <button onClick={save}>Save credentials</button>
      </div>

      <div className="panel">
        <h2>Step 3 — Webhook &amp; install</h2>
        <p className="muted">
          Webhook URL (paste into the app settings, or expose via smee in dev):<br />
          <code>{cfg?.webhook_url}</code>
        </p>
        <p className="muted" style={{ marginTop: 8 }}>
          Then go to <a href="/settings">Settings</a> and click <strong>Connect GitHub</strong> to
          install the app on your repositories.
        </p>
      </div>
    </>
  );
}
