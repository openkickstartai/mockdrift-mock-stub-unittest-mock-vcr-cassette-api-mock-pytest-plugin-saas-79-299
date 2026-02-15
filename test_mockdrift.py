"""Tests for MockDrift core engine — schema validation, cassette checks, SARIF."""
import json
import os
import time

import pytest
import yaml

from mockdrift_core import MockDriftDetector, VCRCassetteDriftChecker, DriftResult, to_sarif


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


# ---------------------------------------------------------------------------
# VCR Cassette Drift Tests
# ---------------------------------------------------------------------------

FIXTURES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


@pytest.fixture
def checker(tmp_path):
    """VCRCassetteDriftChecker wired to our test spec."""
    p = tmp_path / "spec.json"
    p.write_text(json.dumps(SPEC))
    return VCRCassetteDriftChecker(str(p))


def test_vcr_cassette_valid_no_drift(checker):
    """(a) Cassette whose response exactly matches the schema — no drift."""
    path = os.path.join(FIXTURES_DIR, "cassette_valid.yaml")
    results = checker.check(path)
    assert len(results) == 1
    r = results[0]
    assert not r.drifted
    assert r.errors == []
    assert r.cassette_file == "cassette_valid.yaml"
    assert r.interaction_index == 0
    assert r.path == "/users/{id}"
    assert r.method == "get"
    assert r.status_code == "200"
    assert r.actual_keys_diff == {}


def test_vcr_cassette_extra_fields_drift(checker):
    """(b) Cassette with extra fields not in the schema — should drift."""
    path = os.path.join(FIXTURES_DIR, "cassette_extra_fields.yaml")
    results = checker.check(path)
    assert len(results) == 1
    r = results[0]
    assert r.drifted
    assert r.cassette_file == "cassette_extra_fields.yaml"
    assert r.interaction_index == 0
    assert "extra" in r.actual_keys_diff
    assert "role" in r.actual_keys_diff["extra"]
    assert "avatar_url" in r.actual_keys_diff["extra"]
    # jsonschema errors should mention additional properties
    assert len(r.errors) > 0


def test_vcr_cassette_missing_required_drift(checker):
    """(c) Cassette missing required fields — should drift."""
    path = os.path.join(FIXTURES_DIR, "cassette_missing_required.yaml")
    results = checker.check(path)
    assert len(results) == 1
    r = results[0]
    assert r.drifted
    assert r.cassette_file == "cassette_missing_required.yaml"
    assert r.interaction_index == 0
    assert "missing" in r.actual_keys_diff
    assert "id" in r.actual_keys_diff["missing"]
    assert "email" in r.actual_keys_diff["missing"]
    # jsonschema must flag missing required props
    assert any("id" in e or "email" in e for e in r.errors)


def test_vcr_cassette_wrong_type_drift(checker):
    """(d) Cassette with wrong value types — should drift."""
    path = os.path.join(FIXTURES_DIR, "cassette_wrong_type.yaml")
    results = checker.check(path)
    assert len(results) == 1
    r = results[0]
    assert r.drifted
    assert r.cassette_file == "cassette_wrong_type.yaml"
    assert r.interaction_index == 0
    # At least two type errors (id should be int, email should be string)
    assert len(r.errors) >= 2
    # Errors should mention type issues
    error_text = " ".join(r.errors)
    assert "integer" in error_text or "not of type" in error_text or "type" in error_text.lower()


def test_drift_result_to_dict(checker):
    """DriftResult.to_dict() should contain all required locator fields."""
    path = os.path.join(FIXTURES_DIR, "cassette_missing_required.yaml")
    results = checker.check(path)
    d = results[0].to_dict()
    assert "cassette_file" in d
    assert "interaction_index" in d
    assert "path" in d
    assert "method" in d
    assert "status_code" in d
    assert "expected_schema" in d
    assert "actual_keys_diff" in d
    assert "drifted" in d
    assert "errors" in d
    assert d["drifted"] is True
