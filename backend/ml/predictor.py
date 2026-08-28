from __future__ import annotations

import json
from pathlib import Path

import joblib
import structlog

log = structlog.get_logger(__name__)


class DisputePredictor:
    """Loads trained models on init, provides prediction methods."""

    def __init__(self) -> None:
        model_dir = Path(__file__).parent / "models"
        self.card_model = None
        self.card_features: list[str] = []
        self.card_metrics: dict = {}
        self.upi_model = None
        self.upi_features: list[str] = []
        self.upi_metrics: dict = {}

        card_model_path = model_dir / "card_dispute_model.joblib"
        if card_model_path.exists():
            try:
                self.card_model = joblib.load(card_model_path)
                with open(model_dir / "card_model_features.json", encoding="utf-8") as f:
                    self.card_features = json.load(f)
                with open(model_dir / "card_model_metrics.json", encoding="utf-8") as f:
                    self.card_metrics = json.load(f)
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
                log.info("ml.upi_model_loaded", path=str(upi_model_path))
            except Exception:
                log.exception("ml.upi_model_load_failed")
                self.upi_model = None

    def predict_card_risk(self, transaction_data: dict) -> dict:
        if self.card_model is None:
            return {"probability": 0.5, "risk_score": 50, "model": "fallback"}
        features = self._map_card_features(transaction_data)
        prob = float(self.card_model.predict_proba([features])[0][1])
        return {
            "probability": prob,
            "risk_score": int(round(prob * 100)),
            "model": "ieee-cis-xgboost",
            "model_precision": self.card_metrics.get("precision"),
            "model_recall": self.card_metrics.get("recall"),
        }

    def predict_upi_risk(self, transaction_data: dict) -> dict:
        if self.upi_model is None:
            return {"probability": 0.5, "risk_score": 50, "model": "fallback"}
        features = self._map_upi_features(transaction_data)
        prob = float(self.upi_model.predict_proba([features])[0][1])
        return {
            "probability": prob,
            "risk_score": int(round(prob * 100)),
            "model": "paysim-xgboost",
            "model_precision": self.upi_metrics.get("precision"),
            "model_recall": self.upi_metrics.get("recall"),
        }

    def _map_card_features(self, data: dict) -> list[float]:
        amount_raw = data.get("amount", 0) or 0
        amount = float(amount_raw) / 100.0
        email = str(data.get("email") or "")
        email_domain = email.split("@")[1] if "@" in email else "unknown"
        email_code = abs(hash(email_domain)) % 1000
        card4_code = {"visa": 0, "mastercard": 1, "amex": 2, "rupay": 3}.get(
            str(data.get("card_brand") or "").lower(), -1
        )
        card6_code = {"debit": 0, "credit": 1}.get(str(data.get("card_type") or "").lower(), -1)
        # Order matches FEATURES in train_card_model.py
        return [
            amount,
            -1,
            float(card4_code),
            float(card6_code),
            float(email_code),
            -1,
            -1,
            -1,
            -1,
            -1,
            -1,
            -1,
            -1,
            -1,
            -1,
            -1,
            -1,
            -1,
            -1,
        ]

    def _map_upi_features(self, data: dict) -> list[float]:
        amount_raw = data.get("amount", 0) or 0
        amount = float(amount_raw) / 100.0
        type_code = 3  # PAYMENT for merchant P2M
        return [
            float(data.get("step", 1) or 1),
            float(type_code),
            amount,
            -1,
            -1,
            -1,
            -1,
            -1,
            -1,
            -1,
            1,
            0,
            0,
        ]

    def get_model_info(self) -> dict:
        return {
            "card_model": {
                "status": "loaded" if self.card_model else "not_found",
                "dataset": "IEEE-CIS Fraud Detection (590K real transactions)",
                "metrics": self.card_metrics if self.card_model else None,
            },
            "upi_model": {
                "status": "loaded" if self.upi_model else "not_found",
                "dataset": "PaySim (6.3M synthetic mobile money transactions)",
                "metrics": self.upi_metrics if self.upi_model else None,
            },
        }


predictor = DisputePredictor()
