/**
 * Routes and the shell they render into.
 *
 * React Router, because it is the default for a React SPA and nothing here needs more:
 * four routes, no data loading in the router, no server rendering. The alternative worth
 * naming is TanStack Router, whose draw is typed routes -- not enough to justify a less
 * familiar dependency on a team of four.
 *
 * The map lives at /discover rather than /map because "discover" is the product's own
 * word for it: CLAUDE.md describes the two planned views as "a discover view ranking
 * sites in the current map area, and a trip planning view". /map would name the
 * component; /discover names what the user is doing, and leaves room for /plan beside
 * it later.
 *
 * SessionProvider sits above the router so every route sees the same session, which is
 * what lets the header sign out from anywhere.
 */

import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import "./App.css";
import "./phone.css";
import Header from "./Header";
import Landing from "./pages/Landing";
import Login from "./pages/Login";
import Register from "./pages/Register";
import Discover from "./pages/Discover";
import Profile from "./pages/Profile";
import BrowseTrails from "./pages/BrowseTrails";
import { SessionProvider } from "./session";

export default function App() {
  return (
    <SessionProvider>
      <BrowserRouter>
        <div className="shell">
          <Header />
          <div className="shell-body">
            <Routes>
              <Route path="/" element={<Landing />} />
              <Route path="/login" element={<Login />} />
              <Route path="/register" element={<Register />} />
              <Route path="/discover" element={<Discover />} />
              <Route path="/profile" element={<Profile />} />
              <Route path="/trails" element={<BrowseTrails />} />
              {/* Anything else is a typo, not a page. Send it to the front door rather
                  than showing a blank shell. */}
              <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
          </div>
        </div>
      </BrowserRouter>
    </SessionProvider>
  );
}
