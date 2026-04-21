#!/usr/bin/env python3
"""Migrate a legacy global Hermes home tree into this checkout's .hermes-home."""

from __future__ import annotations

import argparse
import shutil
import sys
from datetime import datetime
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from hermes_bootstrap import get_project_hermes_home, get_repo_root


COPY_IF_MISSING = ("auth.json", "SOUL.md")
MERGE_DIRS = ("memories", "skills", "skins")
ARCHIVE_NAMES = (
    "sessions",
    "logs",
    "cron",
    "plans",
    "workspace",
    "sandboxes",
    "profiles",
    "state.db",
    "state.db-shm",
    "state.db-wal",
)


def _deep_fill_missing(target: dict, source: dict) -> dict:
    merged = dict(target)
    for key, value in source.items():
        if key not in merged:
            merged[key] = value
            continue
        existing = merged[key]
        if isinstance(existing, dict) and isinstance(value, dict):
            merged[key] = _deep_fill_missing(existing, value)
    return merged


def _read_yaml(path: Path) -> dict:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a YAML mapping")
    return data


def _write_yaml(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def _parse_env_assignments(path: Path) -> list[tuple[str, str]]:
    assignments: list[tuple[str, str]] = []
    if not path.exists():
        return assignments
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        assignments.append((key.strip(), value))
    return assignments


def _merge_env_file(source: Path, target: Path, *, dry_run: bool) -> str:
    source_items = _parse_env_assignments(source)
    if not target.exists():
        if dry_run:
            return f"copy {source} -> {target}"
        shutil.copy2(source, target)
        return f"copied {source.name}"

    target_text = target.read_text(encoding="utf-8", errors="replace")
    target_keys = {key for key, _ in _parse_env_assignments(target)}
    missing_lines = [f"{key}={value}" for key, value in source_items if key not in target_keys]
    if not missing_lines:
        return "env merge skipped (no missing keys)"
    if dry_run:
        return f"append {len(missing_lines)} env key(s) to {target}"

    suffix = "\n" if target_text and not target_text.endswith("\n") else ""
    target.write_text(
        target_text + suffix + "\n".join(missing_lines) + "\n",
        encoding="utf-8",
    )
    return f"appended {len(missing_lines)} env key(s)"


def _copy_missing_tree(source: Path, target: Path, *, dry_run: bool) -> list[str]:
    actions: list[str] = []
    if not source.exists():
        return actions
    if source.is_file():
        if target.exists():
            actions.append(f"skip existing file {target}")
        elif dry_run:
            actions.append(f"copy {source} -> {target}")
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            actions.append(f"copied {target}")
        return actions

    if not target.exists():
        if dry_run:
            actions.append(f"copy tree {source} -> {target}")
        else:
            shutil.copytree(source, target)
            actions.append(f"copied tree {target}")
        return actions

    for entry in sorted(source.iterdir()):
        actions.extend(_copy_missing_tree(entry, target / entry.name, dry_run=dry_run))
    return actions


def _unique_backup_path(path: Path) -> Path:
    if not path.exists():
        return path
    counter = 1
    while True:
        candidate = path.with_name(f"{path.name}-{counter}")
        if not candidate.exists():
            return candidate
        counter += 1


def _archive_entry(source: Path, backup_root: Path, *, dry_run: bool) -> str | None:
    if not source.exists():
        return None
    destination = _unique_backup_path(backup_root / source.name)
    if dry_run:
        return f"archive {source} -> {destination}"
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.is_dir():
        shutil.copytree(source, destination)
    else:
        shutil.copy2(source, destination)
    return f"archived {source.name}"


def migrate(source_root: Path, target_root: Path, *, dry_run: bool, delete_source: bool) -> list[str]:
    actions: list[str] = []
    if not source_root.exists():
        actions.append(f"source missing: {source_root}")
        return actions

    target_root.mkdir(parents=True, exist_ok=True)
    backup_root = target_root / "migration" / "global-hermes-backup" / datetime.now().strftime("%Y%m%d_%H%M%S")

    source_config = source_root / "config.yaml"
    target_config = target_root / "config.yaml"
    if source_config.exists():
        if target_config.exists():
            merged = _deep_fill_missing(_read_yaml(target_config), _read_yaml(source_config))
            if dry_run:
                actions.append(f"merge YAML {source_config} -> {target_config} (target wins)")
            else:
                _write_yaml(target_config, merged)
                actions.append("merged config.yaml")
        elif dry_run:
            actions.append(f"copy {source_config} -> {target_config}")
        else:
            shutil.copy2(source_config, target_config)
            actions.append("copied config.yaml")

    source_env = source_root / ".env"
    target_env = target_root / ".env"
    if source_env.exists():
        target_env.parent.mkdir(parents=True, exist_ok=True)
        actions.append(_merge_env_file(source_env, target_env, dry_run=dry_run))

    for name in COPY_IF_MISSING:
        actions.extend(_copy_missing_tree(source_root / name, target_root / name, dry_run=dry_run))

    for name in MERGE_DIRS:
        actions.extend(_copy_missing_tree(source_root / name, target_root / name, dry_run=dry_run))

    handled_names = {
        "config.yaml",
        ".env",
        *COPY_IF_MISSING,
        *MERGE_DIRS,
        *ARCHIVE_NAMES,
    }
    for name in ARCHIVE_NAMES:
        result = _archive_entry(source_root / name, backup_root, dry_run=dry_run)
        if result:
            actions.append(result)

    for entry in sorted(source_root.iterdir()):
        if entry.name in handled_names:
            continue
        result = _archive_entry(entry, backup_root, dry_run=dry_run)
        if result:
            actions.append(result)

    if delete_source:
        if dry_run:
            actions.append(f"delete source tree {source_root}")
        else:
            shutil.rmtree(source_root)
            actions.append(f"deleted {source_root}")

    return actions


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrate a legacy global Hermes home into this repository's .hermes-home")
    parser.add_argument("--source", type=Path, default=Path.home() / ".hermes", help="Source Hermes home")
    parser.add_argument("--target", type=Path, default=get_project_hermes_home(), help="Target project-local Hermes home")
    parser.add_argument("--dry-run", action="store_true", help="Print planned actions without modifying files")
    parser.add_argument("--delete-source", action="store_true", help="Delete the source tree after a successful migration")
    args = parser.parse_args()

    actions = migrate(
        args.source.expanduser().resolve(),
        args.target.expanduser().resolve(),
        dry_run=args.dry_run,
        delete_source=args.delete_source,
    )
    for action in actions:
        print(action)
    print(f"repo_root={get_repo_root()}")
    print(f"target_home={args.target.expanduser().resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
