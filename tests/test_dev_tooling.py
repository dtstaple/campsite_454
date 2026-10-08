"""
Tests for the developer setup tooling (TM05-67): scripts/ensure_env.py,
scripts/build_data.py and the build_route_profiles command. Nothing touches the network.
"""

import importlib.util
from io import StringIO
from pathlib import Path

import pytest
from django.contrib.gis.geos import LineString, MultiLineString
from django.core.management import CommandError, call_command

from analysis.analyses import elevation
from geodata.models import TrailRoute

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"


def load_script(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def ensure_env(tmp_path, monkeypatch):
    module = load_script("ensure_env")
    example = tmp_path / ".env.example"
    example.write_text(
        "SECRET_KEY=change-me-locally\n# GDAL_LIBRARY_PATH=\n# GEOS_LIBRARY_PATH=\nX=1\n"
    )
    monkeypatch.setattr(module, "ENV", tmp_path / ".env")
    monkeypatch.setattr(module, "EXAMPLE", example)
    return module


@pytest.mark.unit
def test_ensure_env_creates_env_with_a_real_secret(ensure_env, monkeypatch):
    monkeypatch.setattr(ensure_env.platform, "system", lambda: "Linux")
    assert ensure_env.main() == 0
    text = ensure_env.ENV.read_text()
    assert "change-me-locally" not in text
    assert "# GDAL_LIBRARY_PATH=\n" in text  # unset on Linux: system default paths
    assert "X=1" in text


@pytest.mark.unit
def test_ensure_env_fills_homebrew_paths_on_macos(ensure_env, monkeypatch, tmp_path):
    monkeypatch.setattr(ensure_env.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(ensure_env, "brew_prefix", lambda formula: f"/opt/homebrew/opt/{formula}")
    ensure_env.main()
    text = ensure_env.ENV.read_text()
    assert "GDAL_LIBRARY_PATH=/opt/homebrew/opt/gdal/lib/libgdal.dylib" in text
    assert "GEOS_LIBRARY_PATH=/opt/homebrew/opt/geos/lib/libgeos_c.dylib" in text


@pytest.mark.unit
def test_ensure_env_never_overwrites(ensure_env):
    ensure_env.ENV.write_text("MINE=1\n")
    ensure_env.main()
    assert ensure_env.ENV.read_text() == "MINE=1\n"


@pytest.mark.unit
def test_build_data_runs_steps_in_dependency_order():
    names = [name for name, _ in load_script("build_data").steps("adirondacks")]
    assert names.index("osm-routes") < names.index("route-profiles") < names.index("enrich")
    # Enrichment reads every other layer; route facts read the profiles.
    assert names.index("route-profiles") < names.index("route-facts")
    assert names[-2:] == ["enrich", "route-facts"]


@pytest.mark.unit
def test_build_data_rejects_unknown_steps(monkeypatch, capsys):
    module = load_script("build_data")
    monkeypatch.setattr("sys.argv", ["build_data.py", "--only", "nope"])
    assert module.main() == 2
    assert "Unknown step(s): nope" in capsys.readouterr().out


@pytest.mark.unit
def test_build_data_skips_ridb_without_a_key(monkeypatch, capsys):
    module = load_script("build_data")
    monkeypatch.setattr(module, "ridb_key", lambda: "")
    monkeypatch.setattr("sys.argv", ["build_data.py", "--only", "ridb"])
    assert module.main() == 0
    assert "SKIP" in capsys.readouterr().out


@pytest.mark.django_db
@pytest.mark.integration
def test_build_route_profiles_computes_then_reuses_cache(monkeypatch):
    calls = []

    def flat_3dep(points):
        calls.append(len(points))
        return {
            "samples": [
                {"locationId": i, "value": "500", "resolution": 1, "attributes": {}}
                for i in range(len(points))
            ]
        }

    monkeypatch.setattr(elevation, "post_samples", flat_3dep)
    for osm_id, name, x in ((1, "Inside Trail", -74.0), (2, "", -73.9)):
        TrailRoute.objects.create(
            source=TrailRoute.Source.OSM,
            source_id=f"relation/{osm_id}",
            osm_id=osm_id,
            name=name,
            geom=MultiLineString(LineString((x, 44.0), (x + 0.02, 44.0)), srid=4326),
            length_m=1600,
            member_way_ids=[osm_id],
        )

    out = StringIO()
    call_command("build_route_profiles", "adirondacks", stdout=out)
    assert "1 named routes" in out.getvalue()  # the unnamed route is skipped
    assert "1 computed, 0 already cached, 0 failed" in out.getvalue()
    first_calls = len(calls)

    out = StringIO()
    call_command("build_route_profiles", "adirondacks", stdout=out)
    assert "0 computed, 1 already cached" in out.getvalue()
    assert len(calls) == first_calls


@pytest.mark.django_db
@pytest.mark.unit
def test_build_route_profiles_rejects_unknown_region():
    with pytest.raises(CommandError):
        call_command("build_route_profiles", "atlantis")
