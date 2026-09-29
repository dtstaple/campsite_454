/**
 * Create an account.
 *
 * The logic is the one that used to live in AuthPanel: register() from auth.ts, which
 * signs in afterwards because registration returns no token. Only the surroundings
 * changed.
 */

import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { AuthError, register } from "../auth";
import { useSession } from "../session";

export default function Register() {
  const { signIn } = useSession();
  const navigate = useNavigate();

  const [username, setUsername] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      signIn(await register(username.trim(), email.trim(), password));
      navigate("/discover");
    } catch (caught) {
      setError(caught instanceof AuthError ? caught.message : String(caught));
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="page page-auth">
      <form className="auth-card" onSubmit={submit}>
        <h1 className="auth-title">Create account</h1>

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
          <span>Email</span>
          <input
            type="email"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            autoComplete="email"
            required
          />
        </label>

        <label className="field">
          <span>Password</span>
          <input
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            autoComplete="new-password"
            required
          />
        </label>

        {error && (
          <div className="form-error" role="alert">
            {error}
          </div>
        )}

        <button type="submit" className="button-primary button-block" disabled={busy}>
          {busy ? "Creating…" : "Create account"}
        </button>

        <p className="auth-footer">
          Already have one? <Link to="/login">Sign in</Link>
        </p>
      </form>
    </main>
  );
}
