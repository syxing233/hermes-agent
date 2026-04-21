from argparse import Namespace
from pathlib import Path

from hermes_cli.main import cmd_profile
from hermes_cli.profiles import create_profile, set_active_profile


def test_profile_list_prefers_sticky_active_marker_when_running_from_default_home(
    tmp_path,
    monkeypatch,
    capsys,
):
    repo_root = tmp_path / "repo"
    hermes_home = repo_root / ".hermes-home"
    hermes_home.mkdir(parents=True)

    monkeypatch.setenv("HERMES_PROJECT_ROOT", str(repo_root))
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    create_profile("compliance", no_alias=True)
    set_active_profile("compliance")

    cmd_profile(Namespace(profile_action="list"))
    out = capsys.readouterr().out

    assert "◆compliance" in out
    assert "◆default" not in out
