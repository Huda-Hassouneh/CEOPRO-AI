import pytest
from .test_verification_observations_db import role_password


@pytest.mark.parametrize('role,key', [
    ('ceopro_app', 'APP_DB_PASSWORD'),
    ('ceopro_billing_setup', 'BILLING_SETUP_DB_PASSWORD'),
    ('ceopro_billing_webhook', 'BILLING_WEBHOOK_DB_PASSWORD'),
    ('ceopro_credit_accounting', 'CREDIT_ACCOUNTING_DB_PASSWORD'),
    ('ceopro_billing_observer', 'OBSERVATION_TEST_PASSWORD'),
])
def test_each_role_uses_its_configured_credential(monkeypatch, role, key):
    for variable in ('APP_DB_PASSWORD', 'BILLING_SETUP_DB_PASSWORD', 'BILLING_WEBHOOK_DB_PASSWORD',
                     'CREDIT_ACCOUNTING_DB_PASSWORD', 'OBSERVATION_TEST_PASSWORD'):
        monkeypatch.setenv(variable, 'synthetic-' + variable)
    assert role_password(role) == 'synthetic-' + key
