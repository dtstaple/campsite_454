/**
 * Who is signed in, for the whole app.
 *
 * The session used to live inside the map component, because the map was the app. Now
 * that the header, the auth pages and the map all need it, it lives above the router
 * instead -- otherwise signing out from the header could not reach the map's saved
 * panel, and the map would be the only place that knew a session existed.
 *
 * Storage itself still belongs to auth.ts. This is only the React-shaped wrapper.
 */

import { createContext, use, useCallback, useMemo, useState, type ReactNode } from "react";
import { forgetSession, storedSession, type Session } from "./auth";

interface SessionValue {
  session: Session | null;
  signIn: (session: Session) => void;
  signOut: () => void;
}

const SessionContext = createContext<SessionValue | null>(null);

export function SessionProvider({ children }: { children: ReactNode }) {
  // Read once during the initial state, not in an effect, so the first paint already
  // knows whether it is signed in and the header does not flash "Sign in" at someone
  // who is already signed in.
  const [session, setSession] = useState<Session | null>(storedSession);

  const signIn = useCallback((next: Session) => setSession(next), []);

  const signOut = useCallback(() => {
    forgetSession();
    setSession(null);
  }, []);

  const value = useMemo(() => ({ session, signIn, signOut }), [session, signIn, signOut]);

  return <SessionContext value={value}>{children}</SessionContext>;
}

export function useSession(): SessionValue {
  const value = use(SessionContext);
  if (!value) throw new Error("useSession must be used inside a SessionProvider");
  return value;
}
