"""``evidence learn`` — the learnability affordance.

Prints a structured self-teaching prompt. Must satisfy the agent-first rubric:
>=200 chars and mention purpose, command map, exit codes, --json, and explain.
"""

from __future__ import annotations

import argparse

from evidence import __version__
from evidence.cli._output import emit_result

_TEXT = """\
evidence-cli — checks the evidence around an agent run, and an answer against expected values.

Purpose
-------
Two separate checks, both deterministic, with no model call and no network call.
The run check re-reads a run export (the calls a run made, the results it saved,
the facts it handed back) and counts the facts whose quote is found in the saved
result they cite. The answer check matches an answer text against recorded
expected values. Neither result is folded into the other.

Commands
--------
  evidence whoami             Identity from culture.yaml.
  evidence learn              This self-teaching prompt.
  evidence explain <path>...  Markdown docs for any noun/verb path.
  evidence overview           Descriptive snapshot of the agent.
  evidence doctor             Check the agent-identity invariants.
  evidence cli overview       Describe the CLI surface itself.
  evidence check <export>...  Run check: counts of checked quotes and backed
                                  conclusions for run exports.
  evidence grade              Answer check: a match against recorded expected
                                  values (--answer-file, --expected).

Both results carry one line: a complete trail does not mean the work is correct.

Machine-readable output
-----------------------
Every command supports --json. Errors in JSON mode emit
{"code", "message", "remediation"} to stderr. Stdout and stderr never mix.

Exit-code policy
----------------
  0 success
  1 user-input error (bad flag, bad path, missing arg)
  2 environment / setup error
  3+ reserved

More detail
-----------
  evidence explain evidence
"""


def _as_json_payload() -> dict[str, object]:
    return {
        "tool": "evidence-cli",
        "version": __version__,
        "purpose": (
            "Checks the evidence around an agent run (quotes found in saved results) and, "
            "separately, an answer against recorded expected values."
        ),
        "commands": [
            {"path": ["whoami"], "summary": "Identity probe from culture.yaml."},
            {"path": ["learn"], "summary": "Self-teaching prompt."},
            {"path": ["explain"], "summary": "Markdown docs by path."},
            {"path": ["overview"], "summary": "Descriptive snapshot of the agent."},
            {"path": ["doctor"], "summary": "Check the agent-identity invariants."},
            {"path": ["cli", "overview"], "summary": "Describe the CLI surface."},
            {
                "path": ["check"],
                "summary": "Run check: counts of checked quotes and backed conclusions.",
            },
            {
                "path": ["grade"],
                "summary": "Answer check: a match against recorded expected values.",
            },
        ],
        "exit_codes": {
            "0": "success",
            "1": "user-input error",
            "2": "environment/setup error",
        },
        "json_support": True,
        "explain_pointer": "evidence explain <path>",
    }


def cmd_learn(args: argparse.Namespace) -> int:
    if getattr(args, "json", False):
        emit_result(_as_json_payload(), json_mode=True)
    else:
        emit_result(_TEXT, json_mode=False)
    return 0


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "learn",
        help="Print a structured self-teaching prompt for agent consumers.",
    )
    p.add_argument("--json", action="store_true", help="Emit structured JSON.")
    p.set_defaults(func=cmd_learn)
