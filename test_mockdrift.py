"""Tests for MockDrift core engine — schema validation, cassette checks, SARIF."""
import json
import os
import time

import pytest
import yaml

from mockdrift_core import MockDriftDetector, to_sarif

SPEC = {
    "openapi": "3.0.0",
    "info": {"title": "Test API", "version": "1.0"},
    "paths": {
        "/users": {"get": {"responses": {"200": {"description": "ok", "content": {
            "application/json": {"schema": {
                "type": "array",
                "items": {"$ref": "#/components/schemas/User"}}}}}}}},
        "/users/{id}": {"get": {"responses": {"200": {"description": "ok",
            "content": {"application/json": {
                "schema": {"$ref": "#/components/schemas/User"}}}}}}},
    },
    "components": {"schemas": {"User": {
        "type": "object", "required": ["id", "email"],
        "properties": {"id": {"type": "integer"},
                       "email": {"type": "string"},
                       "name": {"type": "string"}}}}},
}


@pytest.fixture
def detector(tmp_path):
    p = tmp_path / "spec.json"
    p.write_text(json.dumps(SPEC))
    return MockDriftDetector(str(p))


def test_valid_mock_no_drift(detector):
    """Mock matching the schema should report zero drift."""
    report = detector.check_mock(
        "users_list", [{"id": 1, "email": "a@b.com"}], "/users")
    assert not report.drifted
    assert report.errors == []


def test_missing_required_field_drifts(detector):
    """Mock missing required fields must be flagged."""
    report = detector.check_mock("bad", [{"name": "Alice"}], "/users")
    assert report.drifted
    assert any("id" in e or "email" in e for e in report.errors)


def test_wrong_type_drifts(detector):
    """Mock with wrong value types must be flagged."""
    report = detector.check_mock(
        "type_err", {"id": "NaN", "email": "x@y.com"}, "/users/{id}")
    assert report.drifted
    assert len(report.errors) >= 1


def test_unknown_path_reports_no_schema(detector):
    """Checking a path absent from spec should report a clear error."""
    report = detector.check_mock("ghost", {"x": 1}, "/orders")
    assert report.drifted
    assert "No schema" in report.errors[0]


def test_sarif_output_structure(detector):
    """SARIF output must contain drifted results with correct rule IDs."""
    r = detector.check_mock("bad", [{"name": "x"}], "/users")
    sarif = to_sarif([r])
    assert sarif["version"] == "2.1.0"
    results = sarif["runs"][0]["results"]
    assert len(results) >= 1
    assert results[0]["ruleId"] == "mockdrift/schema-drift"


def test_cassette_age_triggers_drift(detector, tmp_path):
    """Cassette older than max_age_days must be flagged as stale."""
    cassette = {"interactions": [{"request": {
        "uri": "https://api.test/users", "method": "GET"},
        "response": {"status": {"code": 200},
                     "body": {"string": json.dumps(
                         [{"id": 1, "email": "a@b.com"}])}}}]}
    p = tmp_path / "old.yaml"
    p.write_text(yaml.dump(cassette))
    old_ts = time.time() - 90 * 86400
    os.utime(str(p), (old_ts, old_ts))
    reports = detector.check_cassette(str(p), max_age_days=30)
    assert len(reports) == 1
    assert reports[0].drifted
    assert any("age" in e.lower() for e in reports[0].errors)


def test_fresh_cassette_no_age_drift(detector, tmp_path):
    """Fresh cassette within max_age should not trigger age drift."""
    cassette = {"interactions": [{"request": {
        "uri": "https://api.test/users", "method": "GET"},
        "response": {"status": {"code": 200},
                     "body": {"string": json.dumps(
                         [{"id": 2, "email": "b@c.com"}])}}}]}
    p = tmp_path / "fresh.yaml"
    p.write_text(yaml.dump(cassette))
    reports = detector.check_cassette(str(p), max_age_days=9999)
    assert len(reports) == 1
    assert not any("age" in e.lower() for e in reports[0].errors)


def test_report_to_dict_roundtrip(detector):
    """DriftReport.to_dict must contain all required keys."""
    r = detector.check_mock("m", {"id": 1, "email": "x@y"}, "/users/{id}")
    d = r.to_dict()
    assert d["name"] == "m"
    assert d["drifted"] is False
    assert d["method"] == "get"
    assert d["path"] == "/users/{id}"
    assert isinstance(d["errors"], list)
