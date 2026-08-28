from __future__ import annotations

import json
from pathlib import Path

import joblib
import pandas as pd
import xgboost as xgb
from sklearn.metrics import (
    classification_report,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
)

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data" / "PS_20174392719_1491204439457_log.csv"
MODEL_DIR = ROOT / "models"

FEATURES = [
    "step",
    "type_encoded",
    "amount",
    "oldbalanceOrg",
    "newbalanceOrig",
    "oldbalanceDest",
    "newbalanceDest",
    "amount_ratio_orig",
    "balance_change_orig",
    "balance_change_dest",
    "is_dest_merchant",
    "balance_error_orig",
    "balance_error_dest",
]
TARGET = "isFraud"
TYPE_MAP = {"CASH_IN": 0, "CASH_OUT": 1, "DEBIT": 2, "PAYMENT": 3, "TRANSFER": 4}


def main() -> None:
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    if not DATA.exists():
        raise SystemExit(f"Missing {DATA} — run python -m backend.ml.download_data first")

    print(f"Loading {DATA}…")
    df = pd.read_csv(DATA)
    df["amount_ratio_orig"] = df["amount"] / (df["oldbalanceOrg"] + 1)
    df["balance_change_orig"] = df["newbalanceOrig"] - df["oldbalanceOrg"]
    df["balance_change_dest"] = df["newbalanceDest"] - df["oldbalanceDest"]
    df["is_dest_merchant"] = df["nameDest"].astype(str).str.startswith("M").astype(int)
    df["balance_error_orig"] = (df["oldbalanceOrg"] - df["amount"] - df["newbalanceOrig"]).abs()
    df["balance_error_dest"] = (df["oldbalanceDest"] + df["amount"] - df["newbalanceDest"]).abs()
    df["type_encoded"] = df["type"].map(TYPE_MAP).fillna(-1).astype(int)

    X = df[FEATURES].fillna(-1)
    y = df[TARGET].astype(int)

    split_step = float(df["step"].quantile(0.8))
    train_mask = df["step"] <= split_step
    X_train, X_test = X[train_mask], X[~train_mask]
    y_train, y_test = y[train_mask], y[~train_mask]

    scale = (y_train == 0).sum() / max((y_train == 1).sum(), 1)

    if len(X_train) > 1_000_000:
        fraud_idx = X_train.index[y_train == 1]
        n_non = max(1_000_000 - len(fraud_idx), 1)
        nonfraud_idx = (
            X_train.index[y_train == 0]
            .to_series()
            .sample(n=min(n_non, (y_train == 0).sum()), random_state=42)
            .index
        )
        sample_idx = fraud_idx.union(nonfraud_idx)
        X_train = X_train.loc[sample_idx]
        y_train = y_train.loc[sample_idx]
        # recompute scale after sample? keep original imbalance weight from full train
        # (user said use scale from before sample — we computed scale already)

    model = xgb.XGBClassifier(
        n_estimators=200,
        max_depth=6,
        learning_rate=0.1,
        scale_pos_weight=scale,
        eval_metric="aucpr",
        random_state=42,
        n_jobs=-1,
    )
    # Cap eval set size for speed
    if len(X_test) > 200_000:
        X_eval = X_test.sample(n=200_000, random_state=42)
        y_eval = y_test.loc[X_eval.index]
    else:
        X_eval, y_eval = X_test, y_test

    model.fit(X_train, y_train, eval_set=[(X_eval, y_eval)], verbose=20)

    y_pred = model.predict(X_test)
    metrics = {
        "precision": float(precision_score(y_test, y_pred, zero_division=0)),
        "recall": float(recall_score(y_test, y_pred, zero_division=0)),
        "f1": float(f1_score(y_test, y_pred, zero_division=0)),
        "confusion_matrix": confusion_matrix(y_test, y_pred).tolist(),
        "test_size": int(len(y_test)),
        "train_size": int(len(y_train)),
        "fraud_rate_train": float(y_train.mean()),
        "fraud_rate_test": float(y_test.mean()),
        "dataset": "PaySim Synthetic Mobile Money",
        "dataset_size": int(len(df)),
        "features": FEATURES,
    }
    print(classification_report(y_test, y_pred, zero_division=0))
    print(f"Precision: {metrics['precision']:.4f}")
    print(f"Recall: {metrics['recall']:.4f}")
    print(f"F1: {metrics['f1']:.4f}")

    joblib.dump(model, MODEL_DIR / "upi_dispute_model.joblib")
    (MODEL_DIR / "upi_model_metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    (MODEL_DIR / "upi_model_features.json").write_text(json.dumps(FEATURES), encoding="utf-8")
    print(f"UPI model saved to {MODEL_DIR / 'upi_dispute_model.joblib'}")


if __name__ == "__main__":
    main()
