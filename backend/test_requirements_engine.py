from datetime import date

import pytest

from requirements_engine import (
    DocumentFact,
    RequirementError,
    RequirementPolicy,
    derive_expiry,
    evaluate,
    plan_alerts,
)

TODAY = date(2026, 10, 13)


def test_explicit_expiry_wins_over_validity_rule():
    policy = RequirementPolicy("Examen", "worker", warning_days=30, validity_days=365)
    doc = DocumentFact(1, "worker", "Persona DEMO", issued_on=date(2026, 1, 1), expires_on=date(2027, 6, 1))
    assert derive_expiry(policy, doc) == date(2027, 6, 1)


def test_expiry_is_derived_from_issue_date():
    policy = RequirementPolicy("Inducción", "worker", warning_days=15, validity_days=90)
    doc = DocumentFact(2, "worker", "Persona DEMO", issued_on=date(2026, 10, 1))
    assert derive_expiry(policy, doc) == date(2026, 12, 30)


def test_no_date_when_no_expiry_rule_or_explicit_date():
    policy = RequirementPolicy("Contrato", "worker")
    doc = DocumentFact(3, "worker", "Persona DEMO")
    assert evaluate(policy, doc, TODAY).state == "no_date"


def test_valid_state_uses_configurable_warning_days():
    policy = RequirementPolicy("Seguro", "vehicle", warning_days=10)
    doc = DocumentFact(4, "vehicle", "Vehículo DEMO", expires_on=date(2026, 10, 24))
    result = evaluate(policy, doc, TODAY)
    assert result.state == "valid" and result.days_remaining == 11


def test_expiring_state_includes_boundary_day():
    policy = RequirementPolicy("Seguro", "vehicle", warning_days=10)
    doc = DocumentFact(5, "vehicle", "Vehículo DEMO", expires_on=date(2026, 10, 23))
    result = evaluate(policy, doc, TODAY)
    assert result.state == "expiring" and result.days_remaining == 10


def test_expired_state():
    policy = RequirementPolicy("Permiso", "vehicle", warning_days=30)
    doc = DocumentFact(6, "vehicle", "Vehículo DEMO", expires_on=date(2026, 10, 12))
    result = evaluate(policy, doc, TODAY)
    assert result.state == "expired" and result.days_remaining == -1


def test_subject_type_mismatch_is_rejected():
    policy = RequirementPolicy("Examen", "worker")
    doc = DocumentFact(7, "vehicle", "Vehículo DEMO")
    with pytest.raises(RequirementError):
        evaluate(policy, doc, TODAY)


@pytest.mark.parametrize("warning", [-1, 3651])
def test_invalid_warning_days_are_rejected(warning):
    with pytest.raises(RequirementError):
        RequirementPolicy("Prueba", "project", warning_days=warning)


@pytest.mark.parametrize("validity", [0, 36501])
def test_invalid_validity_days_are_rejected(validity):
    with pytest.raises(RequirementError):
        RequirementPolicy("Prueba", "company", validity_days=validity)


def test_alert_plan_returns_only_expiring_and_expired_sorted():
    policy = RequirementPolicy("Requisito", "project", warning_days=30)
    pairs = [
        (policy, DocumentFact(12, "project", "Proyecto B", expires_on=date(2026, 10, 20))),
        (policy, DocumentFact(10, "project", "Proyecto A", expires_on=date(2026, 9, 1))),
        (policy, DocumentFact(11, "project", "Proyecto C", expires_on=date(2027, 1, 1))),
    ]
    events = plan_alerts(pairs, TODAY)
    assert [event.document_id for event in events] == [10, 12]
    assert events[0].state == "expired"
    assert events[1].state == "expiring"


def test_requirement_policy_is_immutable():
    policy = RequirementPolicy("Documento", "company")
    with pytest.raises(Exception):
        policy.warning_days = 10
