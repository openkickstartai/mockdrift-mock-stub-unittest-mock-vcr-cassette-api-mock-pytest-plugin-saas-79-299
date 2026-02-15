# MockDrift — Mock/Stub Drift Detector

> Catch every lying mock before your tests go green and production goes boom 💥

MockDrift validates your `unittest.mock` return values and VCR cassettes against real OpenAPI specs. If your API changed but your mocks didn't, MockDrift tells you *before* deploy.

## 🚀 Quick Start

```bash
pip install -r requirements.txt

# CLI: check a VCR cassette against your spec
python mockdrift_core.py --spec openapi.yaml --cassette tests/cassettes/users.yaml

# pytest: validate mocks during test runs
pytest --mockdrift-spec openapi.yaml --mockdrift-fail
```

### pytest Plugin Usage

```python
# conftest.py
pytest_plugins = ["pytest_mockdrift"]

# test_api.py
def test_user_endpoint(mockdrift):
    mock_data = {"id": 1, "email": "a@b.com", "name": "Alice"}
    report = mockdrift.register("user_mock", mock_data, "/users/{id}")
    assert not report.drifted
    # ... use mock_data in your test
```

### CLI Formats

```bash
# Human-readable
python mockdrift_core.py --spec api.yaml --cassette fixture.yaml

# JSON for scripting
python mockdrift_core.py --spec api.yaml --cassette fixture.yaml --format json

# SARIF for GitHub Code Scanning
python mockdrift_core.py --spec api.yaml --cassette fixture.yaml --format sarif
```

## 📊 Why Pay for MockDrift?

**The Problem**: Your test suite mocks an API returning `{"id": 1, "name": "Alice"}`. The real API now returns `{"user_id": 1, "full_name": "Alice", "role": "admin"}`. Tests pass. Production crashes. Every. Single. Time.

**The Cost**: A single production incident from stale mocks costs $5K–$50K in engineering time, customer impact, and incident response. MockDrift costs less than one on-call pizza.

## 💰 Pricing

| Feature | Free (OSS) | Pro ($79/mo) | Enterprise ($299/mo) |
|---|---|---|---|
| OpenAPI schema validation | ✅ | ✅ | ✅ |
| VCR cassette age check | ✅ | ✅ | ✅ |
| CLI + pytest plugin | ✅ | ✅ | ✅ |
| First validation error only | ✅ | All errors | All errors |
| SARIF output | ✅ | ✅ | ✅ |
| **Multi-spec projects** | 1 spec | Unlimited | Unlimited |
| **GraphQL & gRPC schemas** | ❌ | ✅ | ✅ |
| **Auto-discover all mocks** | ❌ | ✅ | ✅ |
| **GitHub PR comments** | ❌ | ✅ | ✅ |
| **Slack/Teams alerts** | ❌ | ❌ | ✅ |
| **Historical drift dashboard** | ❌ | ❌ | ✅ |
| **SSO + audit log** | ❌ | ❌ | ✅ |
| **SLA + priority support** | ❌ | ❌ | ✅ |

## 🏗️ Architecture

```
OpenAPI Spec ──→ MockDriftDetector ──→ DriftReport
                      ↑                    ↓
              mock data / cassette    text/json/sarif
```

## License

MIT (core) — Commercial features require a paid license.
