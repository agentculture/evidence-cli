"""A strict fact's pointer (``at``) into a saved result, and the number rule.

The harness, not the model, copies the evidence: ``at`` names ``lines: [first,
last]`` or a ``search`` term, and the lines it names are copied byte for byte
from the saved result. The rules are those of associate's
``docs/notes/strict-vectors.md`` (steps 2 and 4):

* the saved text is split on ``\\n``; a trailing ``\\n`` makes no empty last
  line, an empty text has no lines, and ``\\r`` stays in its line;
* lines count from 1 at the first line of the saved text, except that a read
  result whose first line starts with digits and a tab is counted by the line
  stamps it shows;
* on a ``partial`` (cut) result, missing lines and evidence that includes the
  last kept line are ``result_cut``.

Pure and standard library only.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping, Optional

from evidence.accuracy.command import READ_TOOLS, js_trim

# re.ASCII: \d is 0-9 only, as in associate's TypeScript.
_STAMP = re.compile(r"^(\d+)\t", re.ASCII)
_NUMBER = re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?", re.ASCII)
#: The only saved result names a pointer reads, as in the extension (``results/wN.txt``).
SAVED_NAME = re.compile(r"results/w[1-9][0-9]*\.txt", re.ASCII)  # used with fullmatch


@dataclass(frozen=True)
class Located:
    """The copied evidence: the quote and the first and last line in the pointer's count."""

    quote: str
    first: int
    last: int


def split_lines(text: str) -> list[str]:
    """Lines of a saved text: split on ``\\n``, no empty last line for a trailing ``\\n``."""
    if text == "":
        return []
    lines = text.split("\n")
    if lines[-1] == "":
        lines.pop()
    return lines


def _whole(value: Any) -> Optional[int]:
    """A whole number as an int (2.0 counts as 2), else None; a boolean is not a number."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None


def valid_lines(value: Any) -> Optional[tuple[int, int]]:
    """``[first, last]`` as two whole numbers with ``1 <= first <= last``, else None."""
    if not isinstance(value, list) or len(value) != 2:
        return None
    first, last = _whole(value[0]), _whole(value[1])
    if first is None or last is None or not 1 <= first <= last:
        return None
    return first, last


def valid_search(value: Any) -> bool:
    return isinstance(value, str) and js_trim(value) != ""


def pointer_shape_ok(at: Any) -> bool:
    """The shape rule: an object with exactly one key, a valid ``lines`` or ``search``."""
    if not isinstance(at, dict) or len(at) != 1:
        return False
    if "lines" in at:
        return valid_lines(at["lines"]) is not None
    return "search" in at and valid_search(at["search"])


def _stamps(tool: Any, lines: list[str]) -> Optional[list[Optional[str]]]:
    """Each line's shown stamp (its digits) for a stamped read result, else None (count from 1)."""
    if tool not in READ_TOOLS or not lines or not _STAMP.match(lines[0]):
        return None
    out: list[Optional[str]] = []
    for line in lines:
        found = _STAMP.match(line)
        out.append(found.group(1) if found else None)
    return out


@dataclass(frozen=True)
class _Text:
    lines: list[str]
    stamps: Optional[list[Optional[str]]]
    partial: bool

    def found_number(self, index: int) -> int:
        """The number a search reports: the found line's stamp, else its count from 1."""
        stamp = self.stamps[index] if self.stamps is not None else None
        return int(stamp) if stamp is not None else index + 1

    def index_of(self, number: int) -> Optional[int]:
        """The line a pointer number names: the first line stamped with exactly that number."""
        if self.stamps is None:
            return number - 1 if 1 <= number <= len(self.lines) else None
        return self.stamps.index(str(number)) if str(number) in self.stamps else None

    def missing_reason(self, last: int) -> str:
        """Why lines past what is shown fail: cut on a partial result, else out of range."""
        if not self.partial:
            return "pointer_out_of_range"
        if self.stamps is None:
            return "result_cut"
        shown = self.stamps[-1]
        return "result_cut" if shown is None or last > int(shown) else "pointer_out_of_range"


def _by_lines(
    text: _Text, first: int, last: int
) -> tuple[Optional[tuple[int, int, int, int]], str]:
    start, end = text.index_of(first), text.index_of(last)
    if start is None or end is None:
        return None, text.missing_reason(last)
    return (start, end, first, last), ""


def _by_search(text: _Text, term: str) -> tuple[Optional[tuple[int, int, int, int]], str]:
    for index, line in enumerate(text.lines):
        if term in line:
            number = text.found_number(index)
            return (index, index, number, number), ""
    return None, "result_cut" if text.partial else "search_not_found"


def resolve(
    at: Mapping[str, Any], saved_text: Optional[str], tool: Any, partial: bool
) -> tuple[Optional[Located], Optional[str]]:
    """The evidence a pointer copies, or the reason it does not resolve."""
    if saved_text is None:
        return None, "no_saved_result"
    lines_value, has_lines = at.get("lines"), "lines" in at
    if has_lines == ("search" in at):
        return None, "pointer_malformed"
    bounds = valid_lines(lines_value) if has_lines else None
    if (has_lines and bounds is None) or (not has_lines and not valid_search(at["search"])):
        return None, "pointer_malformed"
    lines = split_lines(saved_text)
    text = _Text(lines, _stamps(tool, lines), partial)
    span, reason = _by_lines(text, *bounds) if bounds else _by_search(text, at["search"])
    if span is None:
        return None, reason
    start, end, first, last = span
    if partial and end >= len(lines) - 1:
        return None, "result_cut"
    # Stamps out of order give end < start: the slice is then empty, as in the extension.
    quote = "\n".join(lines[start : end + 1])
    return Located(quote, first, last), None


def number_tokens(text: str) -> list[str]:
    """The number tokens of a text, commas removed, tried left to right."""
    return [token.replace(",", "") for token in _NUMBER.findall(text)]


def numbers_shown(value_text: str, evidence: str) -> bool:
    """The number rule: every number token of the value is a token of the evidence."""
    shown = set(number_tokens(evidence))
    return all(token in shown for token in number_tokens(value_text))
