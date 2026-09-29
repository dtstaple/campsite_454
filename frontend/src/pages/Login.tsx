/**
 * Sign in.
 *
 * The logic is the one that used to live in AuthPanel: login() from auth.ts, the
 * server's own error text shown verbatim. Only the surroundings changed -- a page
 * instead of a panel floating over the map.
 */

import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { AuthError, login } from "../auth";
import { useSession } from "../session";

export default function Login() {
  const { signIn } = useSession();
  const navigate = useNavigate();

  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      signIn(await login(username.trim(), password));
      navigate("/discover");
    } catch (caught) {
      // AuthError messages are written to be shown; anything else is unexpected, so it
      // is surfaced rather than swallowed into a generic "something went wrong".
      setError(caught instanceof AuthError ? caught.message : String(caught));
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="page page-auth">
      <form className="auth-card" onSubmit={submit}>
        <h1 className="auth-title">Sign in</h1>

        <label className="field">
          <span>Username</span>
          <input
            value={username}
            onChange={(event) => setUsername(event.target.value)}
            autoComplete="username"
            required
            autoFocus
          />
        </label>

        <label className="field">
          <span>Password</span>
          <input
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            autoComplete="current-password"
            required
          />
        </label>

        {/* role=alert so a screen reader announces a failure that is otherwise only a
            colour change below the field the user just left. */}
        {error && (
          <div className="form-error" role="alert">
            {error}
          </div>
        )}

        <button type="submit" className="button-primary button-block" disabled={busy}>
          {busy ? "Signing in…" : "Sign in"}
        </button>

        <p className="auth-footer">
          No account? <Link to="/register">Create one</Link>
        </p>
      </form>
    </main>
  );
}
