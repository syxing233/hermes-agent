import importlib
import tomllib
from pathlib import Path


def test_pyproject_includes_compliance_agent_package():
    data = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    include = data["tool"]["setuptools"]["packages"]["find"]["include"]

    assert "compliance_agent" in include
    assert "compliance_agent.*" in include


def test_embedded_and_standalone_import_paths_work():
    assert importlib.import_module("compliance_agent.hermes.runtime") is not None
    assert importlib.import_module("compliance_agent.standalone.assistant_service") is not None
