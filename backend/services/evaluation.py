from __future__ import annotations

import json
from dataclasses import asdict, dataclass

from backend.models import Dispute, TransactionRisk
from backend.utils.helpers import paise_to_rupees

_REACTIVE_ONLY = {"billing_proof", "access_activity_log", "explanation_letter"}
_VAULT_FIELDS = (
    "billing_proof",
    "shipping_proof",
    "customer_communication",
    "delivery_photo",
    "access_activity_log",
)
_FP_COST = 200.0


@dataclass
class ClassifierMetrics:
    total_transactions: int
    true_positives: int
    true_negatives: int
    false_positives: int
    false_negatives: int
    precision: float
    recall: float
    f1_score: float
    accuracy: float


@dataclass
class TriageMetrics:
    total_disputes: int
    auto_submitted: int
    sent_to_review: int
    recommended_accept: int
    avg_win_prob_auto: float
    avg_win_prob_review: float
    avg_win_prob_accept: float


@dataclass
class VaultMetrics:
    avg_coverage_with_vault: float
    avg_coverage_without_vault: float
    improvement_pct: float
    proactive_hit_rate: float


@dataclass
class CostAnalysis:
    cost_per_false_positive: float
    cost_per_false_negative: float
    total_fp_cost: float
    total_fn_cost: float
    current_threshold_total_cost: float
    optimal_threshold: int
    optimal_threshold_cost: float
    savings_vs_blind_contest: float


@dataclass
class EvaluationReport:
    risk_scorer: ClassifierMetrics
    triage: TriageMetrics
    vault: VaultMetrics
    cost: CostAnalysis

    def to_dict(self) -> dict:
        return {
            "risk_scorer": asdict(self.risk_scorer),
            "triage": asdict(self.triage),
            "vault": asdict(self.vault),
            "cost": asdict(self.cost),
        }


def _safe_div(num: float, den: float) -> float:
    return round(num / den, 4) if den else 0.0


async def compute_evaluation_metrics(
    risks: list[TransactionRisk],
    disputes: list[Dispute],
) -> EvaluationReport:
    disputed_pay = {d.payment_id for d in disputes}

    tp = tn = fp = fn = 0
    for r in risks:
        high = r.risk_score >= 50
        became = r.payment_id in disputed_pay or r.alert_status == "dispute_filed"
        if high and became:
            tp += 1
        elif not high and not became:
            tn += 1
        elif high and not became:
            fp += 1
        else:
            fn += 1

    precision = _safe_div(tp, tp + fp)
    recall = _safe_div(tp, tp + fn)
    f1 = _safe_div(2 * precision * recall, precision + recall) if (precision + recall) else 0.0
    accuracy = _safe_div(tp + tn, len(risks))

    classifier = ClassifierMetrics(
        total_transactions=len(risks),
        true_positives=tp,
        true_negatives=tn,
        false_positives=fp,
        false_negatives=fn,
        precision=precision,
        recall=recall,
        f1_score=round(f1, 4),
        accuracy=accuracy,
    )

    auto = [d for d in disputes if d.triage_action == "auto_submit"]
    review = [d for d in disputes if d.triage_action == "review"]
    accept = [d for d in disputes if d.triage_action == "accept"]

    def _avg_win(rows: list[Dispute]) -> float:
        vals = [float(d.win_probability) for d in rows if d.win_probability is not None]
        return round(sum(vals) / len(vals), 2) if vals else 0.0

    triage = TriageMetrics(
        total_disputes=len(disputes),
        auto_submitted=len(auto),
        sent_to_review=len(review),
        recommended_accept=len(accept),
        avg_win_prob_auto=_avg_win(auto),
        avg_win_prob_review=_avg_win(review),
        avg_win_prob_accept=_avg_win(accept),
    )

    with_cov: list[float] = []
    without_cov: list[float] = []
    hits = 0
    disputed_risks = [r for r in risks if r.payment_id in disputed_pay]
    for r in disputed_risks:
        try:
            fields = json.loads(r.vault_fields_json or "[]")
        except Exception:
            fields = []
        if not isinstance(fields, list):
            fields = []
        vault_set = set(fields)
        with_c = len(vault_set) / len(_VAULT_FIELDS)
        reactive = vault_set & _REACTIVE_ONLY
        without_c = len(reactive) / len(_VAULT_FIELDS)
        with_cov.append(with_c)
        without_cov.append(without_c)
        if len(vault_set) >= 1:
            hits += 1

    avg_with = round(sum(with_cov) / len(with_cov), 4) if with_cov else 0.0
    avg_without = round(sum(without_cov) / len(without_cov), 4) if without_cov else 0.0
    improvement = round((avg_with - avg_without) * 100, 1)
    hit_rate = _safe_div(hits, len(disputed_risks)) if disputed_risks else 0.0

    vault = VaultMetrics(
        avg_coverage_with_vault=avg_with,
        avg_coverage_without_vault=avg_without,
        improvement_pct=improvement,
        proactive_hit_rate=hit_rate,
    )

    avg_dispute_amt = (
        sum(paise_to_rupees(d.amount_paise) for d in disputes) / len(disputes) if disputes else 0.0
    )
    fn_cost_unit = avg_dispute_amt
    fp_cost_unit = _FP_COST
    current_cost = fp * fp_cost_unit + fn * fn_cost_unit

    # Sweep threshold 30..80 for optimal cost on this cohort
    best_t, best_cost = 50, current_cost
    for thresh in range(30, 81, 5):
        t_fp = t_fn = 0
        for r in risks:
            high = r.risk_score >= thresh
            became = r.payment_id in disputed_pay or r.alert_status == "dispute_filed"
            if high and not became:
                t_fp += 1
            elif not high and became:
                t_fn += 1
        cost = t_fp * fp_cost_unit + t_fn * fn_cost_unit
        if cost < best_cost:
            best_cost = cost
            best_t = thresh

    # Blind contest: contest every dispute at FP cost each (failed contest proxy) + miss none
    blind = len(disputes) * fp_cost_unit
    savings = max(0.0, blind - current_cost)

    cost = CostAnalysis(
        cost_per_false_positive=fp_cost_unit,
        cost_per_false_negative=round(fn_cost_unit, 2),
        total_fp_cost=round(fp * fp_cost_unit, 2),
        total_fn_cost=round(fn * fn_cost_unit, 2),
        current_threshold_total_cost=round(current_cost, 2),
        optimal_threshold=best_t,
        optimal_threshold_cost=round(best_cost, 2),
        savings_vs_blind_contest=round(savings, 2),
    )

    return EvaluationReport(risk_scorer=classifier, triage=triage, vault=vault, cost=cost)
