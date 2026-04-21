"""Tests for project-local Hermes bootstrap behavior."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from hermes_bootstrap import bootstrap_local_hermes_home


def test_bootstrap_uses_project_profile_and_strips_args(tmp_path, monkeypatch):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    monkeypatch.setenv("HERMES_PROJECT_ROOT", str(repo_root))
    monkeypatch.delenv("HERMES_HOME", raising=False)
    monkeypatch.setattr(sys, "argv", ["hermes", "--profile", "coder", "chat"])

    resolved = bootstrap_local_hermes_home()

    assert resolved == (repo_root / ".hermes-home" / "profiles" / "coder")
    assert os.environ["HERMES_HOME"] == str(resolved)
    assert sys.argv == ["hermes", "chat"]


def test_bootstrap_rejects_external_home(tmp_path, monkeypatch):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    monkeypatch.setenv("HERMES_PROJECT_ROOT", str(repo_root))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "outside"))

    with pytest.raises(RuntimeError, match="outside this checkout"):
        bootstrap_local_hermes_home(argv=["chat"], mutate_sys_argv=False)


def test_entrypoints_bootstrap_to_project_local_home(tmp_path):
    repo_root = Path(__file__).resolve().parents[1]
    project_root = tmp_path / "portable-repo"
    project_root.mkdir()
    expected_home = project_root / ".hermes-home"

    modules = [
        ("hermes_cli.main", "import os, hermes_cli.main; print(os.environ['HERMES_HOME'])"),
        (
            "run_agent",
            "import os, sys, types; sys.modules.setdefault('fire', types.SimpleNamespace(Fire=lambda *a, **k: None)); "
            "import run_agent; print(os.environ['HERMES_HOME'])",
        ),
        ("cli", "import os, cli; print(os.environ['HERMES_HOME'])"),
        ("gateway.run", "import os, gateway.run; print(os.environ['HERMES_HOME'])"),
        ("acp_adapter.entry", "import os, acp_adapter.entry; print(os.environ['HERMES_HOME'])"),
    ]

    base_env = {
        **os.environ,
        "PYTHONPATH": str(repo_root),
        "HERMES_PROJECT_ROOT": str(project_root),
    }
    base_env.pop("HERMES_HOME", None)
    interpreter = repo_root / ".venv" / "bin" / "python"
    if not interpreter.exists():
        interpreter = Path(sys.executable)

    for name, code in modules:
        result = subprocess.run(
            [str(interpreter), "-c", code],
            cwd=str(repo_root),
            env=base_env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, f"{name} failed: {result.stderr}"
        assert result.stdout.strip().splitlines()[-1] == str(expected_home)


def test_main_entrypoint_rejects_external_home(tmp_path):
    repo_root = Path(__file__).resolve().parents[1]
    project_root = tmp_path / "portable-repo"
    project_root.mkdir()

    env = {
        **os.environ,
        "PYTHONPATH": str(repo_root),
        "HERMES_PROJECT_ROOT": str(project_root),
        "HERMES_HOME": str(tmp_path / "outside-home"),
    }

    result = subprocess.run(
        [sys.executable, "-c", "import hermes_cli.main"],
        cwd=str(repo_root),
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode != 0
    assert "outside this checkout" in result.stderr
