"""The country given at sign-up is offered (not saved) as onboarding step 1's starting choice."""
from src.ai import onboarding_profile


class _Cursor:
    def __init__(self, row):
        self.row = row

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params):
        assert "country_code" in sql

    def fetchone(self):
        return self.row


class _Conn:
    def __init__(self, row):
        self.row = row

    def cursor(self):
        return _Cursor(self.row)


def test_signup_country_is_suggested_until_a_country_is_saved():
    fresh = onboarding_profile.state(_Conn(({}, None, "JO")), "tenant")
    assert fresh["suggestedCountry"] == "JO"
    assert "country" not in fresh
    saved = onboarding_profile.state(_Conn(({"country": "EG", "highestCompletedStep": 1}, None, "JO")), "tenant")
    assert "suggestedCountry" not in saved and saved["country"] == "EG"


def test_no_suggestion_without_a_signup_country():
    assert "suggestedCountry" not in onboarding_profile.state(_Conn(({}, None, None)), "tenant")
