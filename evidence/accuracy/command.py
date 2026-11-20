"""The command line printed beside a strict fact's copied evidence.

One line built from the walk entry the fact's source names; text the model
wrote about the command is never read. The rules are those of associate's
``docs/notes/strict-vectors.md`` ("The command"):

1. The arguments are ``args_used`` when it is an object, else ``args``, with the
   ``purpose`` key dropped.
2. Every string is rewritten: paths under the checkout (or its run worktrees)
   become relative, other home paths become ``~``, and the contract's
   redaction filter is applied. An object key is only redacted (a path in a
   key is not made relative), and the tool name gets the home rewrite and the
   redaction filter, not the checkout rewrite. A path match may start anywhere
   in a string; a path segment ends at a slash, whitespace, a quote or a
   backtick.
3. ``bash`` prints its ``argv``, a read tool prints its path and line range, and
   any other tool prints ``key=value`` pairs in the recorded key order (in
   ECMAScript property order: keys that are array indexes come first).

Standard library only; pure. A redaction pattern that starts with ``(?i)`` is
case-insensitive. Patterns are compiled with ``re.ASCII`` so that ``\\b`` and
``\\w`` see ASCII word characters only, as an ECMAScript regular expression
without the ``u`` flag does (``\\s`` is then ASCII whitespace only, which is
narrower than ECMAScript's).
"""

from __future__ import annotations

import json
import re
from typing import Any, Mapping, Optional

from evidence.accuracy.check import literal_of

#: The read tools whose path and line range are printed (and whose results carry line stamps).
READ_TOOLS = frozenset({"read", "read_file", "read_page", "readpage"})
_SAFE_TOKEN = re.compile(r"[A-Za-z0-9_@%+=:,./~-]+", re.ASCII)  # used with fullmatch
_WORKTREE_ROOT = re.compile(r"^(.*)/\.worktrees\.([^/]+)/[^/]+$")
_HOME = re.compile(r"(?:/home/[^/\s\"'`]+|/Users/[^/\s\"'`]+|/root)(?=[/\s\"'`]|$)")
_CASE_INSENSITIVE = "(?i)"
# re.ASCII: \d is 0-9 only, as an ECMAScript array index is.
_ARRAY_INDEX = re.compile(r"0|[1-9]\d*", re.ASCII)  # used with fullmatch
_MAX_ARRAY_INDEX = 2**32 - 2
#: ECMAScript String.prototype.trim's set: WhiteSpace and LineTerminator (not \x1c-\x1f, \x85).
_JS_TRIM = "".join(
    chr(code)
    for code in (
        *range(0x09, 0x0E),  # tab, line feed, vertical tab, form feed, carriage return
        0x20,
        0xA0,
        0x1680,
        *range(0x2000, 0x200B),
        0x2028,
        0x2029,
        0x202F,
        0x205F,
        0x3000,
        0xFEFF,
    )
)


def js_trim(text: str) -> str:
    """``text`` trimmed as ECMAScript ``String.prototype.trim`` trims it."""
    return text.strip(_JS_TRIM)


# --- paths ------------------------------------------------------------------------------


def _bases(checkout_root: str) -> Optional[tuple[str, str]]:
    """The checkout base and its worktrees directory, or None when the root is not absolute."""
    root = checkout_root.rstrip("/") if len(checkout_root) > 1 else checkout_root
    if not root.startswith("/") or root == "/":
        return None
    worktree = _WORKTREE_ROOT.match(root)
    base = f"{worktree.group(1)}/{worktree.group(2)}" if worktree else root
    parent, _, name = base.rpartition("/")
    return base, f"{parent}/.worktrees.{name}"


def _checkout_pattern(checkout_root: str) -> Optional[re.Pattern[str]]:
    """A match of a run worktree (one segment under the worktrees directory) or of the base."""
    bases = _bases(checkout_root)
    if bases is None:
        return None
    base, worktrees = bases
    head = f"(?:{re.escape(worktrees)}/[^/\\s\"'`]+|{re.escape(base)})"
    return re.compile(head + r"(?:(/)|(?![A-Za-z0-9_.-]))")


def _relative(pattern: Optional[re.Pattern[str]], text: str) -> str:
    """A match becomes ``.``; with its ``/``, nothing (``.`` before the end, a space, a quote)."""
    if pattern is None:
        return text

    def replace(match: re.Match[str]) -> str:
        if match.group(1) is None:
            return "."
        after = text[match.end() : match.end() + 1]
        return "." if after == "" or after.isspace() or after in "\"'`" else ""

    return pattern.sub(replace, text)


def compile_redaction(redaction: Mapping[str, Any]) -> list[re.Pattern[str]]:
    """The redaction filter's patterns compiled with Python ``re``.

    The patterns are written for ECMAScript; one Python cannot compile (an
    ECMAScript-only form such as a ``(?<name>...)`` group) raises ``ValueError``
    naming the pattern, rather than being dropped and leaving text unredacted.
    """
    patterns = []
    for source in redaction.get("patterns") or []:
        if not isinstance(source, str):
            continue
        body, flags = source, re.ASCII
        if body.startswith(_CASE_INSENSITIVE):
            body, flags = body[len(_CASE_INSENSITIVE) :], flags | re.IGNORECASE
        try:
            patterns.append(re.compile(body, flags))
        except re.error as err:
            raise ValueError(
                f"redaction pattern {source!r} cannot be compiled by Python re: {err}"
            ) from err
    return patterns


