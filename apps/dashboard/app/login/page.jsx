import { loginUrl } from "../../lib/api";

export default function LoginPage() {
  return (
    <div className="login-wrap">
      <div className="login-box">
        <h1>🛡 GitGuardian AI</h1>
        <p>Agentic security on every push.</p>
        <a className="btn" href={loginUrl}>
          Sign in with GitHub
        </a>
      </div>
    </div>
  );
}
