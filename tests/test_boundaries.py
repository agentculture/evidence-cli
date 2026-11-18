"""Boundary tests: no runtime dependency, no forbidden import, no final score, shipped data.

* ``pyproject.toml`` lists no runtime dependency, and a built wheel's metadata has none.
* No module under ``evidence/`` imports ``associate``, a network library or ``subprocess``.
* No registered command prints the words "final score" or "quality score".
* The bundled data files are the byte copies of associate at commit 266dad3 and ship in the wheel.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import shutil
import subprocess
import tempfile
import tomllib
import zipfile
from pathlib import Path

import pytest

from evidence.cli import _build_parser, main
from evidence.explain import known_paths

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = ROOT / "evidence"
FORBIDDEN_ROOTS = frozenset({"associate", "socket", "urllib", "http", "ssl", "subprocess"})
FORBIDDEN_PHRASES = ("final score", "quality score")
FIXTURES = Path(__file__).parent / "fixtures" / "answer"

#: sha256 of the bundled files, equal to associate/contract/ at commit 266dad3.
DATA_SHA256 = {
    "matcher_vectors.json": "92a6491e0d3417b49baf20de628184cc27703789697a63c711ae1e2088e9fef1",
    "accuracy_defaults.json": "b44bd3678b2cf08df1e63b3036e4452599b7803699609e377f6532eb2488c374",
}
WHEEL_DATA = (
    "evidence/data/matcher_vectors.json",
    "evidence/data/accuracy_defaults.json",
    "evidence/data/expected_values.schema.json",
)


# --- no runtime dependency ---------------------------------------------------------


def test_pyproject_declares_no_runtime_dependency():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text("utf-8"))["project"]
    assert project["dependencies"] == []
    assert not project.get("optional-dependencies")
    assert "dynamic" not in project or "dependencies" not in project["dynamic"]


@pytest.mark.skipif(shutil.which("uv") is None, reason="uv is not available to build the wheel")
def test_the_built_wheel_carries_the_data_files_and_requires_nothing():
    with tempfile.TemporaryDirectory() as out:
        # B603/B607: fixed argv; uv is the project's own build tool.
        build = subprocess.run(  # noqa: S603  # nosec B603 B607
            ["uv", "build", "--wheel", "-o", out, str(ROOT)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert build.returncode == 0, build.stderr
        (wheel,) = Path(out).glob("*.whl")
        with zipfile.ZipFile(wheel) as zf:
            names = set(zf.namelist())
            (metadata_name,) = [n for n in names if n.endswith(".dist-info/METADATA")]
            metadata = zf.read(metadata_name).decode("utf-8")
    assert set(WHEEL_DATA) <= names
    assert not [ln for ln in metadata.splitlines() if ln.startswith("Requires-Dist")]


def test_the_bundled_data_files_are_byte_copies_of_associate_at_266dad3():
    for name, expected in DATA_SHA256.items():
        data = (PACKAGE / "data" / name).read_bytes()
        assert hashlib.sha256(data).hexdigest() == expected, name


# --- no forbidden import -----------------------------------------------------------


def imported_roots(tree: ast.AST) -> set[str]:
    """Top-level names a module imports, by statement or by a literal dynamic import."""
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])
        elif isinstance(node, ast.Call):
            roots.update(dynamic_import_roots(node))
    return roots


def dynamic_import_roots(call: ast.Call) -> set[str]:
    func = call.func
    name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
    if name not in {"__import__", "import_module"} or not call.args:
        return set()
    arg = call.args[0]
    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
        return {arg.value.split(".")[0]}
    return set()


def forbidden_imports(package: Path) -> dict[str, set[str]]:
    found: dict[str, set[str]] = {}
    for path in sorted(package.rglob("*.py")):
        bad = imported_roots(ast.parse(path.read_text("utf-8"))) & FORBIDDEN_ROOTS
        if bad:
            found[str(path.relative_to(package.parent))] = bad
    return found


def test_the_scan_finds_a_forbidden_import_when_one_exists(tmp_path):
    (tmp_path / "bad.py").write_text(
        "import subprocess\nfrom urllib.request import urlopen\n"
        "import importlib\nimportlib.import_module('associate.cli')\n"
    )
    (tmp_path / "ok.py").write_text("import json\nfrom pathlib import Path\n")
    key = f"{tmp_path.name}/bad.py"
    assert forbidden_imports(tmp_path) == {key: {"subprocess", "urllib", "associate"}}


def test_no_module_under_evidence_imports_associate_a_network_library_or_subprocess():
    assert len(list(PACKAGE.rglob("*.py"))) > 10
    assert forbidden_imports(PACKAGE) == {}


# --- no command prints a final score -----------------------------------------------


def leaf_paths(parser: argparse.ArgumentParser, prefix: tuple[str, ...] = ()) -> list[tuple]:
    """Every registered command path, read from the parser (so a new verb is covered)."""
    groups = [a for a in parser._actions if isinstance(a, argparse._SubParsersAction)]
    if not groups:
        return [prefix]
    paths: list[tuple[str, ...]] = []
    for group in groups:
        for name, sub in group.choices.items():
            paths.extend(leaf_paths(sub, (*prefix, name)))
    return paths


def arguments_for(path: tuple[str, ...], tmp_path: Path) -> list[str]:
    """Inputs for the verbs that need them; every other verb runs bare."""
    task = FIXTURES / "count-tests"
    if path == ("check",):
        return ["--no-flags", str(make_export_dir(tmp_path))]
    if path == ("grade",):
        answer, expected = task / "answer.txt", task / "expected.json"
        return ["--answer-file", str(answer), "--expected", str(expected)]
    return []


def make_export_dir(tmp_path: Path) -> Path:
    from tests.test_check_command import QUOTE_1, make_export

    return make_export(tmp_path / "runs" / "a" / "export", [QUOTE_1, "an absent quote here"])


def assert_no_score(text: str, label: str) -> None:
    lowered = text.lower()
    for phrase in FORBIDDEN_PHRASES:
        assert phrase not in lowered, f"{label} prints {phrase!r}"


def test_the_enumeration_finds_every_registered_verb():
    paths = leaf_paths(_build_parser())
    assert {("check",), ("grade",), ("whoami",), ("cli", "overview")} <= set(paths)


@pytest.mark.parametrize("json_mode", [False, True])
def test_no_command_prints_a_final_score(capsys, tmp_path, json_mode):
    flag = ["--json"] if json_mode else []
    for path in leaf_paths(_build_parser()):
        argv = [*path, *arguments_for(path, tmp_path), *flag]
        code = main(argv)
        out = capsys.readouterr()
        assert code in (0, 1, 2), (argv, code)  # doctor may report a failed invariant
        assert out.out.strip(), f"{argv} printed nothing"
        assert_no_score(out.out + out.err, " ".join(argv))


def test_no_explain_entry_and_no_help_text_says_final_score(capsys):
    for path in known_paths():
        main(["explain", *path])
        assert_no_score(capsys.readouterr().out, f"explain {path}")
    for path in leaf_paths(_build_parser()):
        with pytest.raises(SystemExit):
            main([*path, "--help"])
        assert_no_score(capsys.readouterr().out, f"{path} --help")
    with pytest.raises(SystemExit):
        main(["--help"])
    assert_no_score(capsys.readouterr().out, "--help")


def test_the_scoring_check_can_fail():
    with pytest.raises(AssertionError):
        assert_no_score("The Final Score is 7", "sample")
