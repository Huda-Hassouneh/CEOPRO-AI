"""Offline contract check for the unchanged onboarding request/storage format."""
import pytest
from pydantic import ValidationError
from src.ai.onboarding_profile import StepRequest


@pytest.mark.parametrize('country,city', [
    ('JO', 'amman'), ('US', 'new-york-city'), ('DE', 'berlin'), ('JP', 'tokyo'),
    ('BR', 'sao-paulo'), ('ZA', 'johannesburg'), ('AU', 'sydney'),
    ('JO', 'Amman (historic spelling)'),
])
def test_iso_country_and_city_string_are_accepted_unchanged(country, city):
    request = StepRequest(step=1, expected_revision=0, country=country, city=city, language='en')
    assert request.country == country
    assert request.city == city


@pytest.mark.parametrize('country,city', [('Jordan', 'amman'), ('jo', 'amman'), ('JO', ''), ('DE', ' '), ('DE', 'x' * 101)])
def test_invalid_storage_formats_are_rejected(country, city):
    with pytest.raises(ValidationError):
        StepRequest(step=1, expected_revision=0, country=country, city=city, language='en')
