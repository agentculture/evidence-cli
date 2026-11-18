"""stdout / stderr helpers with a strict split (stable-contract).

Rule: **results go to stdout, diagnostics and errors go to stderr.** Agents
parsing output can rely on this invariant. JSON mode routes structured
payloads to the same streams — never mixes them.
"""

from __future__ import annotations

import json
import sys
from typing import Any, TextIO

from evidence.cli._errors import CliError


def _encodable(text: str) -> bool:
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def emit_result(data: Any, *, json_mode: bool, stream: TextIO | None = None) -> None:
    """Write a command result to stdout (or ``stream``).

    An input file may hold a lone surrogate (a ``\\ud800`` JSON escape), which no
    UTF-8 stream can write: JSON is then written with that character escaped,
    and text with it as a backslash escape, instead of failing.
    """
    s = stream if stream is not None else sys.stdout
    if json_mode:
        text = json.dumps(data, ensure_ascii=False)
        s.write((text if _encodable(text) else json.dumps(data)) + "\n")
        return
    text = data if isinstance(data, str) else str(data)
    if not _encodable(text):
        text = text.encode("utf-8", "backslashreplace").decode("utf-8")
    s.write(text)
    if not text.endswith("\n"):
        s.write("\n")


def emit_error(err: CliError, *, json_mode: bool, stream: TextIO | None = None) -> None:
    """Write a :class:`CliError` to stderr.

    Text mode renders as two lines when a remediation is present::

        error: <message>
        hint: <remediation>

    The ``hint:`` prefix is required by the agent-first error rubric.
    """
    s = stream if stream is not None else sys.stderr
    if json_mode:
        json.dump(err.to_dict(), s, ensure_ascii=False)
        s.write("\n")
        return
    s.write(f"error: {err.message}\n")
    if err.remediation:
        s.write(f"hint: {err.remediation}\n")


def emit_diagnostic(message: str, *, stream: TextIO | None = None) -> None:
    """Write a human diagnostic (progress, summary) to stderr."""
    s = stream if stream is not None else sys.stderr
    s.write(message if message.endswith("\n") else message + "\n")
