"""
Structural tests: verify the repo has the layout and config the team agreed on.
These catch a broken or incomplete checkout before anything else runs.
"""

import os

import pytest

REQUIRED_FILES = [
    "README.md",
    "LICENSE",
    ".gitignore",
    "requirements.txt",
    "pyproject.toml",
    "docs/onboarding.md",
    "docs/CONTRIBUTING.md",
]

REQUIRED_DIRS = ["docs", "artifacts", "tests"]


@pytest.mark.unit
@pytest.mark.parametrize("relpath", REQUIRED_FILES)
def test_required_file_exists(project_root, relpath):
    assert os.path.isfile(os.path.join(project_root, relpath)), f"missing {relpath}"


@pytest.mark.unit
@pytest.mark.parametrize("relpath", REQUIRED_DIRS)
def test_required_dir_exists(project_root, relpath):
    assert os.path.isdir(os.path.join(project_root, relpath)), f"missing dir {relpath}"


@pytest.mark.unit
def test_env_fixture_isolates_values(env):
    env({"CAMPSITE_TEST_VAR": "set"})
    assert os.environ["CAMPSITE_TEST_VAR"] == "set"
