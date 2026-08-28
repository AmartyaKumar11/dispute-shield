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
DATA = ROOT / "data" / "train_transaction.csv"
MODEL_DIR = ROOT / "models"

FEATURES = [
    "TransactionAmt",
    "ProductCD",
    "card4",
    "card6",
    "P_emaildomain",
    "R_emaildomain",
    "addr1",
    "addr2",
    "dist1",
    "C1",
    "C2",
    "C5",
    "C6",
    "C13",
    "C14",
    "D1",
    "D4",
    "D10",
    "D15",
]
TARGET = "isFraud"


def main() -> None:
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    if not DATA.exists():
        raise SystemExit(f"Missing {DATA} — run python -m backend.ml.download_data first")

    print(f"Loading {DATA}…")
    df = pd.read_csv(DATA)
    for col in FEATURES:
        if col not in df.columns:
            raise SystemExit(f"Missing column {col}")
        # Encode categoricals; force float so XGBoost never sees object/str dtypes
        if not pd.api.types.is_numeric_dtype(df[col]):
            df[col] = df[col].astype("category").cat.codes.astype("float64")
        else:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df[col] = df[col].fillna(-1).astype("float64")

    df = df.dropna(subset=[TARGET])
    X = df[FEATURES].astype("float64")
    y = df[TARGET].astype(int)

    split_idx = int(len(df) * 0.8)
    X_train, X_test = X.iloc[:split_idx], X.iloc[split_idx:]
    y_train, y_test = y.iloc[:split_idx], y.iloc[split_idx:]

    scale = (y_train == 0).sum() / max((y_train == 1).sum(), 1)
    model = xgb.XGBClassifier(
        n_estimators=200,
        max_depth=6,
        learning_rate=0.1,
        scale_pos_weight=scale,
        eval_metric="aucpr",
        random_state=42,
        n_jobs=-1,
    )
    model.fit(X_train, y_train, eval_set=[(X_test, y_test)], verbose=20)

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
        "dataset": "IEEE-CIS Fraud Detection",
        "dataset_size": int(len(df)),
        "features": FEATURES,
    }
    print(classification_report(y_test, y_pred, zero_division=0))
    print(f"Precision: {metrics['precision']:.4f}")
    print(f"Recall: {metrics['recall']:.4f}")
    print(f"F1: {metrics['f1']:.4f}")

    joblib.dump(model, MODEL_DIR / "card_dispute_model.joblib")
    (MODEL_DIR / "card_model_metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    (MODEL_DIR / "card_model_features.json").write_text(json.dumps(FEATURES), encoding="utf-8")
    print(f"Card model saved to {MODEL_DIR / 'card_dispute_model.joblib'}")


if __name__ == "__main__":
    main()
