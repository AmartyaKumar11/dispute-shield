from __future__ import annotations

from dataclasses import dataclass

from backend.config import settings


@dataclass
class TriageDecision:
    action: str  # auto_submit | review | accept
    review_reason: str
    win_probability: float


def decide_triage(win_probability: float, reasoning: str = "") -> TriageDecision:
    auto = float(settings.win_prob_auto_submit)
    review = float(settings.win_prob_review)
    score = float(win_probability)
    if score >= auto:
        return TriageDecision(
            action="auto_submit",
            review_reason=f"Win probability {score:.0f}% ≥ {auto:.0f}% — auto-submit contest.",
            win_probability=score,
        )
    if score >= review:
        return TriageDecision(
            action="review",
            review_reason=(
                f"Win probability {score:.0f}% is in the review band "
                f"({review:.0f}–{auto:.0f}%). Manual decision recommended. {reasoning}"
            ).strip(),
            win_probability=score,
        )
    return TriageDecision(
        action="accept",
        review_reason=(
            f"Win probability {score:.0f}% < {review:.0f}% — contest unlikely to succeed. "
            f"{reasoning}"
        ).strip(),
        win_probability=score,
    )


def clamp_demo_win(payment_data: dict, win_probability: float) -> float:
    """Optional seed bias so demos show a mix of triage outcomes."""
    notes = payment_data.get("notes") if isinstance(payment_data.get("notes"), dict) else {}
    band = notes.get("demo_triage")
    if band == "auto_submit":
        return max(win_probability, float(settings.win_prob_auto_submit) + 5)
    if band == "review":
        mid = (float(settings.win_prob_review) + float(settings.win_prob_auto_submit)) / 2
        return mid
    if band == "accept":
        return min(win_probability, float(settings.win_prob_review) - 8)
    return win_probability
