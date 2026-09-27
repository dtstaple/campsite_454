/**
 * Accounts client. Contract: docs/auth.md
 *
 * Token storage
 * -------------
 * The token lives in localStorage. That is a deliberate trade, not an oversight: it
 * survives a reload, which is what makes "stay signed in" work, and it is readable by
 * any script that gets onto the page. The alternative -- an httpOnly cookie -- is not
 * available to us, because DRF's TokenAuthentication expects an Authorization header
 * and the API is on a different origin from the dev server.
 *
 * Sign-out is client-side only
 * ----------------------------
 * There is no logout endpoint yet, so signing out forgets the token here and the token
 * itself stays valid server-side until TM05-32 adds revocation. Good enough for a
 * shared laptop, not good enough for a stolen one. The limitation is real and belongs
 * to that story, not this one.
 */

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000";

const TOKEN_KEY = "campsite.token";
const USERNAME_KEY = "campsite.username";

export interface Session {
  token: string;
  username: string;
}

/** Thrown for anything the user could act on. `message` is safe to show verbatim. */
export class AuthError extends Error {}

/**
 * Read the stored session.
 *
 * localStorage throws rather than returning null in a private window with site data
 * blocked, so every access is guarded: a browser that refuses to store simply behaves
 * as signed out rather than breaking the page.
 */
export function storedSession(): Session | null {
  try {
    const token = localStorage.getItem(TOKEN_KEY);
    const username = localStorage.getItem(USERNAME_KEY);
    return token && username ? { token, username } : null;
  } catch {
    return null;
  }
}

function remember(session: Session) {
  try {
    localStorage.setItem(TOKEN_KEY, session.token);
    localStorage.setItem(USERNAME_KEY, session.username);
  } catch {
    /* Storage unavailable: the session still works for this page's lifetime. */
  }
}

export function forgetSession() {
  try {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(USERNAME_KEY);
  } catch {
    /* Nothing was stored, so nothing to forget. */
  }
}

/** `Authorization` header for an authenticated request, or nothing when signed out. */
export function authHeaders(session: Session | null): Record<string, string> {
  return session ? { Authorization: `Token ${session.token}` } : {};
}

/**
 * Turn an error response into one sentence a person can act on.
 *
 * DRF reports field errors as `{ field: [messages] }` and this app's own views report
 * `{ error: "..." }`. Both are flattened here so a caller never has to guess the shape,
 * and a response that is neither still produces something better than "undefined".
 */
async function errorFrom(response: Response): Promise<AuthError> {
  let body: unknown;
  try {
    body = await response.json();
  } catch {
    return new AuthError(`Something went wrong (HTTP ${response.status}).`);
  }

  if (body && typeof body === "object") {
    const record = body as Record<string, unknown>;

    if (typeof record.error === "string") return new AuthError(record.error);

    // Field errors: "password: This password is too common."
    const parts: string[] = [];
    for (const [field, value] of Object.entries(record)) {
      const messages = Array.isArray(value) ? value : [value];
      for (const message of messages) {
        if (typeof message !== "string") continue;
        parts.push(field === "non_field_errors" ? message : `${field}: ${message}`);
      }
    }
    if (parts.length) return new AuthError(parts.join(" "));
  }

  return new AuthError(`Something went wrong (HTTP ${response.status}).`);
}

async function post(path: string, payload: unknown): Promise<Response> {
  try {
    return await fetch(`${API_BASE_URL}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  } catch {
    throw new AuthError(`Could not reach the API at ${API_BASE_URL}. Is the backend running?`);
  }
}

/**
 * Create an account, then sign in with it.
 *
 * Registering does not return a token, so this logs in afterwards to leave the caller
 * signed in -- which is what someone who just filled in a signup form expects.
 *
 * Worth knowing (docs/auth.md): registering with an email that already has an account
 * returns 201 without creating one, deliberately, so that registration cannot be used
 * to discover who has an account. The login that follows is then the first sign that
 * anything was wrong, so its failure is reported in those terms rather than as a bare
 * "invalid credentials", which would be baffling one second after a success.
 */
export async function register(
  username: string,
  email: string,
  password: string,
): Promise<Session> {
  const response = await post("/api/auth/register/", { username, email, password });
  if (!response.ok) throw await errorFrom(response);

  try {
    return await login(username, password);
  } catch {
    throw new AuthError(
      "Account created, but signing in failed. That email may already have an account — " +
        "try signing in with the original username.",
    );
  }
}

export async function login(username: string, password: string): Promise<Session> {
  const response = await post("/api/auth/login/", { username, password });
  if (!response.ok) throw await errorFrom(response);

  const body = (await response.json()) as { token?: string };
  if (!body.token) throw new AuthError("The server did not return a token.");

  const session = { token: body.token, username };
  remember(session);
  return session;
}
