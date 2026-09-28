/**
 * App header: brand, primary nav, and who is signed in.
 *
 * Present on every route, so sign out is reachable from anywhere rather than only from
 * the map -- which was the old behaviour, when the auth panel floated over it.
 */

import { Link, NavLink, useNavigate } from "react-router-dom";
import { useSession } from "./session";

export default function Header() {
  const { session, signOut } = useSession();
  const navigate = useNavigate();

  function handleSignOut() {
    signOut();
    // Back to the front door. Staying put would leave a signed-out user looking at a
    // Saved panel that just emptied itself for no visible reason.
    navigate("/");
  }

  return (
    <header className="site-header">
      <Link to="/" className="brand">
        CampSite
      </Link>

      <nav className="site-nav">
        <NavLink to="/discover" className="nav-link">
          Discover
        </NavLink>
      </nav>

      <div className="site-account">
        {session ? (
          <>
            <span className="account-who">
              Signed in as <b>{session.username}</b>
            </span>
            <button type="button" className="link-button" onClick={handleSignOut}>
              Sign out
            </button>
          </>
        ) : (
          <>
            <Link to="/login" className="link-button">
              Sign in
            </Link>
            <Link to="/register" className="button-primary">
              Create account
            </Link>
          </>
        )}
      </div>
    </header>
  );
}
