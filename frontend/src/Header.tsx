/**
 * App header: brand, primary nav, and who is signed in.
 *
 * Present on every route, so sign out is reachable from anywhere rather than only from
 * the map -- which was the old behaviour, when the auth panel floated over it.
 */

import { Link, NavLink, useLocation, useNavigate } from "react-router-dom";
import { useSession } from "./session";

export default function Header() {
  const { session, signOut } = useSession();
  const navigate = useNavigate();
  // Over the map the header shrinks to a slim strip so the terrain gets the screen.
  const onMap = useLocation().pathname.startsWith("/discover");

  function handleSignOut() {
    signOut();
    // Back to the front door. Staying put would leave a signed-out user looking at a
    // Profile or a waypoint list that just emptied itself for no visible reason.
    navigate("/");
  }

  return (
    <header className={`site-header${onMap ? " is-map" : ""}`}>
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
            {/* TM05-100: saved campsites, trails, waypoints and plans. */}
            <NavLink to="/profile" className="nav-link account-profile">
              Profile
            </NavLink>
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
