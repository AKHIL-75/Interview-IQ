"""Opt-in credentials for provisioned live test accounts; never log values."""
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

config_path = os.environ.get('IIQ_TEST_CONFIG_FILE', str(Path(__file__).resolve().parents[1] / '.env.test.local'))
if config_path:
    load_dotenv(config_path, override=False)


def _unavailable(message):
    if 'pytest' in sys.modules:
        import pytest
        pytest.skip(message, allow_module_level=True)
    print('SKIP: ' + message)
    raise SystemExit(0)


def require_test_accounts(count=1):
    accounts = {}
    missing = []
    for label in ('A', 'B')[:count]:
        names = [f'IIQ_TEST_{label}_EMAIL', f'IIQ_TEST_{label}_PASSWORD']
        missing.extend(name for name in names if not os.environ.get(name))
        accounts[label] = dict(zip(('email', 'password'), (os.environ.get(name) for name in names)))
    if missing:
        _unavailable('Provision test accounts locally; missing ' + ', '.join(missing))
    if count == 2 and accounts['A']['email'].casefold() == accounts['B']['email'].casefold():
        _unavailable('Isolation checks require two distinct provisioned accounts')
    return accounts


def require_signup_opt_in():
    if os.environ.get('IIQ_TEST_ALLOW_SIGNUP') != '1':
        _unavailable('Legacy registration suite requires separate IIQ_TEST_ALLOW_SIGNUP=1; account creation is disabled by default')
