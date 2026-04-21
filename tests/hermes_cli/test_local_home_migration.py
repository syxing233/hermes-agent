"""Tests for project-local legacy Hermes-home migration."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import yaml


def _load_migration_module():
    module_path = Path(__file__).resolve().parents[2] / "scripts" / "migrate_global_hermes_home.py"
    spec = importlib.util.spec_from_file_location("migrate_global_hermes_home", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_migration_merges_config_and_env_and_archives_runtime(tmp_path):
    module = _load_migration_module()
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()

    (source / "config.yaml").write_text(
        yaml.safe_dump(
            {
                "model": {"default": "source-model", "provider": "source-provider"},
                "agent": {"max_turns": 30},
                "compliance": {"workflow_base_url": "https://legacy.example/v1"},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (target / "config.yaml").write_text(
        yaml.safe_dump(
            {
                "model": {"default": "target-model"},
                "agent": {"max_turns": 90},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (source / ".env").write_text("SOURCE_ONLY=1\nSHARED=legacy\n", encoding="utf-8")
    (target / ".env").write_text("SHARED=target\nTARGET_ONLY=1\n", encoding="utf-8")
    (source / "SOUL.md").write_text("legacy soul", encoding="utf-8")
    (source / "skills").mkdir()
    (source / "skills" / "foo.txt").write_text("skill", encoding="utf-8")
    (source / "sessions").mkdir()
    (source / "sessions" / "session.json").write_text("{}", encoding="utf-8")
    (source / "state.db").write_text("db", encoding="utf-8")

    actions = module.migrate(source, target, dry_run=False, delete_source=False)

    merged = yaml.safe_load((target / "config.yaml").read_text(encoding="utf-8"))
    assert merged["model"]["default"] == "target-model"
    assert merged["model"]["provider"] == "source-provider"
    assert merged["agent"]["max_turns"] == 90
    assert merged["compliance"]["workflow_base_url"] == "https://legacy.example/v1"

    env_text = (target / ".env").read_text(encoding="utf-8")
    assert "TARGET_ONLY=1" in env_text
    assert "SHARED=target" in env_text
    assert "SOURCE_ONLY=1" in env_text

    assert (target / "SOUL.md").read_text(encoding="utf-8") == "legacy soul"
    assert (target / "skills" / "foo.txt").read_text(encoding="utf-8") == "skill"
    backup_root = target / "migration" / "global-hermes-backup"
    archived_sessions = list(backup_root.glob("*/sessions/session.json"))
    assert archived_sessions
    archived_state = list(backup_root.glob("*/state.db"))
    assert archived_state
    assert any("merged config.yaml" in action for action in actions)


def test_migration_delete_source_removes_legacy_tree(tmp_path):
    module = _load_migration_module()
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()
    (source / "config.yaml").write_text("model:\n  default: legacy\n", encoding="utf-8")

    module.migrate(source, target, dry_run=False, delete_source=True)

    assert not source.exists()


def test_migration_dry_run_is_non_mutating(tmp_path):
    module = _load_migration_module()
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()
    (source / "config.yaml").write_text("model:\n  default: legacy\n", encoding="utf-8")

    actions = module.migrate(source, target, dry_run=True, delete_source=True)

    assert source.exists()
    assert not (target / "config.yaml").exists()
    assert any(action.startswith("merge YAML") or action.startswith("copy") for action in actions)
    assert any(action.startswith("delete source tree") for action in actions)
