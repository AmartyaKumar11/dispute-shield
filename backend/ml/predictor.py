from __future__ import annotations

import json
from pathlib import Path

import joblib
import numpy as np
import structlog

log = structlog.get_logger(__name__)


class DisputePredictor:
    """Loads trained models on init, provides prediction methods."""

    def __init__(self) -> None:
        model_dir = Path(__file__).parent / "models"
        self.card_model = None
        self.card_features: list[str] = []
        self.card_metrics: dict = {}
        self.card_threshold = 0.5
        self.upi_model = None
        self.upi_features: list[str] = []
        self.upi_metrics: dict = {}
        self.upi_threshold = 0.5

        card_model_path = model_dir / "card_dispute_model.joblib"
        if card_model_path.exists():
            try:
                self.card_model = joblib.load(card_model_path)
                with open(model_dir / "card_model_features.json", encoding="utf-8") as f:
                    self.card_features = json.load(f)
                with open(model_dir / "card_model_metrics.json", encoding="utf-8") as f:
                    self.card_metrics = json.load(f)
                self.card_threshold = float(self.card_metrics.get("optimal_threshold", 0.5))
                log.info("ml.card_model_loaded", path=str(card_model_path))
            except Exception:
                log.exception("ml.card_model_load_failed")
                self.card_model = None

        upi_model_path = model_dir / "upi_dispute_model.joblib"
        if upi_model_path.exists():
            try:
                self.upi_model = joblib.load(upi_model_path)
                with open(model_dir / "upi_model_features.json", encoding="utf-8") as f:
                    self.upi_features = json.load(f)
                with open(model_dir / "upi_model_metrics.json", encoding="utf-8") as f:
                    self.upi_metrics = json.load(f)
                self.upi_threshold = float(self.upi_metrics.get("optimal_threshold", 0.5))
                log.info("ml.upi_model_loaded", path=str(upi_model_path))
            except Exception:
                log.exception("ml.upi_model_load_failed")
                self.upi_model = None

    def predict_card_risk(self, transaction_data: dict) -> dict:
        if self.card_model is None:
            return {
                "probability": 0.5,
                "risk_score": 50,
                "model": "fallback",
                "threshold": 0.5,
                "flagged": False,
            }

        features = self._map_card_features(transaction_data)
        prob = float(self.card_model.predict_proba([features])[0][1])
        flagged = prob >= self.card_threshold
        return {
            "probability": prob,
            "risk_score": int(prob * 100),
            "model": "ieee-cis-xgboost",
            "threshold": self.card_threshold,
            "flagged": flagged,
            "model_precision": self.card_metrics.get("precision"),
            "model_recall": self.card_metrics.get("recall"),
            "model_f1": self.card_metrics.get("f1"),
            "features_used": self.card_metrics.get("num_features"),
            "training_data_size": self.card_metrics.get("dataset_size"),
        }

    def predict_upi_risk(self, transaction_data: dict) -> dict:
        if self.upi_model is None:
            return {
                "probability": 0.5,
                "risk_score": 50,
                "model": "fallback",
                "threshold": 0.5,
                "flagged": False,
            }

        features = self._map_upi_features(transaction_data)
        prob = float(self.upi_model.predict_proba([features])[0][1])
        flagged = prob >= self.upi_threshold
        return {
            "probability": prob,
            "risk_score": int(prob * 100),
            "model": "paysim-xgboost",
            "threshold": self.upi_threshold,
            "flagged": flagged,
            "model_precision": self.upi_metrics.get("precision"),
            "model_recall": self.upi_metrics.get("recall"),
            "model_f1": self.upi_metrics.get("f1"),
            "features_used": self.upi_metrics.get("num_features"),
            "training_data_size": self.upi_metrics.get("dataset_size"),
        }

    def _map_card_features(self, data: dict) -> list[float]:
        amount = data.get("amount", 0) / 100
        feature_vector: list[float] = []
        for feat in self.card_features:
            if feat == "TransactionAmt":
                feature_vector.append(float(amount))
            elif feat == "ProductCD":
                feature_vector.append(4.0)
            elif feat == "card4":
                brands = {"visa": 0, "mastercard": 1, "amex": 2, "rupay": 3}
                feature_vector.append(float(brands.get(data.get("card_brand", ""), -1)))
            elif feat == "card6":
                types = {"debit": 0, "credit": 1}
                feature_vector.append(float(types.get(data.get("card_type", ""), -1)))
            elif feat == "P_emaildomain":
                email = data.get("email", "") or ""
                domain = email.split("@")[1] if "@" in email else ""
                feature_vector.append(float(hash(domain) % 10000))
            elif feat == "TransactionDT":
                feature_vector.append(float(data.get("created_at", 0) or 0))
            else:
                feature_vector.append(-1.0)
        return feature_vector

    def _map_upi_features(self, data: dict) -> list[float]:
        amount = float(data.get("amount", 0) or 0) / 100
        hour = data.get("hour", 12)
        try:
            hour_i = int(hour)
        except (TypeError, ValueError):
            hour_i = 12

        feature_map = {
            "step": data.get("step", 1),
            "type_encoded": 3,
            "amount": amount,
            "amount_log": float(np.log1p(amount)),
            "oldbalanceOrg": -1,
            "newbalanceOrig": -1,
            "amount_ratio_orig": -1,
            "balance_change_orig": -1,
            "is_dest_merchant": 1,
            "drains_account": 0,
            "amount_gt_balance": 0,
            "sender_txn_count": data.get("sender_txn_count", -1),
            "sender_cumulative_amount": data.get("sender_cumulative_amount", -1),
            "sender_avg_amount": data.get("sender_avg_amount", -1),
            "amount_vs_sender_avg": -1,
            "sender_unique_recipients": data.get("sender_unique_recipients", -1),
            "hour_of_day": hour_i if hour is not None else -1,
            "is_night": 1 if hour_i <= 6 else 0,
            "is_risky_type": 0,
        }
        return [float(feature_map.get(f, -1)) for f in self.upi_features]

    def get_model_info(self) -> dict:
        return {
            "card_model": {
                "status": "loaded" if self.card_model else "not_found",
                "dataset": "IEEE-CIS Fraud Detection (590K real e-commerce transactions)",
                "metrics": self.card_metrics if self.card_model else None,
                "threshold": self.card_threshold,
                "top_features": (self.card_metrics.get("top_features", [])[:5] if self.card_model else []),
            },
            "upi_model": {
                "status": "loaded" if self.upi_model else "not_found",
                "dataset": (
                    "PaySim Mobile Money (6.3M synthetic transactions, "
                    "calibrated from real fintech data)"
                ),
                "metrics": self.upi_metrics if self.upi_model else None,
                "threshold": self.upi_threshold,
                "top_features": (self.upi_metrics.get("top_features", [])[:5] if self.upi_model else []),
            },
        }


predictor = DisputePredictor()
