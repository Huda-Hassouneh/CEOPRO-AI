from datetime import date

from src.ai.mpi.scoring import (
    ReviewContribution,
    compare_mpi_results,
    compute_mpi,
    recency_weight,
    reliability_weight,
    volume_confidence,
)


def test_recency_weight_is_one_for_same_day():
    assert recency_weight(date(2026, 8, 8), date(2026, 8, 8)) == 1.0


def test_recency_weight_decays_with_age():
    today = date(2026, 8, 8)
    recent = recency_weight(date(2026, 8, 1), today)
    old = recency_weight(date(2026, 1, 1), today)
    assert recent > old
    assert 0.0 < old < recent < 1.0


def test_reliability_weight_ranks_public_api_above_manual():
    assert reliability_weight("PUBLIC_API") > reliability_weight("PUBLIC_FEED") > reliability_weight("MANUAL")


def test_reliability_weight_unknown_method_falls_back_to_manual_level():
    from src.ai.mpi.scoring import DEFAULT_RELIABILITY_WEIGHT, reliability_weight as rw
    assert rw("SOME_UNKNOWN_METHOD") == DEFAULT_RELIABILITY_WEIGHT


def test_volume_confidence_saturates_at_one():
    assert volume_confidence(0) == 0.0
    assert 0.0 < volume_confidence(5) < 1.0
    assert volume_confidence(1000) == 1.0


def test_compute_mpi_returns_none_for_empty_contributions():
    assert compute_mpi([], {}) is None


def test_compute_mpi_all_positive_high_volume_approaches_100():
    contributions = [
        ReviewContribution(f"r{i}", sentiment_score=1.0, recency_weight=1.0, reliability_weight=1.0, relevance_weight=1.0)
        for i in range(50)
    ]
    result = compute_mpi(contributions, {"positive": 50, "neutral": 0, "negative": 0})
    assert result.mpi > 95
    assert result.volume_confidence == 1.0
    assert result.review_count == 50


def test_compute_mpi_all_negative_high_volume_approaches_zero():
    contributions = [
        ReviewContribution(f"r{i}", sentiment_score=-1.0, recency_weight=1.0, reliability_weight=1.0, relevance_weight=1.0)
        for i in range(50)
    ]
    result = compute_mpi(contributions, {"positive": 0, "neutral": 0, "negative": 50})
    assert result.mpi < 5


def test_compute_mpi_no_signal_stays_at_neutral_midpoint():
    contributions = [
        ReviewContribution("r1", sentiment_score=0.0, recency_weight=1.0, reliability_weight=1.0, relevance_weight=1.0)
    ]
    result = compute_mpi(contributions, {"positive": 0, "neutral": 1, "negative": 0})
    assert result.mpi == 50.0


def test_compute_mpi_low_volume_pulls_toward_neutral_despite_strong_sentiment():
    """A single glowing review shouldn't swing the MPI to 100 - volume confidence must dampen it."""
    contributions = [
        ReviewContribution("r1", sentiment_score=1.0, recency_weight=1.0, reliability_weight=1.0, relevance_weight=1.0)
    ]
    result = compute_mpi(contributions, {"positive": 1, "neutral": 0, "negative": 0})
    assert 50.0 < result.mpi < 60.0  # nowhere near 100, despite a perfect single review


def test_compute_mpi_low_reliability_reviews_count_less():
    high_reliability = [
        ReviewContribution(f"r{i}", sentiment_score=1.0, recency_weight=1.0, reliability_weight=1.0, relevance_weight=1.0)
        for i in range(20)
    ]
    low_reliability = [
        ReviewContribution(f"r{i}", sentiment_score=1.0, recency_weight=1.0, reliability_weight=0.1, relevance_weight=1.0)
        for i in range(20)
    ]
    result_high = compute_mpi(high_reliability, {})
    result_low = compute_mpi(low_reliability, {})
    # Weighted sentiment score itself is unaffected (all-positive either way),
    # but the low-reliability set contributes less to a mixed comparison -
    # verified indirectly via a mixed batch below instead of this symmetric case.
    assert result_high.weighted_sentiment_score == result_low.weighted_sentiment_score


def test_compute_mpi_mixed_reliability_weights_toward_the_more_reliable_reviews():
    contributions = [
        ReviewContribution(
            "positive_reliable", sentiment_score=1.0, recency_weight=1.0, reliability_weight=1.0, relevance_weight=1.0
        ),
        ReviewContribution(
            "negative_unreliable", sentiment_score=-1.0, recency_weight=1.0, reliability_weight=0.1, relevance_weight=1.0
        ),
    ]
    result = compute_mpi(contributions, {})
    assert result.weighted_sentiment_score > 0  # the reliable positive review dominates


def test_compare_mpi_results_refuses_comparison_below_volume_floor():
    thin = compute_mpi(
        [ReviewContribution("r1", sentiment_score=0.5, recency_weight=1.0, reliability_weight=1.0, relevance_weight=1.0)], {}
    )
    thick = compute_mpi(
        [
            ReviewContribution(f"r{i}", sentiment_score=0.5, recency_weight=1.0, reliability_weight=1.0, relevance_weight=1.0)
            for i in range(30)
        ],
        {},
    )
    comparison = compare_mpi_results(thin, thick, min_volume_for_comparison=10)
    assert comparison.comparable is False
    assert comparison.difference is None


def test_compare_mpi_results_returns_difference_when_both_sides_sufficient():
    a = compute_mpi(
        [
            ReviewContribution(f"a{i}", sentiment_score=1.0, recency_weight=1.0, reliability_weight=1.0, relevance_weight=1.0)
            for i in range(20)
        ],
        {},
    )
    b = compute_mpi(
        [
            ReviewContribution(f"b{i}", sentiment_score=-1.0, recency_weight=1.0, reliability_weight=1.0, relevance_weight=1.0)
            for i in range(20)
        ],
        {},
    )
    comparison = compare_mpi_results(a, b, min_volume_for_comparison=10)
    assert comparison.comparable is True
    assert comparison.difference > 0  # a is more positive than b
