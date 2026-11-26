"""Credential configuration regressions; no network or account mutation."""
import os
import subprocess
import sys
from pathlib import Path

import pytest

from .live_test_config import require_signup_opt_in, require_test_accounts


@pytest.fixture(autouse=True)
def clear_accounts(monkeypatch):
    for key in list(os.environ):
        if key.startswith('IIQ_TEST_'):
            monkeypatch.delenv(key)
    monkeypatch.setenv('IIQ_TEST_CONFIG_FILE', '')


def test_missing_config_skips_without_values():
    with pytest.raises(pytest.skip.Exception, match='IIQ_TEST_A_EMAIL'):
        require_test_accounts()


def test_provisioned_account(monkeypatch):
    monkeypatch.setenv('IIQ_TEST_A_EMAIL', 'account-a@example.invalid')
    monkeypatch.setenv('IIQ_TEST_A_PASSWORD', 'synthetic-test-sentinel')
    assert require_test_accounts()['A']['email'] == 'account-a@example.invalid'


def test_isolation_requires_distinct_accounts(monkeypatch):
    for label in ('A', 'B'):
        monkeypatch.setenv(f'IIQ_TEST_{label}_EMAIL', 'same@example.invalid')
        monkeypatch.setenv(f'IIQ_TEST_{label}_PASSWORD', 'synthetic-test-sentinel')
    with pytest.raises(pytest.skip.Exception, match='distinct'):
        require_test_accounts(2)


def test_signup_requires_separate_opt_in():
    with pytest.raises(pytest.skip.Exception, match='creation is disabled'):
        require_signup_opt_in()


def test_legacy_scripts_stop_before_network_without_credentials():
    folder = Path(__file__).parent
    for name in ('test_live_http_flow.py', 'test_phase12_profile.py', 'test_phase12_token_refresh.py',
                 'test_phase13_history_analytics.py', 'test_phase14_report_generation.py',
                 'verify_phase12_all_17_tests.py', 'verify_phase13_isolation_edge_cases.py',
                 'verify_phase13_real_e2e_flow.py', 'verify_phase14_real_e2e_flow.py',
                 'verify_real_e2e_persistence.py', 'verify_real_persistence_e2e.py'):
        result = subprocess.run([sys.executable, str(folder / name)], capture_output=True, text=True, timeout=10)
        assert result.returncode == 0, name
        assert result.stdout.startswith('SKIP:'), name
        assert not result.stderr, name
