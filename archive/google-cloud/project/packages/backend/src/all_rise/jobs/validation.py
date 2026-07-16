from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class SourceValidationIssue:
    item_key: str
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class SourceValidationReport:
    checked: int
    accepted: int
    issues: tuple[SourceValidationIssue, ...]

    @property
    def valid(self) -> bool:
        return not self.issues


def validate_source_records(
    records: Iterable[Mapping[str, Any]],
    *,
    identity_fields: Sequence[str],
    required_fields: Sequence[str],
) -> SourceValidationReport:
    """Validate required provider fields and reject duplicate stable identities."""
    seen: set[tuple[str, ...]] = set()
    issues: list[SourceValidationIssue] = []
    checked = 0
    accepted = 0
    for index, record in enumerate(records):
        checked += 1
        identity = tuple(str(record.get(field, "")) for field in identity_fields)
        item_key = ":".join(identity) or f"row-{index}"
        missing = [
            field
            for field in required_fields
            if record.get(field) is None or record.get(field) == ""
        ]
        if missing:
            issues.append(
                SourceValidationIssue(
                    item_key,
                    "missing_required_field",
                    f"missing: {', '.join(missing)}",
                )
            )
            continue
        if identity in seen:
            issues.append(
                SourceValidationIssue(item_key, "duplicate_identity", "duplicate source record")
            )
            continue
        seen.add(identity)
        accepted += 1
    return SourceValidationReport(checked, accepted, tuple(issues))
