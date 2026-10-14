"""PAGDOC document requirement policy engine.

Pure domain logic used to calculate expiry, warning states and internal alert
plans. It performs no messaging and contains no personal data.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Iterable, Literal

SubjectType = Literal["worker", "vehicle", "company", "project"]
DocumentState = Literal["valid", "expiring", "expired", "no_date"]


class RequirementError(ValueError):
    pass


@dataclass(frozen=True)
class RequirementPolicy:
    name: str
    subject_type: SubjectType
    warning_days: int = 30
    validity_days: int | None = None
    required: bool = True

    def __post_init__(self):
        if not self.name.strip():
            raise RequirementError("Requirement name is required")
        if self.warning_days < 0 or self.warning_days > 3650:
            raise RequirementError("warning_days must be between 0 and 3650")
        if self.validity_days is not None and not 1 <= self.validity_days <= 36500:
            raise RequirementError("validity_days must be between 1 and 36500")
        if self.subject_type not in {"worker", "vehicle", "company", "project"}:
            raise RequirementError("Unsupported subject_type")


@dataclass(frozen=True)
class DocumentFact:
    document_id: int
    subject_type: SubjectType
    subject_name: str
    issued_on: date | None = None
    expires_on: date | None = None


@dataclass(frozen=True)
class Evaluation:
    document_id: int
    state: DocumentState
    expires_on: date | None
    days_remaining: int | None
    warning_days: int


@dataclass(frozen=True)
class AlertEvent:
    document_id: int
    subject_name: str
    state: Literal["expiring", "expired"]
    due_on: date
    days_remaining: int


def derive_expiry(policy: RequirementPolicy, doc: DocumentFact) -> date | None:
    if doc.subject_type != policy.subject_type:
        raise RequirementError("Document subject type does not match requirement")
    if doc.expires_on is not None:
        return doc.expires_on
    if policy.validity_days is not None and doc.issued_on is not None:
        return doc.issued_on + timedelta(days=policy.validity_days)
    return None


def evaluate(policy: RequirementPolicy, doc: DocumentFact, today: date | None = None) -> Evaluation:
    current = today or date.today()
    expiry = derive_expiry(policy, doc)
    if expiry is None:
        return Evaluation(doc.document_id, "no_date", None, None, policy.warning_days)
    remaining = (expiry - current).days
    if remaining < 0:
        state: DocumentState = "expired"
    elif remaining <= policy.warning_days:
        state = "expiring"
    else:
        state = "valid"
    return Evaluation(doc.document_id, state, expiry, remaining, policy.warning_days)


def plan_alerts(
    pairs: Iterable[tuple[RequirementPolicy, DocumentFact]],
    today: date | None = None,
) -> list[AlertEvent]:
    current = today or date.today()
    events: list[AlertEvent] = []
    for policy, doc in pairs:
        result = evaluate(policy, doc, current)
        if result.state not in {"expiring", "expired"} or result.expires_on is None:
            continue
        events.append(
            AlertEvent(
                document_id=doc.document_id,
                subject_name=doc.subject_name,
                state=result.state,
                due_on=result.expires_on,
                days_remaining=result.days_remaining or 0,
            )
        )
    return sorted(events, key=lambda event: (event.due_on, event.document_id))
