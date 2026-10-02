/**
 * The front door.
 *
 * Deliberately bare: the name, what it does, and the way in. It leads with exploration
 * -- the map, the trails, the terrain -- and lands on the question a backcountry trip
 * actually turns on: where to spend the night. It still names the four things a site is
 * judged on, because that is what separates this from a campground booking site.
 */

import { Link } from "react-router-dom";
import { useSession } from "../session";

const FACTORS = ["Water nearby", "Flat ground", "Trail access", "Legal to camp"];

export default function Landing() {
  const { session } = useSession();

  return (
    <main className="page page-landing">
      <div className="landing-inner">
        <p className="eyebrow">Backcountry exploration</p>

        <h1 className="landing-title">Find where to spend the night.</h1>

        <p className="landing-lede">
          Explore the trails and terrain of the Adirondacks and the White Mountains, then
          find a place to stop. CampSite scores backcountry sites on how close the water
          is, how flat the ground is, whether a trail reaches them, and whether you are
          allowed to camp there.
        </p>

        <ul className="factor-list">
          {FACTORS.map((factor) => (
            <li key={factor}>{factor}</li>
          ))}
        </ul>

        <div className="landing-actions">
          <Link to="/discover" className="button-primary button-lg">
            Explore the map
          </Link>
          {!session && (
            <span className="landing-secondary">
              <Link to="/register" className="link-button">
                Create an account
              </Link>{" "}
              to save the sites you like, or{" "}
              <Link to="/login" className="link-button">
                sign in
              </Link>
              .
            </span>
          )}
        </div>
      </div>
    </main>
  );
}
