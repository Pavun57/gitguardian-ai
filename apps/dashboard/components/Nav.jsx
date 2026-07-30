"use client";

import { useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import { api } from "../lib/api";

export default function Nav() {
  const [user, setUser] = useState(null);
  const pathname = usePathname();

  useEffect(() => {
    if (pathname === "/login") return;
    api("/auth/me").then(setUser).catch(() => {});
  }, [pathname]);

  if (pathname === "/login") return null;

  return (
    <nav>
      <span className="brand">🛡 GitGuardian AI</span>
      <a href="/">Overview</a>
      <a href="/scans">Scans</a>
      <a href="/approvals">Approvals</a>
      <a href="/repos">Repos</a>
      <a href="/settings">Settings</a>
      <a href="http://localhost:3100" target="_blank">Traces ↗</a>
      <span className="spacer" />
      {user && (
        <span className="muted">
          {user.avatar ? <img src={user.avatar} alt="" /> : null} {user.login}
        </span>
      )}
    </nav>
  );
}
