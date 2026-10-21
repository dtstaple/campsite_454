"""
Tests for scripts/doctor.py's .env and requirements checks. Since TM05-113, a .env without
DEBUG=True needs a SECRET_KEY, and requirements.txt gained packages that older virtualenvs
lack. Both used to slip past make doctor.
"""

import importlib.util
from importlib.metadata import PackageNotFoundError
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"


@pytest.fixture
def doctor(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("doctor", SCRIPTS / "doctor.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    (tmp_path / ".env").write_text("")
    monkeypatch.setattr(module, "ROOT", tmp_path)
    return module


def env(**overrides):
    values = {
        "POSTGRES_DB": "campsite",
        "POSTGRES_USER": "campsite",
        "POSTGRES_PASSWORD": "pw",
        "POSTGRES_PORT": "5432",
        "DATABASE_URL": "postgis://campsite:pw@localhost:5432/campsite",
        "CORS_ALLOWED_ORIGINS": "http://localhost:5173",
        "RIDB_API_KEY": "x",
    }
    values.update(overrides)
    return values


@pytest.mark.unit
def test_no_secret_key_without_debug_fails(doctor, capsys):
    doctor.check_env(env())
    out = capsys.readouterr().out
    assert doctor.failures == 1
    assert "FAIL .env: SECRET_KEY unset and DEBUG is not True" in out
    assert "add DEBUG=True and SECRET_KEY" in out


@pytest.mark.unit
def test_no_secret_key_with_debug_only_warns(doctor, capsys):
    doctor.check_env(env(DEBUG="True"))
    assert doctor.failures == 0
    assert "WARN .env: SECRET_KEY unset -- DEBUG=True" in capsys.readouterr().out


@pytest.mark.unit
def test_a_secret_key_passes_without_debug(doctor, capsys):
    doctor.check_env(env(SECRET_KEY="long-random-value"))
    assert doctor.failures == 0
    assert "SECRET_KEY" not in capsys.readouterr().out


@pytest.fixture
def pins(doctor, monkeypatch):
    (doctor.ROOT / "requirements.txt").write_text(
        "# --- core ---\nDjango==5.1.3\nwhitenoise==6.8.2  # TM05-113\n\nruff==0.6.9\n"
    )
    monkeypatch.setattr(doctor.sys, "prefix", "/venv")
    monkeypatch.setattr(doctor.sys, "base_prefix", "/usr")

    def installed(packages):
        def version(name):
            if name not in packages:
                raise PackageNotFoundError(name)
            return packages[name]

        monkeypatch.setattr("importlib.metadata.version", version)

    return installed


@pytest.mark.unit
def test_requirements_all_pinned_versions_pass(doctor, pins, capsys):
    pins({"Django": "5.1.3", "whitenoise": "6.8.2", "ruff": "0.6.9"})
    doctor.check_requirements()
    assert doctor.failures == 0
    assert "PASS requirements" in capsys.readouterr().out


@pytest.mark.unit
def test_requirements_missing_or_wrong_version_fails(doctor, pins, capsys):
    pins({"Django": "5.1.3", "ruff": "0.5.0"})
    doctor.check_requirements()
    out = capsys.readouterr().out
    assert doctor.failures == 1
    assert "whitenoise missing" in out
    assert "ruff 0.5.0 (want 0.6.9)" in out
    assert "pip install -r requirements.txt" in out


@pytest.mark.unit
def test_requirements_skipped_outside_the_venv(doctor, monkeypatch, capsys):
    monkeypatch.setattr(doctor.sys, "base_prefix", doctor.sys.prefix)
    doctor.check_requirements()
    assert doctor.failures == 0
    assert capsys.readouterr().out == ""


# --- the rest of make doctor, with docker, node, ports and lsof faked ---------------------


def completed(returncode=0, stdout=""):
    return __import__("subprocess").CompletedProcess([], returncode, stdout, "")


def fake_run(monkeypatch, doctor, answers):
    """answers maps the first word(s) of a command to a CompletedProcess."""

    def run(command):
        for prefix, result in answers.items():
            if " ".join(command).startswith(prefix):
                return result
        return completed(1)

    monkeypatch.setattr(doctor, "run", run)


@pytest.mark.unit
def test_read_env_skips_comments_and_blank_lines(doctor):
    (doctor.ROOT / ".env").write_text("# note\n\nA=1\n B = two words \nnot a pair\n")
    assert doctor.read_env() == {"A": "1", "B": "two words"}


@pytest.mark.unit
def test_run_reports_a_missing_command_as_127(doctor):
    assert doctor.run(["campsite-no-such-command"]).returncode == 127


@pytest.mark.unit
def test_python_other_than_3_12_fails(doctor, monkeypatch, capsys):
    monkeypatch.setattr(doctor.platform, "python_version", lambda: "3.13.0")
    monkeypatch.setattr(doctor.sys, "base_prefix", doctor.sys.prefix)
    doctor.check_python()
    out = capsys.readouterr().out
    assert doctor.failures == 1
    assert "FAIL python: 3.13.0" in out
    assert "WARN python: not running inside .venv" in out


@pytest.mark.unit
@pytest.mark.parametrize(
    "result, expected",
    [
        (completed(127), "FAIL node: node not found"),
        (completed(0, "v20.11.0\n"), "FAIL node: v20.11.0, need 22+"),
        (completed(0, "v22.4.0\n"), "PASS node: v22.4.0 (CI uses 22)"),
    ],
)
def test_node_version(doctor, monkeypatch, capsys, result, expected):
    fake_run(monkeypatch, doctor, {"node": result})
    doctor.check_node()
    out = capsys.readouterr().out
    assert expected in out
    assert ("node_modules missing" in out) == (result.returncode == 0)


@pytest.mark.unit
def test_node_reads_the_wanted_version_from_nvmrc(doctor, monkeypatch, capsys):
    (doctor.ROOT / ".nvmrc").write_text("24\n")
    (doctor.ROOT / "frontend" / "node_modules").mkdir(parents=True)
    fake_run(monkeypatch, doctor, {"node": completed(0, "v24.1.0")})
    doctor.check_node()
    assert capsys.readouterr().out.strip() == "PASS node: v24.1.0 (CI uses 24)"


@pytest.mark.unit
@pytest.mark.parametrize(
    "overrides, expected",
    [
        ({"DATABASE_URL": "postgis://campsite:pw@localhost:5434/campsite"}, "POSTGRES_PORT"),
        ({"DATABASE_URL": "postgis://campsite:other@localhost:5432/campsite"}, "password"),
        ({"CORS_ALLOWED_ORIGINS": "http://localhost:3000"}, "port 5173"),
        ({"POSTGRES_DB": ""}, "unset: POSTGRES_DB"),
    ],
)
def test_env_mistakes_fail(doctor, capsys, overrides, expected):
    doctor.check_env(env(SECRET_KEY="k", **overrides))
    out = capsys.readouterr().out
    assert doctor.failures == 1
    assert expected in out


@pytest.mark.unit
def test_env_missing_file_and_missing_ridb_key(doctor, capsys):
    doctor.check_env(env(SECRET_KEY="k", RIDB_API_KEY=""))
    assert "WARN .env: RIDB_API_KEY empty" in capsys.readouterr().out
    (doctor.ROOT / ".env").unlink()
    doctor.check_env(env())
    assert "FAIL .env: missing" in capsys.readouterr().out


@pytest.mark.unit
@pytest.mark.parametrize(
    "which, answers, up, expected",
    [
        (None, {}, False, "docker not installed"),
        ("/usr/bin/docker", {"docker info": completed(1)}, False, "Docker is not running"),
        ("/usr/bin/docker", {"docker info": completed()}, False, "campsite_db does not exist"),
        (
            "/usr/bin/docker",
            {"docker info": completed(), "docker inspect": completed(0, "starting\n")},
            False,
            "campsite_db is starting",
        ),
        (
            "/usr/bin/docker",
            {"docker info": completed(), "docker inspect": completed(0, "healthy\n")},
            True,
            "PASS database container: campsite_db healthy",
        ),
    ],
)
def test_docker_and_the_database_container(
    doctor, monkeypatch, capsys, which, answers, up, expected
):
    monkeypatch.setattr(doctor.shutil, "which", lambda name: which)
    fake_run(monkeypatch, doctor, answers)
    assert doctor.check_docker({}) is up
    assert expected in capsys.readouterr().out


@pytest.mark.unit
def test_ports_free_ours_and_taken(doctor, monkeypatch, capsys):
    root = str(doctor.ROOT)
    owners = {
        5432: None,
        8000: f"python manage.py runserver [in {root}/backend]",
        5173: "nginx [in /]",
    }
    monkeypatch.setattr(doctor, "port_owner", owners.get)
    fake_run(monkeypatch, doctor, {})
    doctor.check_ports({})
    out = capsys.readouterr().out
    assert "FAIL port 5432: free, but the database should be listening" in out
    assert "PASS port 8000: in use by this checkout's backend" in out
    assert "FAIL port 5173: in use by something else: nginx [in /]" in out


@pytest.mark.unit
def test_ports_database_in_use_by_the_container_or_by_something_else(doctor, monkeypatch, capsys):
    monkeypatch.setattr(doctor, "port_owner", lambda port: "postgres" if port == 5432 else None)
    fake_run(monkeypatch, doctor, {"docker port": completed(0, "0.0.0.0:5432\n")})
    doctor.check_ports({})
    assert "PASS port 5432: in use by campsite_db" in capsys.readouterr().out
    fake_run(monkeypatch, doctor, {})
    doctor.check_ports({})
    assert "set POSTGRES_PORT to a free port" in capsys.readouterr().out


@pytest.mark.unit
def test_port_owner_free_and_listening(doctor, monkeypatch):
    import socket

    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        port = server.getsockname()[1]
        assert doctor.port_owner(port) is None
        server.listen()
        monkeypatch.setattr(doctor.shutil, "which", lambda name: "/usr/bin/lsof")
        fake_run(
            monkeypatch,
            doctor,
            {"lsof -t": completed(0, "41\n41\n"), "ps": completed(0, "postgres\n")},
        )
        monkeypatch.setattr(doctor, "process_cwd", lambda pid: "/srv")
        assert doctor.port_owner(port) == "postgres [in /srv]"
        monkeypatch.setattr(
            doctor.shutil, "which", lambda name: "/bin/ss" if name == "ss" else None
        )
        fake_run(monkeypatch, doctor, {"ss": completed(0, "users:((pid=7,fd=3))")})
        assert doctor.port_owner(port) == "unknown process (maybe Docker)"


@pytest.mark.unit
def test_process_cwd_falls_back_to_lsof(doctor, monkeypatch):
    def no_proc(path):
        raise OSError(path)

    monkeypatch.setattr(doctor.os, "readlink", no_proc)
    fake_run(monkeypatch, doctor, {"lsof -a": completed(0, "p41\nfcwd\nn/Users/me/campsite\n")})
    assert doctor.process_cwd("41") == "/Users/me/campsite"
    fake_run(monkeypatch, doctor, {})
    assert doctor.process_cwd("41") == "?"


@pytest.mark.unit
def test_django_is_skipped_outside_the_venv(doctor, monkeypatch, capsys):
    monkeypatch.setattr(doctor.sys, "base_prefix", doctor.sys.prefix)
    doctor.check_django({}, db_up=True)
    assert "WARN django: skipped" in capsys.readouterr().out


@pytest.mark.unit
def test_django_without_the_database(doctor, monkeypatch, capsys):
    monkeypatch.setattr(doctor.sys, "base_prefix", "/usr")
    doctor.check_django({}, db_up=False)
    out = capsys.readouterr().out
    assert "PASS gdal: GDAL" in out
    assert "FAIL database connection: skipped" in out


@pytest.mark.unit
def test_django_import_errors_carry_a_fix(doctor, monkeypatch, capsys):
    import django

    monkeypatch.setattr(doctor.sys, "base_prefix", "/usr")
    for message, fix in (
        ("Could not find the GDAL library", "brew install gdal"),
        ("boom", "check .env"),
    ):

        def broken(message=message):
            raise RuntimeError(message)

        monkeypatch.setattr(django, "setup", broken)
        doctor.check_django({}, db_up=True)
        out = capsys.readouterr().out
        assert f"FAIL django: RuntimeError: {message}" in out
        assert fix in out


@pytest.mark.django_db
def test_django_database_migrations_and_an_empty_database(doctor, monkeypatch, capsys):
    monkeypatch.setattr(doctor.sys, "base_prefix", "/usr")
    doctor.check_django({}, db_up=True)
    out = capsys.readouterr().out
    assert "PASS database connection: PostGIS" in out
    assert "PASS migrations: all applied" in out
    assert "FAIL data: database is empty" in out


@pytest.mark.django_db
def test_data_with_some_layers_empty_or_all_loaded(doctor, monkeypatch, capsys):
    from django.db.models import QuerySet

    counts = {"Campsite": 3, "Trail": 2, "WaterFeature": 0, "PublicLand": 1}
    monkeypatch.setattr(QuerySet, "count", lambda self: counts.get(self.model.__name__, 5))
    doctor.check_data()
    assert "WARN data: some layers empty: WaterFeature" in capsys.readouterr().out
    counts["WaterFeature"] = 9
    doctor.check_data()
    assert capsys.readouterr().out.startswith("PASS data: Campsite 3")


@pytest.mark.unit
def test_main_exit_code_follows_the_failures(doctor, monkeypatch, capsys):
    for name in ("check_python", "check_requirements", "check_node", "check_env", "check_ports"):
        monkeypatch.setattr(doctor, name, lambda *args: None)
    monkeypatch.setattr(doctor, "check_docker", lambda env: False)
    monkeypatch.setattr(doctor, "check_django", lambda env, up: None)
    assert doctor.main() == 0
    assert "All checks passed." in capsys.readouterr().out
    monkeypatch.setattr(doctor, "check_node", lambda: doctor.report("FAIL", "node", "x"))
    assert doctor.main() == 1
    assert "1 check(s) FAILED" in capsys.readouterr().out
