/**
 * The front door.
 *
 * Deliberately bare: the name, what it does, and the way in. The one thing it does
 * commit to is naming the four things a site is judged on, because "find a campsite" on
 * its own does not distinguish this from a campground booking site -- and the scoring is
 * the product.
 */

import { Link } from "react-router-dom";
import { useSession } from "../session";

const FACTORS = ["Water nearby", "Flat ground", "Trail access", "Legal to camp"];

export default function Landing() {
  const { session } = useSession();

  return (
    <main className="page page-landing">
      <div className="landing-inner">
        <p className="eyebrow">Backcountry campsites</p>

        <h1 className="landing-title">Find somewhere worth sleeping.</h1>

        <p className="landing-lede">
          CampSite scores backcountry sites across the Adirondacks on how close the water
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
            Open the map
          </Link>
          {!session && (
            <span className="landing-secondary">
              <Link to="/register" className="link-button">
                Create an account
              </Link>{" "}
              to save the ones you like, or{" "}
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
