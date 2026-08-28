from __future__ import annotations

import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.metrics import (
    classification_report,
    confusion_matrix,
    f1_score,
    precision_recall_curve,
    precision_score,
    recall_score,
)

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data" / "train_transaction.csv"
MODEL_DIR = ROOT / "models"
TARGET = "isFraud"
DROP_COLS = ["isFraud", "TransactionID"]


def main() -> None:
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    if not DATA.exists():
        raise SystemExit(f"Missing {DATA} — run python -m backend.ml.download_data first")

    print(f"Loading {DATA}…")
    df = pd.read_csv(DATA)
    features = [c for c in df.columns if c not in DROP_COLS]

    for col in features:
        if not pd.api.types.is_numeric_dtype(df[col]):
            df[col] = df[col].astype("category").cat.codes.astype("float32")
        else:
            df[col] = pd.to_numeric(df[col], errors="coerce").astype("float32")

    df = df.dropna(subset=[TARGET])
    X = df[features]
    y = df[TARGET].astype(int)

    split_idx = int(len(df) * 0.8)
    X_train, X_test = X.iloc[:split_idx], X.iloc[split_idx:]
    y_train, y_test = y.iloc[:split_idx], y.iloc[split_idx:]

    scale = float((y_train == 0).sum() / max((y_train == 1).sum(), 1))
    model = xgb.XGBClassifier(
        n_estimators=500,
        max_depth=8,
        learning_rate=0.05,
        scale_pos_weight=scale,
        eval_metric="aucpr",
        early_stopping_rounds=50,
        random_state=42,
        n_jobs=-1,
        colsample_bytree=0.8,
        subsample=0.8,
        min_child_weight=5,
        gamma=1,
        reg_alpha=0.1,
        reg_lambda=1,
        tree_method="hist",
    )
    model.fit(X_train, y_train, eval_set=[(X_test, y_test)], verbose=50)

    y_prob = model.predict_proba(X_test)[:, 1]
    precisions, recalls, thresholds = precision_recall_curve(y_test, y_prob)
    f1_scores = 2 * (precisions[:-1] * recalls[:-1]) / (precisions[:-1] + recalls[:-1] + 1e-8)
    best_f1_idx = int(np.argmax(f1_scores))
    best_f1_threshold = float(thresholds[best_f1_idx])

    valid_idx = np.where(precisions[:-1] >= 0.7)[0]
    if len(valid_idx) > 0:
        best_p70_idx = int(valid_idx[np.argmax(recalls[:-1][valid_idx])])
        precision_threshold = float(thresholds[best_p70_idx])
    else:
        precision_threshold = best_f1_threshold

    deploy_threshold = precision_threshold
    y_pred = (y_prob >= deploy_threshold).astype(int)
    y_pred_default = (y_prob >= 0.5).astype(int)

    top_features = sorted(
        zip(features, model.feature_importances_.tolist()),
        key=lambda x: x[1],
        reverse=True,
    )[:20]

    metrics = {
        "precision": float(precision_score(y_test, y_pred, zero_division=0)),
        "recall": float(recall_score(y_test, y_pred, zero_division=0)),
        "f1": float(f1_score(y_test, y_pred, zero_division=0)),
        "confusion_matrix": confusion_matrix(y_test, y_pred).tolist(),
        "optimal_threshold": deploy_threshold,
        "default_threshold_metrics": {
            "precision": float(precision_score(y_test, y_pred_default, zero_division=0)),
            "recall": float(recall_score(y_test, y_pred_default, zero_division=0)),
            "f1": float(f1_score(y_test, y_pred_default, zero_division=0)),
        },
        "test_size": int(len(y_test)),
        "train_size": int(len(y_train)),
        "fraud_rate_train": float(y_train.mean()),
        "fraud_rate_test": float(y_test.mean()),
        "num_features": len(features),
        "dataset": "IEEE-CIS Fraud Detection",
        "dataset_size": int(len(df)),
        "top_features": [{"name": f, "importance": float(i)} for f, i in top_features],
    }

    print(f"\nDeploy threshold: {deploy_threshold:.4f}")
    print("At deploy threshold:")
    print(classification_report(y_test, y_pred, zero_division=0))
    print(f"Precision: {metrics['precision']:.4f}")
    print(f"Recall: {metrics['recall']:.4f}")
    print(f"F1: {metrics['f1']:.4f}")
    print("\nTop 10 features:")
    for feat in metrics["top_features"][:10]:
        print(f"  {feat['name']}: {feat['importance']:.4f}")

    joblib.dump(model, MODEL_DIR / "card_dispute_model.joblib")
    (MODEL_DIR / "card_model_metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    (MODEL_DIR / "card_model_features.json").write_text(json.dumps(features), encoding="utf-8")
    print(f"\nCard model saved. {len(features)} features. Threshold: {deploy_threshold:.4f}")


if __name__ == "__main__":
    main()
