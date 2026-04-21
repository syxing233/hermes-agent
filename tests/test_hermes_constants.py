"""Tests for hermes_constants module."""

import os
from pathlib import Path
from unittest.mock import patch

import pytest

import hermes_constants
from hermes_bootstrap import ensure_allowed_hermes_home, get_project_hermes_home
from hermes_constants import get_default_hermes_root, get_hermes_home, is_container


class TestGetDefaultHermesRoot:
    """Tests for project-local Hermes root helpers."""

    def test_no_hermes_home_returns_project_local_home(self, tmp_path, monkeypatch):
        """When HERMES_HOME is not set, returns <repo>/.hermes-home."""
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        monkeypatch.setenv("HERMES_PROJECT_ROOT", str(repo_root))
        monkeypatch.delenv("HERMES_HOME", raising=False)
        assert get_default_hermes_root() == repo_root / ".hermes-home"
        assert get_hermes_home() == repo_root / ".hermes-home"

    def test_hermes_home_is_project_local_root(self, tmp_path, monkeypatch):
        repo_root = tmp_path / "repo"
        native = repo_root / ".hermes-home"
        native.mkdir(parents=True)
        monkeypatch.setenv("HERMES_PROJECT_ROOT", str(repo_root))
        monkeypatch.setenv("HERMES_HOME", str(native))
        assert get_default_hermes_root() == native

    def test_hermes_home_is_project_local_profile(self, tmp_path, monkeypatch):
        repo_root = tmp_path / "repo"
        native = repo_root / ".hermes-home"
        profile = native / "profiles" / "coder"
        profile.mkdir(parents=True)
        monkeypatch.setenv("HERMES_PROJECT_ROOT", str(repo_root))
        monkeypatch.setenv("HERMES_HOME", str(profile))
        assert get_default_hermes_root() == native

    def test_custom_external_hermes_home_still_round_trips_for_low_level_calls(self, tmp_path, monkeypatch):
        docker_home = tmp_path / "opt" / "data"
        docker_home.mkdir(parents=True)
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        monkeypatch.setenv("HERMES_PROJECT_ROOT", str(repo_root))
        monkeypatch.setenv("HERMES_HOME", str(docker_home))
        assert get_default_hermes_root() == docker_home

    def test_project_local_validation_rejects_external_home(self, tmp_path, monkeypatch):
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        monkeypatch.setenv("HERMES_PROJECT_ROOT", str(repo_root))
        with pytest.raises(RuntimeError):
            ensure_allowed_hermes_home(tmp_path / "outside")

    def test_project_local_validation_accepts_project_profile(self, tmp_path, monkeypatch):
        repo_root = tmp_path / "repo"
        profile = repo_root / ".hermes-home" / "profiles" / "coder"
        profile.mkdir(parents=True)
        monkeypatch.setenv("HERMES_PROJECT_ROOT", str(repo_root))
        assert ensure_allowed_hermes_home(profile) == profile.resolve()
        assert get_project_hermes_home() == (repo_root / ".hermes-home")


class TestIsContainer:
    """Tests for is_container() — Docker/Podman detection."""

    def _reset_cache(self, monkeypatch):
        """Reset the cached detection result before each test."""
        monkeypatch.setattr(hermes_constants, "_container_detected", None)

    def test_detects_dockerenv(self, monkeypatch, tmp_path):
        """/.dockerenv triggers container detection."""
        self._reset_cache(monkeypatch)
        monkeypatch.setattr(os.path, "exists", lambda p: p == "/.dockerenv")
        assert is_container() is True

    def test_detects_containerenv(self, monkeypatch, tmp_path):
        """/run/.containerenv triggers container detection (Podman)."""
        self._reset_cache(monkeypatch)
        monkeypatch.setattr(os.path, "exists", lambda p: p == "/run/.containerenv")
        assert is_container() is True

    def test_detects_cgroup_docker(self, monkeypatch, tmp_path):
        """/proc/1/cgroup containing 'docker' triggers detection."""
        import builtins
        self._reset_cache(monkeypatch)
        monkeypatch.setattr(os.path, "exists", lambda p: False)
        cgroup_file = tmp_path / "cgroup"
        cgroup_file.write_text("12:memory:/docker/abc123\n")
        _real_open = builtins.open
        monkeypatch.setattr("builtins.open", lambda p, *a, **kw: _real_open(str(cgroup_file), *a, **kw) if p == "/proc/1/cgroup" else _real_open(p, *a, **kw))
        assert is_container() is True

    def test_negative_case(self, monkeypatch, tmp_path):
        """Returns False on a regular Linux host."""
        import builtins
        self._reset_cache(monkeypatch)
        monkeypatch.setattr(os.path, "exists", lambda p: False)
        cgroup_file = tmp_path / "cgroup"
        cgroup_file.write_text("12:memory:/\n")
        _real_open = builtins.open
        monkeypatch.setattr("builtins.open", lambda p, *a, **kw: _real_open(str(cgroup_file), *a, **kw) if p == "/proc/1/cgroup" else _real_open(p, *a, **kw))
        assert is_container() is False

    def test_caches_result(self, monkeypatch):
        """Second call uses cached value without re-probing."""
        monkeypatch.setattr(hermes_constants, "_container_detected", True)
        assert is_container() is True
        # Even if we make os.path.exists return False, cached value wins
        monkeypatch.setattr(os.path, "exists", lambda p: False)
        assert is_container() is True
