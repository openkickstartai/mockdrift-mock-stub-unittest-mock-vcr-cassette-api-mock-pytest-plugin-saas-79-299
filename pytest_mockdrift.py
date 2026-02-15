"""MockDrift pytest plugin - validate mocks against OpenAPI schemas during tests.

Usage:
    # conftest.py
    pytest_plugins = ["pytest_mockdrift"]

    # run with:
    pytest --mockdrift-spec openapi.yaml --mockdrift-fail
"""
import pytest

from mockdrift_core import MockDriftDetector


class MockRegistry:
    """Collects mock registrations and validates each against the OpenAPI spec."""

    def __init__(self, detector):
        self._detector = detector
        self._reports = []

    def register(self, name, data, path, method="get", status="200"):
        """Register mock data and validate it against the spec schema.

        Returns the DriftReport so callers can assert inline.
        """
        report = self._detector.check_mock(name, data, path, method, status)
        self._reports.append(report)
        return report

    @property
    def reports(self):
        return list(self._reports)

    @property
    def drifted(self):
        return [r for r in self._reports if r.drifted]


def pytest_addoption(parser):
    grp = parser.getgroup("mockdrift", "Mock drift detection")
    grp.addoption("--mockdrift-spec",
                  help="Path to OpenAPI spec for mock drift detection")
    grp.addoption("--mockdrift-fail", action="store_true", default=False,
                  help="Fail tests when mock drift is detected")


@pytest.fixture
def mockdrift(request):
    """Fixture providing a MockRegistry bound to the configured OpenAPI spec.

    Use `mockdrift.register(name, data, path)` to validate mock data.
    When --mockdrift-fail is set, the test fails if any registered mock drifts.
    """
    spec_path = request.config.getoption("--mockdrift-spec", default=None)
    if not spec_path:
        pytest.skip("--mockdrift-spec not provided")
    detector = MockDriftDetector(spec_path)
    registry = MockRegistry(detector)
    yield registry
    if request.config.getoption("--mockdrift-fail") and registry.drifted:
        lines = [f"  {r.name}: {'; '.join(r.errors)}" for r in registry.drifted]
        count = len(registry.drifted)
        pytest.fail(
            f"MockDrift detected {count} drifted mock(s):\n" + "\n".join(lines))
