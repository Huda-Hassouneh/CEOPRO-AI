"""Explicit policy inputs are independent of MPI's captured runtime settings."""
from datetime import date

import pytest

from src.ai.mpi import cold_start, scoring


def test_explicit_recency_policy_and_runtime_wrapper(monkeypatch):
    monkeypatch.setattr(scoring, "RECENCY_HALF_LIFE_DAYS", 90)
    review_day, as_of = date(2020, 1, 1), date(2020, 1, 13)
    assert scoring._recency_weight(review_day, as_of, 12) == .5
    assert scoring.recency_weight(review_day, as_of) == .5 ** (12 / 90)
    assert scoring._recency_weight(as_of, review_day, 12) == 1.


@pytest.mark.parametrize("count,expected", [(0, 0.), (2, .5), (4, 1.), (5, 1.)])
def test_explicit_volume_policy(monkeypatch, count, expected):
    monkeypatch.setattr(scoring, "MIN_VOLUME_FOR_FULL_CONFIDENCE", 20)
    assert scoring._volume_confidence(count, 4) == expected
    assert scoring.volume_confidence(count) == count / 20


def test_explicit_scoring_policy_preserves_mixed_vector_and_rounding(monkeypatch):
    monkeypatch.setattr(scoring, "MIN_VOLUME_FOR_FULL_CONFIDENCE", 20)
    contributions = [scoring.ReviewContribution("a", .8, 1., 1., 1.),
                     scoring.ReviewContribution("b", -.6, .5, .6, 1.)]
    labels = {"positive": 1, "negative": 1}
    assert scoring._compute_mpi(contributions, labels, 4).as_dict() == dict(
        mpi=61.92, weighted_sentiment_score=.4769, volume_confidence=.5,
        review_count=2, avg_recency_weight=.75, avg_reliability_weight=.8,
        label_counts=labels)
    assert scoring.compute_mpi(contributions, labels).mpi == 52.38
    assert scoring._compute_mpi([], {}, 0) is None


def test_zero_weight_still_has_numeric_neutral_score():
    result = scoring._compute_mpi([scoring.ReviewContribution("a", 1., 0., 1., 1.)], {}, 4)
    assert result.mpi == 50.
    assert result.weighted_sentiment_score == 0.
    assert result.review_count == 1


@pytest.mark.parametrize("count,status", [(0, "LOW_SAMPLE_SIZE"), (2, "LOW_SAMPLE_SIZE"),
                                         (3, "OK"), (4, "OK")])
def test_explicit_sample_threshold_and_runtime_wrapper(monkeypatch, count, status):
    monkeypatch.setattr(cold_start, "MIN_SAMPLE_SIZE", 5)
    assert cold_start._assess_sample_size(count, 3).as_dict() == dict(
        sufficient=count >= 3, analyzed_count=count, minimum_required=3, status=status)
    assert cold_start.assess(count).minimum_required == 5
    assert cold_start.assess(count).status == "LOW_SAMPLE_SIZE"


def test_zero_policy_keeps_existing_arithmetic_failure():
    with pytest.raises(ZeroDivisionError):
        scoring._recency_weight(date(2020, 1, 1), date(2020, 1, 2), 0)
    with pytest.raises(ZeroDivisionError):
        scoring._compute_mpi([scoring.ReviewContribution("a", 1., 1., 1., 1.)], {}, 0)
