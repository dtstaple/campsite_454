"""
scripts/snapshot.py (TM05-160): `make dump` and `make restore` against any DATABASE_URL.
pg_dump/pg_restore are faked; nothing here downloads, dumps or drops anything for real.
"""

import importlib.util
import io
import subprocess
from fnmatch import fnmatchcase
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"


@pytest.fixture
def snapshot(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("snapshot", SCRIPTS / "snapshot.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "DUMPS", tmp_path / "dumps")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    return module


TOC = """;
; Archive created at 2026-11-08
3; 2615 2200 SCHEMA - public pg_database_owner
4; 0 0 COMMENT - SCHEMA public pg_database_owner
5; 0 0 COMMENT - EXTENSION postgis
220; 1259 16400 TABLE public geodata_campsite campsite
221; 1259 16410 TABLE public auth_user campsite
5001; 0 16400 TABLE DATA public geodata_campsite campsite
5002; 0 16500 TABLE DATA public routing_trailedge campsite
"""


# --- the connection --------------------------------------------------------------------------


@pytest.mark.unit
def test_pg_env_from_a_hosted_url(snapshot):
    env = snapshot.pg_env(
        "postgres://dev_davis:p%40ss%2Fword@ep-x.us-east-2.aws.neon.tech/campsite"
        "?sslmode=require&connect_timeout=10&unknown=1"
    )
    assert env == {
        "PGHOST": "ep-x.us-east-2.aws.neon.tech",
        "PGPORT": "5432",
        "PGUSER": "dev_davis",
        "PGPASSWORD": "p@ss/word",
        "PGDATABASE": "campsite",
        "PGSSLMODE": "require",
        "PGCONNECT_TIMEOUT": "10",
    }
    assert snapshot.describe(env) == (
        "dev_davis@ep-x.us-east-2.aws.neon.tech:5432/campsite sslmode=require"
    )
    assert "p@ss" not in snapshot.describe(env)


@pytest.mark.unit
@pytest.mark.parametrize(
    "url, message",
    [
        ("mysql://u:p@h/db", "postgres:// URL"),
        ("postgis://u:p@localhost:5432/", "names no database"),
    ],
)
def test_pg_env_rejects_bad_urls(snapshot, url, message):
    with pytest.raises(snapshot.SnapshotError, match=message):
        snapshot.pg_env(url)


@pytest.mark.unit
def test_database_url_prefers_the_environment_then_dot_env(snapshot, tmp_path, monkeypatch):
    with pytest.raises(snapshot.SnapshotError, match="DATABASE_URL is not set"):
        snapshot.database_url()
    (tmp_path / ".env").write_text("# x\nDATABASE_URL=postgis://a@localhost:5432/file\n")
    assert snapshot.database_url().endswith("/file")
    monkeypatch.setenv("DATABASE_URL", "postgis://a@localhost:5432/env")
    assert snapshot.database_url().endswith("/env")


# --- what goes in a dump -------------------------------------------------------------------


@pytest.mark.unit
def test_toc_parsing(snapshot):
    lines = TOC.splitlines()
    kept = snapshot.restore_list(lines)
    assert not any("SCHEMA - public" in line or "SCHEMA public" in line for line in kept)
    assert not any("COMMENT - EXTENSION" in line for line in kept)
    assert len(kept) == len(lines) - 3
    assert snapshot.data_tables(lines) == ["geodata_campsite", "routing_trailedge"]
    terrain = [
        "5003; 0 16600 TABLE DATA public terrain_terrainrun campsite",
        "5004; 0 16610 TABLE DATA public terrain_terrainzone campsite",
        "222; 1259 16600 TABLE public terrain_terrainrun campsite",
    ]
    light = snapshot.restore_list(lines + terrain, no_terrain=True)
    # Every terrain table's rows are left out, together; the tables themselves stay.
    assert snapshot.data_tables(light) == ["geodata_campsite", "routing_trailedge"]
    assert terrain[2] in light
    assert len(snapshot.data_tables(snapshot.restore_list(lines + terrain))) == 4


@pytest.mark.unit
@pytest.mark.parametrize(
    "table, mine",
    [
        ("auth_user", True),
        ("authtoken_token", True),
        ("accounts_savedcampsite", True),
        ("planning_hike", True),
        ("django_session", True),
        ("geodata_campsite", False),
        ("routing_trailedge", False),
        ("auth_permission", False),
    ],
)
def test_personal_tables(snapshot, table, mine):
    assert snapshot.personal(table) is mine


@pytest.mark.django_db
def test_every_table_that_points_at_a_user_is_left_out_of_dumps(snapshot):
    """A new model holding a person's data must match PERSONAL_TABLES, or `make dump` would
    publish it. Follows foreign keys, so a trip plan's stops count as the user's too."""
    from django.apps import apps
    from django.contrib.auth import get_user_model

    owned = {get_user_model()}
    changed = True
    while changed:
        changed = False
        for model in apps.get_models(include_auto_created=True):
            if model in owned:
                continue
            targets = {f.related_model for f in model._meta.fields if f.is_relation}
            if targets & owned:
                owned.add(model)
                changed = True
    leaked = [
        model._meta.db_table
        for model in owned
        if not any(fnmatchcase(model._meta.db_table, p) for p in snapshot.PERSONAL_TABLES)
    ]
    # The admin log is listed by name; everything else must match too.
    assert leaked == []


# --- the client tools ----------------------------------------------------------------------


@pytest.mark.unit
def test_tools_run_locally_when_pg_restore_is_new_enough(snapshot, monkeypatch, tmp_path):
    monkeypatch.setattr(snapshot, "tools_major", lambda binary: 16)
    tools = snapshot.Tools({"PGHOST": "db", "PGPASSWORD": "secret"}, tmp_path)
    assert tools.mode == "local"
    command, env = tools.command(["pg_restore", "--list", "x.dump"])
    assert command == ["pg_restore", "--list", "x.dump"]
    assert env["PGPASSWORD"] == "secret"


@pytest.mark.unit
def test_tools_fall_back_to_docker_without_the_password_in_argv(snapshot, monkeypatch, tmp_path):
    monkeypatch.setattr(snapshot, "tools_major", lambda binary: 14)
    monkeypatch.setattr(snapshot.shutil, "which", lambda name: "/usr/bin/docker")
    tools = snapshot.Tools({"PGHOST": "localhost", "PGPASSWORD": "secret"}, tmp_path)
    assert tools.mode == "docker"
    command, env = tools.command(["pg_dump", "--file=out.dump"])
    assert "secret" not in " ".join(command)
    assert command[-3:] == [snapshot.TOOLS_IMAGE, "pg_dump", "--file=out.dump"]
    assert ["-e", "PGPASSWORD"] == command[
        command.index("PGPASSWORD") - 1 : command.index("PGPASSWORD") + 1
    ]
    assert f"{tmp_path.resolve()}:/work" in command
    # localhost on the host is host.docker.internal from inside the container.
    assert env["PGHOST"] == "host.docker.internal"


@pytest.mark.unit
def test_tools_without_pg_restore_or_docker_say_how_to_get_them(snapshot, monkeypatch, tmp_path):
    monkeypatch.setattr(snapshot, "tools_major", lambda binary: None)
    monkeypatch.setattr(snapshot.shutil, "which", lambda name: None)
    with pytest.raises(snapshot.SnapshotError, match="brew install libpq"):
        snapshot.Tools({}, tmp_path)


@pytest.mark.unit
def test_tools_major_reads_the_version(snapshot, monkeypatch):
    monkeypatch.setattr(snapshot.shutil, "which", lambda name: "/usr/bin/pg_restore")
    monkeypatch.setattr(
        snapshot.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(a, 0, "pg_restore (PostgreSQL) 16.4\n", ""),
    )
    assert snapshot.tools_major("pg_restore") == 16
    monkeypatch.setattr(snapshot.shutil, "which", lambda name: None)
    assert snapshot.tools_major("pg_restore") is None


@pytest.mark.unit
def test_a_failing_tool_raises_with_its_stderr(snapshot, monkeypatch, tmp_path):
    tools = snapshot.Tools({}, tmp_path, mode="local")
    monkeypatch.setattr(
        snapshot.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(a, 1, "", "could not connect\n"),
    )
    with pytest.raises(snapshot.SnapshotError, match="pg_restore failed .exit 1.. could not"):
        tools.run(["pg_restore", "--list", "x.dump"], capture=True)


class FakeTools:
    """Records each call; `pg_restore --list` answers with TOC."""

    calls: list = []

    def __init__(self, env, workdir, mode=None):
        self.env, self.workdir, self.mode = env, Path(workdir), "fake"

    def run(self, args, capture=False):
        FakeTools.calls.append((args, self.workdir))
        if "--list" in args:
            return subprocess.CompletedProcess(args, 0, FakeTools.toc, "")
        for arg in args:
            if arg.startswith("--file="):
                (self.workdir / arg.removeprefix("--file=")).write_bytes(b"PGDMP")
        if "--use-list=restore.list" in args:
            FakeTools.restored_list = (self.workdir / "restore.list").read_text()
        return subprocess.CompletedProcess(args, 0, "", "")


@pytest.fixture
def fake_tools(snapshot, monkeypatch):
    FakeTools.calls = []
    FakeTools.toc = TOC
    monkeypatch.setattr(snapshot, "Tools", FakeTools)
    return FakeTools


# --- restore -------------------------------------------------------------------------------


@pytest.fixture
def target(snapshot, monkeypatch):
    """A fake database: `tables` lists the tables with rows."""
    state = {"tables": [], "postgis": [], "dropped": 0, "closed": False}

    class Connection:
        def close(self):
            state["closed"] = True

    monkeypatch.setenv("DATABASE_URL", "postgis://campsite:pw@localhost:5432/campsite")
    monkeypatch.setattr(snapshot, "connect", lambda env: Connection())
    monkeypatch.setattr(snapshot, "non_empty_tables", lambda c: state["tables"])
    monkeypatch.setattr(
        snapshot, "ensure_postgis", lambda c: state["postgis"].append(1) or "PostGIS created"
    )
    monkeypatch.setattr(snapshot, "drop_public_tables", lambda c: state.update(dropped=1) or 1)
    monkeypatch.setattr(snapshot, "summary", lambda c: "    campsites 3")
    return state


@pytest.mark.unit
def test_restore_refuses_a_database_with_data(snapshot, target, fake_tools, tmp_path):
    target["tables"] = ["auth_user", "geodata_campsite"]
    dump = tmp_path / "x.dump"
    dump.write_bytes(b"PGDMP")
    with pytest.raises(snapshot.SnapshotError, match="FORCE=1"):
        snapshot.restore(str(dump))
    assert fake_tools.calls == [] and target["dropped"] == 0
    # --if-empty: the dev container's rebuild keeps what is there.
    assert snapshot.restore(str(dump), if_empty=True) == 0
    assert fake_tools.calls == []


@pytest.mark.unit
@pytest.mark.parametrize("force, tables", [(False, []), (True, ["geodata_campsite"])])
def test_restore_creates_postgis_drops_restores(
    snapshot, target, fake_tools, tmp_path, capsys, force, tables
):
    target["tables"] = tables
    dump = tmp_path / "x.dump"
    dump.write_bytes(b"PGDMP")
    assert snapshot.restore(str(dump), force=force, migrate=False) == 0
    assert target["postgis"] == [1] and target["dropped"] == 1 and target["closed"]
    restore_args = fake_tools.calls[-1][0]
    assert restore_args[0] == "pg_restore" and "--no-owner" in restore_args
    assert "--dbname=campsite" in restore_args and "pw" not in " ".join(restore_args)
    assert "SCHEMA - public" not in fake_tools.restored_list
    assert "TABLE DATA public geodata_campsite" in fake_tools.restored_list
    assert "Target: campsite@localhost:5432/campsite" in capsys.readouterr().out


@pytest.mark.unit
def test_restore_runs_migrate_against_the_same_database(
    snapshot, target, fake_tools, tmp_path, monkeypatch
):
    dump = tmp_path / "x.dump"
    dump.write_bytes(b"PGDMP")
    ran = []
    monkeypatch.setattr(snapshot.subprocess, "run", lambda cmd, **k: ran.append((cmd, k["env"])))
    snapshot.restore(str(dump))
    command, env = ran[0]
    assert command[-2:] == ["migrate", "--no-input"]
    assert env["DATABASE_URL"] == "postgis://campsite:pw@localhost:5432/campsite"


@pytest.mark.unit
def test_fetch_a_path_a_missing_path_and_a_url(snapshot, tmp_path, monkeypatch):
    local = tmp_path / "a.dump"
    local.write_bytes(b"x")
    assert snapshot.fetch(str(local)) == local
    with pytest.raises(snapshot.SnapshotError, match="no such dump"):
        snapshot.fetch(str(tmp_path / "missing.dump"))

    opened = []

    def urlopen(url, timeout):
        opened.append(url)
        return io.BytesIO(b"PGDMP-data")

    monkeypatch.setattr(snapshot.urllib.request, "urlopen", urlopen)
    url = "https://github.com/o/r/releases/download/dev-data-x/campsite-x.dump"
    path = snapshot.fetch(url)
    assert path == tmp_path / "dumps" / "campsite-x.dump"
    assert path.read_bytes() == b"PGDMP-data"
    assert snapshot.fetch(url) == path and len(opened) == 1  # reused, not downloaded again

    def broken(url, timeout):
        raise OSError("404")

    monkeypatch.setattr(snapshot.urllib.request, "urlopen", broken)
    with pytest.raises(snapshot.SnapshotError, match="download failed"):
        snapshot.fetch(url.replace("campsite-x", "campsite-y"))
    assert not list((tmp_path / "dumps").glob("*.part"))


# --- dump and check ------------------------------------------------------------------------


@pytest.mark.unit
def test_dump_excludes_personal_data_and_checks_the_result(
    snapshot, fake_tools, tmp_path, monkeypatch, capsys
):
    monkeypatch.setenv("DATABASE_URL", "postgis://campsite:pw@localhost:5432/campsite")
    out = tmp_path / "dumps" / "campsite-test.dump"
    assert snapshot.dump(out) == 0
    args = fake_tools.calls[0][0]
    assert args[0] == "pg_dump" and "--schema=public" in args
    for pattern in snapshot.PERSONAL_TABLES:
        assert f"--exclude-table-data={pattern}" in args
    assert out.exists()
    assert "No personal tables have data." in capsys.readouterr().out


@pytest.mark.unit
def test_a_dump_with_personal_data_is_deleted(snapshot, fake_tools, tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgis://campsite:pw@localhost:5432/campsite")
    fake_tools.toc = TOC + "5003; 0 16600 TABLE DATA public auth_user campsite\n"
    out = tmp_path / "leaky.dump"
    with pytest.raises(snapshot.SnapshotError, match="personal data: auth_user"):
        snapshot.dump(out)
    assert not out.exists()


@pytest.mark.unit
def test_main_reports_failures_and_dispatches(snapshot, fake_tools, tmp_path, capsys):
    assert snapshot.main(["restore", str(tmp_path / "none.dump")]) == 1
    assert "FAIL DATABASE_URL is not set" in capsys.readouterr().err
    dump = tmp_path / "ok.dump"
    dump.write_bytes(b"PGDMP")
    assert snapshot.main(["check", str(dump)]) == 0
    assert "rows for 2 tables" in capsys.readouterr().out


# --- against the test database ---------------------------------------------------------------


@pytest.mark.django_db
def test_non_empty_tables_and_postgis_on_a_real_database(snapshot):
    from django.db import connection
    from django.utils import timezone

    from geodata.models import IngestRun

    connection.ensure_connection()
    raw = connection.connection
    assert snapshot.ensure_postgis(raw).startswith("PostGIS 3")
    assert snapshot.non_empty_tables(raw) == []  # migrate's own rows do not count
    assert "routing graph edges" in snapshot.summary(raw)
    IngestRun.objects.create(source="osm", region="adirondacks", started_at=timezone.now())
    assert snapshot.non_empty_tables(raw) == ["geodata_ingestrun"]
