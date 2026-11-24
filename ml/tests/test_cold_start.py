"""FR-22: the three alpha regimes, exploration, and the shared-state rules (synthetic data)."""

import random

from ml.assignment.cold_start import (
    HISTORY_MATCH,
    NEW_DEVELOPER,
    SKILL_MATCH,
    Candidate,
    alpha_for,
    recommend,
)

BUG = "NullPointerException in the payments checkout when the card is declined"


def make(
    dev_id: int,
    resolved: int,
    profile: str,
    history: float | None,
    *,
    availability: str = "Available",
    workload: int = 0,
    max_workload: int = 5,
    active: bool = True,
) -> Candidate:
    return Candidate(
        developer_id=dev_id,
        name=f"dev{dev_id}",
        resolved_count=resolved,
        profile_text=profile,
        history_score=history,
        availability=availability,
        workload=workload,
        max_workload=max_workload,
        active=active,
    )


def test_alpha_regimes() -> None:
    assert alpha_for(0, 10) == 0.0
    assert alpha_for(4, 10) == 0.4
    assert alpha_for(10, 10) == 1.0
    assert alpha_for(25, 10) == 1.0


def test_alpha_zero_uses_profile_only() -> None:
    newcomer = make(1, 0, "payments checkout card", history=0.9)
    other = make(2, 0, "css themes", history=0.1)
    result = recommend(BUG, [newcomer, other], threshold=10, epsilon=0.0, availability_bonus=0.0)
    assert [r.developer_id for r in result] == [1, 2]
    assert result[0].alpha == 0.0
    assert result[0].score == result[0].profile_score  # history ignored
    assert result[0].reason == NEW_DEVELOPER


def test_alpha_one_uses_history_only() -> None:
    veteran = make(1, 50, "css themes", history=0.6)  # weak skills, strong history
    specialist = make(2, 50, "payments checkout card", history=0.2)
    result = recommend(BUG, [veteran, specialist], threshold=10, epsilon=0.0)
    assert [r.developer_id for r in result] == [1, 2]
    assert result[0].alpha == 1.0 and result[0].score == 1.0  # history rescaled to best = 1
    assert result[0].reason == HISTORY_MATCH


def test_partial_alpha_blends_both() -> None:
    warm = make(1, 5, "payments checkout card", history=0.3)
    result = recommend(
        BUG, [warm, make(2, 50, "", history=0.6)], threshold=10, epsilon=0.0, availability_bonus=0.0
    )
    blended = next(r for r in result if r.developer_id == 1)
    assert blended.alpha == 0.5
    expected = 0.5 * blended.history_score + 0.5 * blended.profile_score
    assert abs(blended.score - expected) < 1e-3
    assert blended.reason in (HISTORY_MATCH, SKILL_MATCH)


def test_unknown_to_history_model_falls_back_to_profile() -> None:
    result = recommend(BUG, [make(1, 30, "payments", history=None)], threshold=10, epsilon=0.0)
    assert result[0].alpha == 0.0 and result[0].reason == SKILL_MATCH


def test_exploration_reserves_slot_three_for_cold_start() -> None:
    veterans = [make(i, 40, "payments checkout card", history=0.9 - i / 100) for i in range(1, 5)]
    newcomer = make(99, 0, "css", history=None)
    always = recommend(BUG, [*veterans, newcomer], threshold=10, epsilon=1.0, rng=random.Random(1))  # noqa: S311
    assert always[2].developer_id == 99 and always[2].explored and always[2].reason == NEW_DEVELOPER
    never = recommend(BUG, [*veterans, newcomer], threshold=10, epsilon=0.0)
    assert 99 not in [r.developer_id for r in never]


def test_critical_bug_skips_unavailable_and_full_developers() -> None:
    busy = make(1, 40, "payments checkout", history=0.9, workload=5, max_workload=5)
    away = make(2, 40, "payments checkout", history=0.8, availability="Unavailable")
    free = make(3, 40, "payments checkout", history=0.1)
    ids = [
        r.developer_id
        for r in recommend(BUG, [busy, away, free], threshold=10, epsilon=0, severity="Critical")
    ]
    assert ids == [3]
    normal = [r.developer_id for r in recommend(BUG, [busy, away, free], threshold=10, epsilon=0)]
    assert normal[0] == 1


def test_likely_duplicate_boosts_original_fixer_and_inactive_excluded() -> None:
    a = make(1, 40, "payments checkout", history=0.9)
    b = make(2, 40, "payments checkout", history=0.5)
    gone = make(3, 40, "payments checkout", history=1.0, active=False)
    result = recommend(
        BUG, [a, b, gone], threshold=10, epsilon=0, original_fixers=[2], duplicate_boost=0.6
    )
    assert [r.developer_id for r in result] == [2, 1]
    assert result[0].notes
    assert recommend(BUG, [], threshold=10, epsilon=0) == []


def test_absolute_history_scale_lets_a_strong_skill_match_win() -> None:
    """A veteran whose resolved reports are only weakly similar (0.2) must not beat a
    newcomer whose skills match the report well, once history is on an absolute scale."""
    veteran = make(1, 40, "billing invoices", 0.2)
    newcomer = make(2, 0, "payments checkout card declined nullpointerexception", None)
    relative = recommend(BUG, [veteran, newcomer], threshold=10, epsilon=0.0)
    absolute = recommend(
        BUG, [veteran, newcomer], threshold=10, epsilon=0.0, normalize_history=False
    )
    assert relative[0].developer_id == 1  # rescaled: the weak match becomes 1.0
    assert absolute[0].developer_id == 2
    assert absolute[0].reason == NEW_DEVELOPER
    assert absolute[1].history_score == 0.2
