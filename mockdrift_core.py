"""MockDrift - detect when mocks/stubs drift from real API schemas."""
import json
import os
import sys
import time
from urllib.parse import urlparse

import yaml
from jsonschema import ValidationError, validate


class DriftReport:
    """Result of checking one mock or cassette interaction against a schema."""

    def __init__(self, name, path, method, errors):
        self.name = name
        self.path = path
        self.method = method
        self.errors = errors

    @property
    def drifted(self):
        return len(self.errors) > 0

    def to_dict(self):
        return {"name": self.name, "path": self.path, "method": self.method,
                "drifted": self.drifted, "errors": self.errors}


class MockDriftDetector:
    """Validates mock data and VCR cassettes against an OpenAPI spec."""

    def __init__(self, spec_path):
        with open(spec_path) as f:
            self.spec = yaml.safe_load(f)
        self._defs = self.spec.get(
            "definitions", self.spec.get("components", {}).get("schemas", {}))

    def _resolve(self, schema):
        if not isinstance(schema, dict):
            return schema
        if "$ref" in schema:
            name = schema["$ref"].split("/")[-1]
            return self._resolve(self._defs.get(name, {}))
        out = dict(schema)
        if "properties" in out:
            out["properties"] = {
                k: self._resolve(v) for k, v in out["properties"].items()}
        if "items" in out:
            out["items"] = self._resolve(out["items"])
        return out

    def get_schema(self, path, method="get", status="200"):
        op = self.spec.get("paths", {}).get(path, {}).get(method.lower())
        if not op:
            return None
        resp = op.get("responses", {}).get(str(status))
        if not resp:
            return None
        for media in resp.get("content", {}).values():
            if "schema" in media:
                return self._resolve(media["schema"])
        if "schema" in resp:
            return self._resolve(resp["schema"])
        return None

    def check_mock(self, name, data, path, method="get", status="200"):
        schema = self.get_schema(path, method, status)
        if not schema:
            return DriftReport(name, path, method,
                               [f"No schema for {method.upper()} {path} [{status}]"])
        errors = []
        try:
            validate(instance=data, schema=schema)
        except ValidationError as e:
            errors.append(e.message)
        return DriftReport(name, path, method, errors)

    def check_cassette(self, cassette_path, max_age_days=30):
        age_days = (time.time() - os.path.getmtime(cassette_path)) / 86400
        with open(cassette_path) as f:
            data = yaml.safe_load(f)
        reports = []
        for i, ix in enumerate(data.get("interactions", [])):
            req = ix.get("request", {})
            res = ix.get("response", {})
            path = urlparse(req.get("uri", "")).path
            method = req.get("method", "GET").lower()
            errs = []
            if age_days > max_age_days:
                errs.append(f"Cassette age {age_days:.0f}d exceeds {max_age_days}d limit")
            body_str = res.get("body", {}).get("string", "")
            try:
                body = json.loads(body_str) if body_str else None
            except (json.JSONDecodeError, TypeError):
                body = None
            if body is not None:
                schema = self.get_schema(path, method)
                if schema:
                    try:
                        validate(instance=body, schema=schema)
                    except ValidationError as e:
                        errs.append(f"Body drift: {e.message}")
            tag = f"cassette[{i}]:{method.upper()} {path}"
            reports.append(DriftReport(tag, path, method, errs))
        return reports


def to_sarif(reports):
    results = [
        {"ruleId": "mockdrift/schema-drift", "level": "error",
         "message": {"text": f"{r.name}: {e}"},
         "locations": [{"physicalLocation": {
             "artifactLocation": {"uri": r.path}}}]}
        for r in reports if r.drifted for e in r.errors]
    return {
        "version": "2.1.0",
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "runs": [{"tool": {"driver": {
            "name": "MockDrift", "version": "1.0.0",
            "rules": [{"id": "mockdrift/schema-drift",
                        "shortDescription": {"text": "Mock drifted from API schema"}}]}},
            "results": results}]}


def main():
    import argparse
    ap = argparse.ArgumentParser(prog="mockdrift",
                                 description="Detect stale mocks & cassettes")
    ap.add_argument("--spec", required=True, help="OpenAPI spec path")
    ap.add_argument("--cassette", help="VCR cassette file to check")
    ap.add_argument("--max-age", type=int, default=30, help="Max cassette age (days)")
    ap.add_argument("--format", choices=["text", "json", "sarif"], default="text")
    args = ap.parse_args()
    det = MockDriftDetector(args.spec)
    reports = det.check_cassette(args.cassette, args.max_age) if args.cassette else []
    drifted = [r for r in reports if r.drifted]
    if args.format == "sarif":
        print(json.dumps(to_sarif(reports), indent=2))
    elif args.format == "json":
        print(json.dumps([r.to_dict() for r in reports], indent=2))
    else:
        for r in reports:
            mark = "\u274c DRIFT" if r.drifted else "\u2705 OK"
            print(f"{mark} {r.name}")
            for e in r.errors:
                print(f"   \u2192 {e}")
        total = len(reports)
        print(f"\n{'\U0001f6a8' if drifted else '\u2705'} {len(drifted)}/{total} drifted")
    sys.exit(1 if drifted else 0)


if __name__ == "__main__":
    main()
