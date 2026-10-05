/**
 * The homepage (TM05-68).
 *
 * The hero keeps the original front door's copy. Below it, three short sections walk
 * through what the app does today, each next to a screen recording of it. Then one line
 * on coverage, one way in, and the data credits.
 *
 * Every sentence here describes something the app does now; check the code before
 * adding one. The recordings are listed in docs/media-shot-list.md, and until a file
 * exists its slot says what to record.
 */

import { Link } from "react-router-dom";
import { IMAGERY_ATTRIBUTION } from "../basemap/satellite";
import FeatureMedia from "../home/FeatureMedia";
import "../home/home.css";
import { useSession } from "../session";

interface Feature {
  id: string;
  title: string;
  body: string;
  media: { name: string; label: string; description: string };
}

const HERO_MEDIA = {
  name: "hero",
  label: "RECORD: 3D flythrough, Van Hoevenberg Trail to Marcy, satellite on, ~8 s",
  description:
    "A 3D flythrough of the Van Hoevenberg Trail climbing Mount Marcy over satellite imagery.",
};

const FEATURES: Feature[] = [
  {
    id: "route",
    title: "Preview the route before you go",
    body:
      "Click a named trail and you get its distance, total climb, high point, steepest " +
      "stretch and a rough walking time, with the elevation profile underneath. Move along " +
      "the profile and a marker follows on the map; switch on 3D to see the terrain, or let " +
      "it fly the route.",
    media: {
      name: "route-preview",
      label:
        "RECORD: Van Hoevenberg Trail panel, cursor along the profile, then 3D on and a few seconds of flythrough, ~9 s",
      description:
        "Moving along a trail's elevation profile while a marker follows on the map, then the same trail in 3D.",
    },
  },
  {
    id: "campsites",
    title: "Find campsites along the trail",
    body:
      "Mapped campsites near the route are listed in trail order, by mile, with how far each " +
      "one sits off the trail. Choose how far you're willing to walk off it, from 250 m to " +
      "2 km, and the same sites are marked on the profile.",
    media: {
      name: "campsites-along-trail",
      label:
        "RECORD: Van Hoevenberg Trail campsite list, hover each site as the profile marker follows, click Marcy Dam, ~8 s",
      description:
        "The list of campsites along a trail by mile marker, each with its distance off the trail.",
    },
  },
  {
    id: "score",
    title: "See what's behind a site's score",
    body:
      "Sites along a trail get a score out of 100 from the distance to water, the slope of " +
      "the ground, trail access, whether the land is open to camping, and tonight's " +
      "forecast. Open a site and you see what it rests on: the nearest named water and how " +
      "far, the slope, the nearest trail, and the public land it sits on.",
    media: {
      name: "site-score",
      label:
        "RECORD: Marcy Dam (score 99) opened from the Van Hoevenberg list, panel scrolls through land, slope, water, trail, ~7 s",
      description:
        "A campsite's panel listing its public land unit, slope, nearest water and nearest trail.",
    },
  },
];

const SOURCES: { what: string; who: string; href: string }[] = [
  {
    what: "Trails, routes and campsites",
    who: "© OpenStreetMap contributors",
    href: "https://www.openstreetmap.org/copyright",
  },
  {
    what: "Lakes and streams",
    who: "USGS National Hydrography Dataset (NHD)",
    href: "https://www.usgs.gov/national-hydrography",
  },
  {
    what: "Elevation profiles and slope",
    who: "USGS 3D Elevation Program (3DEP)",
    href: "https://www.usgs.gov/3d-elevation-program",
  },
  {
    what: "Public land",
    who: "USGS Protected Areas Database of the United States (PAD-US)",
    href: "https://www.usgs.gov/programs/gap-analysis-project/science/pad-us-data-overview",
  },
  {
    what: "Federal campgrounds",
    who: "Recreation.gov (RIDB)",
    href: "https://ridb.recreation.gov/",
  },
  {
    what: "Satellite imagery",
    // The same credit the map shows (basemap/satellite.ts), without its link markup.
    who: IMAGERY_ATTRIBUTION.replace(/<[^>]+>/g, ""),
    href: "https://goto.arcgisonline.com/maps/World_Imagery",
  },
];

function media(name: string) {
  return { src: `/media/${name}.mp4`, poster: `/media/${name}-poster.jpg` };
}

export default function Landing() {
  const { session } = useSession();

  return (
    <main className="page page-home">
      <div className="home">
        <section className="home-hero" aria-labelledby="home-title">
          <div className="home-hero-text">
            <p className="eyebrow">Backcountry exploration</p>

            <h1 id="home-title" className="home-title">
              Find where to spend the night.
            </h1>

            <p className="home-lede">
              Explore the trails and terrain of the Adirondacks and the White Mountains, then
              find a place to stop. CampSite scores backcountry sites on how close the water
              is, how flat the ground is, whether a trail reaches them, and whether you are
              allowed to camp there.
            </p>

            <div className="home-actions">
              <Link to="/discover" className="button-primary button-lg">
                Explore the map
              </Link>
              {!session && (
                <span className="home-secondary">
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

          <FeatureMedia
            {...media(HERO_MEDIA.name)}
            label={HERO_MEDIA.label}
            description={HERO_MEDIA.description}
            eager
          />
        </section>

        {FEATURES.map((feature, index) => (
          <section
            key={feature.id}
            className={`home-feature${index % 2 === 0 ? " is-flipped" : ""}`}
            aria-labelledby={`feature-${feature.id}`}
          >
            <div className="home-feature-text">
              <h2 id={`feature-${feature.id}`} className="home-feature-title">
                {feature.title}
              </h2>
              <p className="home-feature-body">{feature.body}</p>
            </div>
            <FeatureMedia
              {...media(feature.media.name)}
              label={feature.media.label}
              description={feature.media.description}
            />
          </section>
        ))}

        <section className="home-coverage" aria-label="Coverage">
          <p>
            Data today covers the Adirondacks in New York and the White Mountains in New
            Hampshire.
          </p>
        </section>

        <section className="home-cta" aria-labelledby="home-cta-title">
          <h2 id="home-cta-title" className="home-cta-title">
            Pick a trail and see where you'd stop for the night.
          </h2>
          <Link to="/discover" className="button-primary button-lg">
            Explore the map
          </Link>
        </section>
      </div>

      <footer className="home-footer">
        <div className="home-footer-inner">
          <h2 className="home-footer-title">Data sources</h2>
          <dl className="home-sources">
            {SOURCES.map((source) => (
              <div key={source.what} className="home-source">
                <dt>{source.what}</dt>
                <dd>
                  <a href={source.href} target="_blank" rel="noopener noreferrer">
                    {source.who}
                  </a>
                </dd>
              </div>
            ))}
          </dl>
          <p className="home-footer-note">
            Basemap and 3D terrain credits are shown on the map itself.
          </p>
        </div>
      </footer>
    </main>
  );
}
