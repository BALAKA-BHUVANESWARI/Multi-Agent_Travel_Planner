"""What an evaluator returns.

A case tests one of two things, and the report never mixes them:
* ``planner``: does the application give a right result?
* ``self_check``: does the evaluator itself find the mistakes planted in made-up data?
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

PASSED, FAILED, NOT_SUPPORTED, NOT_RUN, ERROR = "passed", "failed", "not_supported", "not_run", "error"
STATUSES = (PASSED, FAILED, NOT_SUPPORTED, NOT_RUN, ERROR)
FAIL, WARN, INFO = "fail", "warn", "not_checked"       # how serious one finding is


@dataclass(frozen=True)
class Finding:
    code: str
    severity: str              # fail (hard failure) | warn | not_checked
    message: str


@dataclass
class Result:
    status: str
    failures: list[str] = field(default_factory=list)      # why the case failed, or why it was not supported
    findings: list[Finding] = field(default_factory=list)  # what was seen in the output, warnings included
    measured: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return asdict(self)


def outcome(failures: list[str], findings: list[Finding] | None = None, measured: dict | None = None) -> Result:
    return Result(FAILED if failures else PASSED, failures, findings or [], measured or {})
