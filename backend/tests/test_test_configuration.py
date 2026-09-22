"""The CI acceptance command must not pass by silently skipping integration tests."""

import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize("missing", ["TEST_DATABASE_URL", "TEST_REDIS_URL"])
def test_required_service_mode_rejects_missing_configuration(missing):
    env = os.environ | {
        "TEST_DATABASE_URL": "postgresql+psycopg://unused/isolated_test",
        "TEST_REDIS_URL": "redis://localhost:6379/15",
    }
    env.pop(missing)
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--require-services",
            "--collect-only",
            "tests/test_features.py",
        ],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == pytest.ExitCode.USAGE_ERROR
    assert f"Full suite requires {missing}" in result.stderr
