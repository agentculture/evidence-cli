"""The 0.7.0 release: version, changelog entry, and the wording of the project docs."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _read(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def test_version_is_0_7_0() -> None:
    assert re.search(r'^version = "0\.7\.0"$', _read("pyproject.toml"), re.MULTILINE)


def test_changelog_has_0_7_0_entry_naming_the_scaffold() -> None:
    text = _read("CHANGELOG.md")
    assert "## [0.7.0]" in text
    entry = text.split("## [0.7.0]")[1].split("## [0.6.1]")[0]
    assert "scaffold" in entry
    assert "266dad3" in entry


def test_claude_md_is_no_longer_a_seed() -> None:
    text = _read("CLAUDE.md")
    assert "Re-init instruction" not in text
    assert "/init" not in text


def test_claude_md_states_the_two_results_names_and_dependency_rule() -> None:
    text = _read("CLAUDE.md")
    assert "evidence check" in text
    assert "evidence grade" in text
    assert "docs/library.md" in text
    assert "breaking release" in text
    assert "dependencies = []" in text


def test_claude_md_has_no_home_paths_or_checkpoint_ids() -> None:
    text = _read("CLAUDE.md")
    assert "/home/" not in text
    assert "NVIDIA-Nemotron" not in text


def test_readme_names_both_commands_and_the_trail_line() -> None:
    text = _read("README.md")
    assert "evidence check" in text
    assert "evidence grade" in text
    assert "a complete trail does not mean the work is correct" in text
    assert "groundwork" in text
