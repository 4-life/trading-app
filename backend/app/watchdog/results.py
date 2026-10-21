from dataclasses import dataclass


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str
