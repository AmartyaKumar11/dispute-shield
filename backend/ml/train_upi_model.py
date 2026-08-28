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
DATA = ROOT / "data" / "PS_20174392719_1491204439457_log.csv"
MODEL_DIR = ROOT / "models"
TARGET = "isFraud"
TYPE_MAP = {"CASH_IN": 0, "CASH_OUT": 1, "DEBIT": 2, "PAYMENT": 3, "TRANSFER": 4}

FEATURES = [
    "step",
    "type_encoded",
    "amount",
    "amount_log",
    "oldbalanceOrg",
    "newbalanceOrig",
    "amount_ratio_orig",
    "balance_change_orig",
    "is_dest_merchant",
    "drains_account",
    "amount_gt_balance",
    "sender_txn_count",
    "sender_cumulative_amount",
    "sender_avg_amount",
    "amount_vs_sender_avg",
    "sender_unique_recipients",
    "hour_of_day",
    "is_night",
    "is_risky_type",
]


def main() -> None:
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    if not DATA.exists():
        raise SystemExit(f"Missing {DATA} — run python -m backend.ml.download_data first")

    print(f"Loading {DATA}…")
    df = pd.read_csv(DATA)
    df["type_encoded"] = df["type"].map(TYPE_MAP)

    # No balance_error_* / dest balances — those leak the label
    df["amount_log"] = np.log1p(df["amount"])
    df["amount_ratio_orig"] = df["amount"] / (df["oldbalanceOrg"] + 1)
    df["balance_change_orig"] = df["newbalanceOrig"] - df["oldbalanceOrg"]
    df["is_dest_merchant"] = df["nameDest"].astype(str).str.startswith("M").astype(int)
    df["drains_account"] = (df["newbalanceOrig"] == 0).astype(int)
    df["amount_gt_balance"] = (df["amount"] > df["oldbalanceOrg"]).astype(int)

    df = df.sort_values(["nameOrig", "step"]).reset_index(drop=True)
    df["sender_txn_count"] = df.groupby("nameOrig").cumcount()
    df["sender_cumulative_amount"] = df.groupby("nameOrig")["amount"].cumsum() - df["amount"]
    df["sender_avg_amount"] = df["sender_cumulative_amount"] / (df["sender_txn_count"] + 1)
    df["amount_vs_sender_avg"] = df["amount"] / (df["sender_avg_amount"] + 1)
    df["sender_unique_recipients"] = df.groupby("nameOrig")["nameDest"].transform("nunique")
    df["hour_of_day"] = df["step"] % 24
    df["is_night"] = ((df["hour_of_day"] >= 0) & (df["hour_of_day"] <= 6)).astype(int)
    df["is_risky_type"] = df["type"].isin(["TRANSFER", "CASH_OUT"]).astype(int)

    X = df[FEATURES].fillna(-1)
    y = df[TARGET].astype(int)

    split_step = float(df["step"].quantile(0.8))
    train_mask = df["step"] <= split_step
    X_train, X_test = X[train_mask], X[~train_mask]
    y_train, y_test = y[train_mask], y[~train_mask]

    fraud_train = X_train.index[y_train == 1]
    nonfraud_train = X_train.index[y_train == 0]
    max_nonfraud = max(1_500_000 - len(fraud_train), 1)
    if len(nonfraud_train) > max_nonfraud:
        nonfraud_sample = (
            nonfraud_train.to_series().sample(n=max_nonfraud, random_state=42).index
        )
        sample_idx = fraud_train.union(nonfraud_sample)
        X_train = X_train.loc[sample_idx]
        y_train = y_train.loc[sample_idx]

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

    if len(X_test) > 250_000:
        X_eval = X_test.sample(n=250_000, random_state=42)
        y_eval = y_test.loc[X_eval.index]
    else:
        X_eval, y_eval = X_test, y_test

    model.fit(X_train, y_train, eval_set=[(X_eval, y_eval)], verbose=50)

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
        zip(FEATURES, model.feature_importances_.tolist()),
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
        "num_features": len(FEATURES),
        "dataset": "PaySim Mobile Money (6.3M transactions)",
        "dataset_size": int(len(df)),
        "top_features": [{"name": f, "importance": float(i)} for f, i in top_features],
    }

    print(f"\nDeploy threshold: {deploy_threshold:.4f}")
    print(classification_report(y_test, y_pred, zero_division=0))
    print(f"Precision: {metrics['precision']:.4f}")
    print(f"Recall: {metrics['recall']:.4f}")
    print(f"F1: {metrics['f1']:.4f}")
    print("\nTop 10 features:")
    for feat in metrics["top_features"][:10]:
        print(f"  {feat['name']}: {feat['importance']:.4f}")

    if metrics["precision"] > 0.95:
        print(
            "WARNING: precision still > 0.95 — possible residual leak. "
            f"Top features: {[f['name'] for f in metrics['top_features'][:5]]}"
        )

    joblib.dump(model, MODEL_DIR / "upi_dispute_model.joblib")
    (MODEL_DIR / "upi_model_metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    (MODEL_DIR / "upi_model_features.json").write_text(json.dumps(FEATURES), encoding="utf-8")
    print(f"\nUPI model saved. {len(FEATURES)} features. Threshold: {deploy_threshold:.4f}")


if __name__ == "__main__":
    main()
