/**
 * Sign in / create account, and the signed-in indicator.
 *
 * Collapsed to a single line when signed in, because an account is a means to saving a
 * campsite here rather than the point of the app -- the map should not give up space to
 * it permanently.
 */

import { useState } from "react";
import { AuthError, forgetSession, login, register, type Session } from "./auth";

type Mode = "signin" | "register";

interface Props {
  session: Session | null;
  onChange: (session: Session | null) => void;
}

export default function AuthPanel({ session, onChange }: Props) {
  const [open, setOpen] = useState(false);
  const [mode, setMode] = useState<Mode>("signin");
  const [username, setUsername] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  function reset() {
    setUsername("");
    setEmail("");
    setPassword("");
    setError(null);
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const next =
        mode === "register"
          ? await register(username.trim(), email.trim(), password)
          : await login(username.trim(), password);
      onChange(next);
      setOpen(false);
      reset();
    } catch (caught) {
      // AuthError messages are written to be shown; anything else is unexpected, so it
      // is surfaced rather than swallowed into a generic "something went wrong".
      setError(caught instanceof AuthError ? caught.message : String(caught));
    } finally {
      setBusy(false);
    }
  }

  function signOut() {
    forgetSession();
    onChange(null);
  }

  if (session) {
    return (
      <div className="auth auth-signed-in">
        <span className="auth-who">
          Signed in as <b>{session.username}</b>
        </span>
        <button type="button" className="auth-link" onClick={signOut}>
          Sign out
        </button>
      </div>
    );
  }

  if (!open) {
    return (
      <div className="auth">
        <button
          type="button"
          className="auth-button"
          onClick={() => {
            setOpen(true);
            reset();
          }}
        >
          Sign in
        </button>
      </div>
    );
  }

  return (
    <div className="auth">
      <form className="auth-form" onSubmit={submit}>
        <div className="panel-title">{mode === "register" ? "Create account" : "Sign in"}</div>

        <label className="auth-field">
          <span>Username</span>
          <input
            value={username}
            onChange={(event) => setUsername(event.target.value)}
            autoComplete="username"
            required
            autoFocus
          />
        </label>

        {mode === "register" && (
          <label className="auth-field">
            <span>Email</span>
            <input
              type="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              autoComplete="email"
              required
            />
          </label>
        )}

        <label className="auth-field">
          <span>Password</span>
          <input
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            autoComplete={mode === "register" ? "new-password" : "current-password"}
            required
          />
        </label>

        {/* role=alert so a screen reader announces a failure that is otherwise only a
            colour change well below the field the user just left. */}
        {error && (
          <div className="auth-error" role="alert">
            {error}
          </div>
        )}

        <div className="auth-actions">
          <button type="submit" className="auth-button" disabled={busy}>
            {busy ? "Working…" : mode === "register" ? "Create account" : "Sign in"}
          </button>
          <button
            type="button"
            className="auth-link"
            onClick={() => {
              setMode(mode === "register" ? "signin" : "register");
              setError(null);
            }}
          >
            {mode === "register" ? "I have an account" : "Create one"}
          </button>
          <button
            type="button"
            className="auth-link"
            onClick={() => {
              setOpen(false);
              reset();
            }}
          >
            Cancel
          </button>
        </div>
      </form>
    </div>
  );
}
