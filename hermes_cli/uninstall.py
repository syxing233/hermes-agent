"""Project-local Hermes cleanup helpers.

This checkout keeps runtime state inside ``<repo>/.hermes-home`` and local
profile wrappers inside ``<repo>/bin``. The uninstall flow intentionally avoids
touching user-global shell config, LaunchAgents, systemd units, or any legacy
global Hermes home.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from hermes_bootstrap import get_project_wrapper_dir
from hermes_constants import get_hermes_home
from hermes_cli.colors import Colors, color


def log_info(msg: str) -> None:
    print(f"{color('→', Colors.CYAN)} {msg}")


def log_success(msg: str) -> None:
    print(f"{color('✓', Colors.GREEN)} {msg}")


def log_warn(msg: str) -> None:
    print(f"{color('⚠', Colors.YELLOW)} {msg}")


def get_project_root() -> Path:
    """Get the repository root for this checkout."""
    return Path(__file__).parent.parent.resolve()


def remove_local_wrappers(wrapper_dir: Path) -> list[Path]:
    """Remove generated profile wrappers from ``<repo>/bin``."""
    removed: list[Path] = []
    if not wrapper_dir.exists():
        return removed

    for entry in wrapper_dir.iterdir():
        if not entry.is_file():
            continue
        try:
            content = entry.read_text(encoding="utf-8")
        except OSError:
            continue
        if "run-hermes-local.sh" not in content or " -p " not in content:
            continue
        entry.unlink()
        removed.append(entry)
    return removed


def _confirm(prompt_text: str, *, auto_yes: bool = False) -> bool:
    if auto_yes:
        return True
    try:
        response = input(prompt_text).strip().lower()
    except (KeyboardInterrupt, EOFError):
        print()
        return False
    return response == "yes"


def run_uninstall(args) -> None:
    """Reset the project-local Hermes runtime state."""
    project_root = get_project_root()
    hermes_home = get_hermes_home()
    wrapper_dir = get_project_wrapper_dir()

    print()
    print(color("┌─────────────────────────────────────────────────────────┐", Colors.MAGENTA, Colors.BOLD))
    print(color("│          Hermes Agent Project-Local Cleanup            │", Colors.MAGENTA, Colors.BOLD))
    print(color("└─────────────────────────────────────────────────────────┘", Colors.MAGENTA, Colors.BOLD))
    print()
    print(color("This command only touches files inside this repository.", Colors.CYAN, Colors.BOLD))
    print(f"  Repo:    {project_root}")
    print(f"  State:   {hermes_home}")
    print(f"  Wrappers:{wrapper_dir}")
    print()
    print("Modes:")
    print("  1) Wrapper cleanup only     - remove generated profile wrappers from ./bin")
    print("  2) Full local reset         - remove .hermes-home and generated wrappers")
    print("  3) Cancel")
    print()

    auto_yes = bool(getattr(args, "yes", False))
    full_reset = bool(getattr(args, "full", False))
    choice = "2" if full_reset else None

    if choice is None and not auto_yes:
        try:
            choice = input(color("Select option [1/2/3]: ", Colors.BOLD)).strip()
        except (KeyboardInterrupt, EOFError):
            print()
            print("Cancelled.")
            return
    elif choice is None:
        choice = "2"

    if choice == "3":
        print()
        print("Cleanup cancelled.")
        return
    if choice not in {"1", "2"}:
        print()
        print("Cleanup cancelled.")
        return

    full_reset = choice == "2"
    print()
    if full_reset:
        print(color("This will delete the project-local Hermes state directory.", Colors.YELLOW, Colors.BOLD))
        print(f"  {hermes_home}")
    else:
        print("This will remove generated profile wrappers from the repository-local bin directory.")
    print()

    if not _confirm("Type 'yes' to confirm: ", auto_yes=auto_yes):
        print("Cleanup cancelled.")
        return

    removed_wrappers = remove_local_wrappers(wrapper_dir)
    if removed_wrappers:
        log_success(f"Removed {len(removed_wrappers)} local profile wrapper(s)")
    else:
        log_info("No generated profile wrappers found")

    if full_reset:
        if hermes_home.exists():
            shutil.rmtree(hermes_home)
            log_success(f"Removed project-local state: {hermes_home}")
        else:
            log_info("No project-local state directory found")
    else:
        log_info("Skipped project-local state removal")

    print()
    print("Repository files were left intact.")