# --- JSON as ECMAScript writes it -----------------------------------------------------------


def _is_array_index(key: str) -> bool:
    return _ARRAY_INDEX.fullmatch(key) is not None and int(key) <= _MAX_ARRAY_INDEX


def js_items(value: Mapping[str, Any]) -> list[tuple[str, Any]]:
    """An object's entries in ECMAScript property order: array-index keys ascending, then others."""
    keys = [str(k) for k in value]
    indexes = sorted((k for k in keys if _is_array_index(k)), key=int)
    others = [k for k in keys if not _is_array_index(k)]
    return [(k, value[k]) for k in indexes + others]


def js_json(value: Any) -> str:
    """Compact JSON as ECMAScript ``JSON.stringify`` writes it (numbers as ``String(n)``)."""
    if isinstance(value, bool) or value is None:
        return json.dumps(value)
    if isinstance(value, (int, float)):
        return literal_of(value) or "null"
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, list):
        return "[" + ",".join(js_json(item) for item in value) + "]"
    if isinstance(value, dict):
        pairs = (f"{json.dumps(k, ensure_ascii=False)}:{js_json(v)}" for k, v in js_items(value))
        return "{" + ",".join(pairs) + "}"
    return "null"


def token(value: Any) -> str:
    """One printed token: a plain string as it is, any other string or value as JSON."""
    if isinstance(value, str) and _SAFE_TOKEN.fullmatch(value):
        return value
    return js_json(value)


# --- the rewrite and the line ------------------------------------------------------------------


class _Rewriter:
    """Rewrites one string: checkout paths, then home paths, then the redaction filter."""

    def __init__(self, checkout_root: str, redaction: Mapping[str, Any]) -> None:
        self.checkout = _checkout_pattern(checkout_root)
        self.patterns = compile_redaction(redaction)
        replacement = redaction.get("replacement")
        self.replacement = replacement if isinstance(replacement, str) else ""

    def redact(self, text: str) -> str:
        for pattern in self.patterns:
            text = pattern.sub(lambda _m: self.replacement, text)
        return text

    def text(self, text: str, checkout: bool = True) -> str:
        relative = _relative(self.checkout, text) if checkout else text
        return self.redact(_HOME.sub("~", relative))

    def value(self, value: Any) -> Any:
        if isinstance(value, str):
            return self.text(value)
        if isinstance(value, list):
            return [self.value(item) for item in value]
        if isinstance(value, dict):
            # An object key is redacted only, as the extension does (no path rewriting).
            out: dict[str, Any] = {}
            for key, item in js_items(value):
                out[self.redact(key)] = self.value(item)
            return out
        return value


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _bash_line(args: Mapping[str, Any]) -> Optional[str]:
    argv = args.get("argv")
    if not isinstance(argv, list) or not all(isinstance(t, str) for t in argv):
        return None
    line = " ".join(token(t) for t in argv)
    cwd = args.get("cwd")
    if isinstance(cwd, str) and js_trim(cwd) != "":
        line = f"cd {token(cwd)} && {line}"
    return line


def _read_line(tool: str, args: Mapping[str, Any]) -> Optional[str]:
    path = args.get("path")
    if not isinstance(path, str):
        return None
    line = f"{tool} {token(path)}"
    start, end = args.get("start_line"), args.get("end_line")
    if _is_number(start) or _is_number(end):
        first = js_json(start) if _is_number(start) else "1"
        last = js_json(end) if _is_number(end) else "end"
        line += f" lines {first}-{last}"
    return line


def _generic_line(tool: str, args: Mapping[str, Any]) -> str:
    pairs = [f"{key}={token(value)}" for key, value in js_items(args)]
    return " ".join([tool, *pairs])


def command_args(entry: Mapping[str, Any]) -> tuple[dict[str, Any], str]:
    """The arguments the command is built from, without ``purpose``, and their field name."""
    used = entry.get("args_used")
    if isinstance(used, dict):
        chosen, origin = used, "args_used"
    else:
        raw = entry.get("args")
        chosen, origin = (raw if isinstance(raw, dict) else {}), "args"
    return {k: v for k, v in chosen.items() if k != "purpose"}, origin


def render_command(
    entry: Mapping[str, Any], checkout_root: str, redaction: Mapping[str, Any]
) -> tuple[str, str]:
    """The printed command line for a walk entry and the field it came from.

    *checkout_root* is the absolute path of the checkout the run examined;
    *redaction* is ``{replacement, patterns}`` (associate's ``policy.json``
    ``redaction``).
    """
    rewriter = _Rewriter(checkout_root, redaction)
    raw_args, origin = command_args(entry)
    args = rewriter.value(raw_args)
    raw_tool = entry.get("tool")
    # The tool name gets the home rewrite and the redaction filter, not the checkout rewrite.
    tool = rewriter.text(raw_tool if isinstance(raw_tool, str) else "unknown", checkout=False)
    line = None
    if tool == "bash":
        line = _bash_line(args)
    elif tool in READ_TOOLS:
        line = _read_line(tool, args)
    return (line if line is not None else _generic_line(tool, args)), origin
