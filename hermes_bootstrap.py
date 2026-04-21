"""Import-safe bootstrap helpers for project-local Hermes runtime paths."""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path


PROJECT_STATE_DIRNAME = ".hermes-home"
_PROFILE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


def get_repo_root() -> Path:
    """Return the repository root for this Hermes checkout."""
    override = os.getenv("HERMES_PROJECT_ROOT", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return Path(__file__).resolve().parent


def get_project_hermes_home(repo_root: Path | None = None) -> Path:
    """Return the project-local Hermes home directory."""
    return (repo_root or get_repo_root()) / PROJECT_STATE_DIRNAME


def get_profiles_root(repo_root: Path | None = None) -> Path:
    """Return the project-local profiles directory."""
    return get_project_hermes_home(repo_root) / "profiles"


def get_project_wrapper_dir(repo_root: Path | None = None) -> Path:
    """Return the repository-local wrapper directory."""
    return (repo_root or get_repo_root()) / "bin"


def get_active_profile_path(repo_root: Path | None = None) -> Path:
    """Return the sticky active_profile marker path."""
    return get_project_hermes_home(repo_root) / "active_profile"


def get_profile_home(profile_name: str, repo_root: Path | None = None) -> Path:
    """Return the HERMES_HOME path for the requested project-local profile."""
    if profile_name == "default":
        return get_project_hermes_home(repo_root)
    return get_profiles_root(repo_root) / profile_name


def validate_profile_name(profile_name: str) -> None:
    """Validate a profile identifier."""
    if profile_name == "default":
        return
    if not _PROFILE_ID_RE.match(profile_name):
        raise ValueError(
            f"Invalid profile name {profile_name!r}. Must match "
            "[a-z0-9][a-z0-9_-]{0,63}"
        )


def _resolve_path(path: str | os.PathLike[str], repo_root: Path | None = None) -> Path:
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = (repo_root or get_repo_root()) / candidate
    return candidate.resolve()


def is_allowed_hermes_home(
    candidate: str | os.PathLike[str] | Path,
    repo_root: Path | None = None,
) -> bool:
    """Return True when *candidate* is inside the allowed project-local home set."""
    resolved = _resolve_path(candidate, repo_root)
    project_home = get_project_hermes_home(repo_root).resolve()
    if resolved == project_home:
        return True
    return resolved.parent == (project_home / "profiles").resolve()


def ensure_allowed_hermes_home(
    candidate: str | os.PathLike[str] | Path,
    repo_root: Path | None = None,
) -> Path:
    """Validate that *candidate* stays inside this checkout."""
    resolved = _resolve_path(candidate, repo_root)
    if not is_allowed_hermes_home(resolved, repo_root):
        project_home = get_project_hermes_home(repo_root).resolve()
        raise RuntimeError(
            "Project-local Hermes refuses HERMES_HOME outside this checkout. "
            f"Allowed paths are {project_home} or {project_home / 'profiles' / '<name>'}; "
            f"got {resolved}"
        )
    return resolved


def read_active_profile(repo_root: Path | None = None) -> str:
    """Read the sticky active profile marker from the project-local home."""
    active_path = get_active_profile_path(repo_root)
    try:
        name = active_path.read_text(encoding="utf-8").strip()
    except (FileNotFoundError, OSError, UnicodeDecodeError):
        return "default"
    return name or "default"


def _extract_profile_arg(argv: list[str]) -> str | None:
    for i, arg in enumerate(argv):
        if arg in ("--profile", "-p") and i + 1 < len(argv):
            return argv[i + 1]
        if arg.startswith("--profile="):
            return arg.split("=", 1)[1]
    return None


def strip_profile_args(argv: list[str]) -> list[str]:
    """Remove a single profile flag from argv."""
    stripped: list[str] = []
    skip_next = False
    for arg in argv:
        if skip_next:
            skip_next = False
            continue
        if arg in ("--profile", "-p"):
            skip_next = True
            continue
        if arg.startswith("--profile="):
            continue
        stripped.append(arg)
    return stripped


def resolve_local_hermes_home(
    *,
    profile_name: str | None = None,
    env_home: str | None = None,
    repo_root: Path | None = None,
) -> Path:
    """Resolve the effective project-local HERMES_HOME."""
    if profile_name is not None:
        validate_profile_name(profile_name)
        return get_profile_home(profile_name, repo_root).resolve()
    if env_home:
        return ensure_allowed_hermes_home(env_home, repo_root)

    active_profile = read_active_profile(repo_root)
    validate_profile_name(active_profile)
    return get_profile_home(active_profile, repo_root).resolve()


def bootstrap_local_hermes_home(
    *,
    argv: list[str] | None = None,
    mutate_sys_argv: bool = True,
    repo_root: Path | None = None,
) -> Path:
    """Resolve and export a project-local HERMES_HOME before Hermes imports."""
    root = repo_root or get_repo_root()
    current_home = os.environ.get("HERMES_HOME", "").strip() or None
    if current_home:
        ensure_allowed_hermes_home(current_home, root)

    arg_list = list(sys.argv[1:] if argv is None else argv)
    profile_name = _extract_profile_arg(arg_list)
    target_home = resolve_local_hermes_home(
        profile_name=profile_name,
        env_home=current_home,
        repo_root=root,
    )
    os.environ["HERMES_HOME"] = str(target_home)

    if profile_name is not None and mutate_sys_argv and argv is None:
        sys.argv = [sys.argv[0], *strip_profile_args(sys.argv[1:])]

    return target_home
