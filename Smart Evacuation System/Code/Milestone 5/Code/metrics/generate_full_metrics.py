from pathlib import Path
import json
import argparse
import sys

import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.metrics import (
    accuracy_score,
    balanced_accuracy_score,
    precision_recall_fscore_support,
    classification_report,
    confusion_matrix,
    matthews_corrcoef,
    cohen_kappa_score,
    log_loss,
    roc_auc_score,
    average_precision_score,
)
from sklearn.preprocessing import label_binarize
import matplotlib.pyplot as plt
import seaborn as sns

SCRIPT_DIR = Path(__file__).resolve().parent
CODE_DIR = SCRIPT_DIR.parent
if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))

from evacuation.model import EvacuationVirtualModel
from evacuation.data_prep import prepare_training_dataframe
from evacuation.config import ID_TO_STATE


def run(csv_path: Path, out_dir: Path, epochs: int = 50, random_state: int = 42, test_size: float = 0.2) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)

    df = pd.read_csv(csv_path)
    X, y, auto_labeled = prepare_training_dataframe(df, target_col="target_state")
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=test_size, random_state=random_state, stratify=y
    )

    vm = EvacuationVirtualModel()
    X_train_scaled = vm.scaler.fit_transform(X_train)
    X_test_scaled = vm.scaler.transform(X_test)

    rng = np.random.default_rng(random_state)
    n = X_train_scaled.shape[0]
    epoch_losses = []
    for _ in range(epochs):
        idx = rng.permutation(n)
        X_epoch = X_train_scaled[idx]
        y_epoch = y_train.iloc[idx].to_numpy()
        vm.model.partial_fit(X_epoch, y_epoch, classes=vm.classes_)

        p = np.clip(vm.model.predict_proba(X_epoch), 1e-9, 1.0)
        y_onehot = np.eye(len(vm.classes_))[y_epoch]
        loss = float(-np.mean(np.sum(y_onehot * np.log(p), axis=1)))
        epoch_losses.append(loss)

    y_pred = vm.model.predict(X_test_scaled)
    y_proba = vm.model.predict_proba(X_test_scaled)

    class_ids = [0, 1, 2]
    class_names = [ID_TO_STATE[i] for i in class_ids]

    acc = float(accuracy_score(y_test, y_pred))
    bal_acc = float(balanced_accuracy_score(y_test, y_pred))
    prec_micro, rec_micro, f1_micro, _ = precision_recall_fscore_support(y_test, y_pred, average="micro", zero_division=0)
    prec_macro, rec_macro, f1_macro, _ = precision_recall_fscore_support(y_test, y_pred, average="macro", zero_division=0)
    prec_weighted, rec_weighted, f1_weighted, _ = precision_recall_fscore_support(y_test, y_pred, average="weighted", zero_division=0)

    mcc = float(matthews_corrcoef(y_test, y_pred))
    kappa = float(cohen_kappa_score(y_test, y_pred))
    ll = float(log_loss(y_test, y_proba, labels=class_ids))

    y_test_bin = label_binarize(y_test, classes=class_ids)
    roc_auc_ovr_macro = float(roc_auc_score(y_test_bin, y_proba, average="macro", multi_class="ovr"))
    roc_auc_ovo_macro = float(roc_auc_score(y_test_bin, y_proba, average="macro", multi_class="ovo"))
    roc_auc_ovr_weighted = float(roc_auc_score(y_test_bin, y_proba, average="weighted", multi_class="ovr"))
    roc_auc_ovo_weighted = float(roc_auc_score(y_test_bin, y_proba, average="weighted", multi_class="ovo"))

    ap_per_class = {name: float(average_precision_score(y_test_bin[:, i], y_proba[:, i])) for i, name in enumerate(class_names)}
    mean_ap_macro = float(np.mean(list(ap_per_class.values())))

    cm = confusion_matrix(y_test, y_pred, labels=class_ids)
    cm_norm_true = confusion_matrix(y_test, y_pred, labels=class_ids, normalize="true")
    cm_norm_pred = confusion_matrix(y_test, y_pred, labels=class_ids, normalize="pred")
    cm_norm_all = confusion_matrix(y_test, y_pred, labels=class_ids, normalize="all")

    per_class_rates = {}
    for i, cname in enumerate(class_names):
        tp = float(cm[i, i])
        fn = float(cm[i, :].sum() - tp)
        fp = float(cm[:, i].sum() - tp)
        tn = float(cm.sum() - (tp + fn + fp))
        per_class_rates[cname] = {
            "tp": tp,
            "tn": tn,
            "fp": fp,
            "fn": fn,
            "sensitivity_tpr_recall": tp / (tp + fn) if (tp + fn) else 0.0,
            "specificity_tnr": tn / (tn + fp) if (tn + fp) else 0.0,
            "precision_ppv": tp / (tp + fp) if (tp + fp) else 0.0,
            "npv": tn / (tn + fn) if (tn + fn) else 0.0,
            "false_positive_rate": fp / (fp + tn) if (fp + tn) else 0.0,
            "false_negative_rate": fn / (fn + tp) if (fn + tp) else 0.0,
        }

    cls_report_dict = classification_report(
        y_test,
        y_pred,
        labels=class_ids,
        target_names=class_names,
        zero_division=0,
        output_dict=True,
    )
    cls_report_text = classification_report(
        y_test,
        y_pred,
        labels=class_ids,
        target_names=class_names,
        zero_division=0,
    )

    pd.DataFrame(cm, index=class_names, columns=class_names).to_csv(out_dir / "confusion_matrix_counts.csv")
    pd.DataFrame(cm_norm_true, index=class_names, columns=class_names).to_csv(out_dir / "confusion_matrix_normalized_true.csv")
    pd.DataFrame(cm_norm_pred, index=class_names, columns=class_names).to_csv(out_dir / "confusion_matrix_normalized_pred.csv")
    pd.DataFrame(cm_norm_all, index=class_names, columns=class_names).to_csv(out_dir / "confusion_matrix_normalized_all.csv")

    plt.figure(figsize=(7, 6))
    sns.heatmap(cm, annot=True, fmt="d", cmap="Blues", xticklabels=class_names, yticklabels=class_names)
    plt.title("Confusion Matrix (Counts)")
    plt.xlabel("Predicted")
    plt.ylabel("Actual")
    plt.tight_layout()
    plt.savefig(out_dir / "confusion_matrix_counts.png", dpi=200)
    plt.close()

    plt.figure(figsize=(7, 6))
    sns.heatmap(cm_norm_true, annot=True, fmt=".4f", cmap="Greens", xticklabels=class_names, yticklabels=class_names)
    plt.title("Confusion Matrix (Row-Normalized)")
    plt.xlabel("Predicted")
    plt.ylabel("Actual")
    plt.tight_layout()
    plt.savefig(out_dir / "confusion_matrix_normalized_true.png", dpi=200)
    plt.close()

    audit_df = X_test.copy().reset_index(drop=True)
    audit_df["y_true_id"] = y_test.reset_index(drop=True)
    audit_df["y_true_label"] = audit_df["y_true_id"].map(ID_TO_STATE)
    audit_df["y_pred_id"] = y_pred
    audit_df["y_pred_label"] = pd.Series(y_pred).map(ID_TO_STATE)
    for i, cname in enumerate(class_names):
        audit_df[f"proba_{cname}"] = y_proba[:, i]
    audit_df.to_csv(out_dir / "test_predictions_with_probabilities.csv", index=False)

    summary = {
        "dataset": {
            "csv_path": str(csv_path),
            "rows_total": int(len(df)),
            "features_shape": [int(X.shape[0]), int(X.shape[1])],
            "target_distribution_total": {ID_TO_STATE[int(k)]: int(v) for k, v in y.value_counts().sort_index().items()},
            "auto_labeled": bool(auto_labeled),
        },
        "evaluation_protocol": {
            "model": "SGDClassifier(loss=log_loss, alpha=0.0005, random_state=42)",
            "scaler": "StandardScaler",
            "epochs": epochs,
            "test_size": test_size,
            "random_state": random_state,
            "split": "train_test_split(stratify=y)",
            "classes": class_names,
        },
        "split_sizes": {"train_rows": int(len(y_train)), "test_rows": int(len(y_test))},
        "overall_metrics": {
            "accuracy": acc,
            "balanced_accuracy": bal_acc,
            "precision_micro": float(prec_micro),
            "recall_micro": float(rec_micro),
            "f1_micro": float(f1_micro),
            "precision_macro": float(prec_macro),
            "recall_macro": float(rec_macro),
            "f1_macro": float(f1_macro),
            "precision_weighted": float(prec_weighted),
            "recall_weighted": float(rec_weighted),
            "f1_weighted": float(f1_weighted),
            "matthews_corrcoef": mcc,
            "cohen_kappa": kappa,
            "log_loss": ll,
            "roc_auc_ovr_macro": roc_auc_ovr_macro,
            "roc_auc_ovo_macro": roc_auc_ovo_macro,
            "roc_auc_ovr_weighted": roc_auc_ovr_weighted,
            "roc_auc_ovo_weighted": roc_auc_ovo_weighted,
            "pr_auc_macro_mean": mean_ap_macro,
        },
        "average_precision_per_class": ap_per_class,
        "confusion_matrix": {
            "labels": class_names,
            "counts": cm.tolist(),
            "normalized_true": cm_norm_true.tolist(),
            "normalized_pred": cm_norm_pred.tolist(),
            "normalized_all": cm_norm_all.tolist(),
        },
        "per_class_rates_ovr": per_class_rates,
        "classification_report": cls_report_dict,
        "epoch_loss": epoch_losses,
    }

    (out_dir / "classification_report.txt").write_text(cls_report_text, encoding="utf-8")
    (out_dir / "metrics_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(f"Metrics package generated in: {out_dir}")
    print(f"Accuracy: {acc:.12f}")
    print("Confusion matrix (counts):")
    print(cm)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate full evaluation metrics for Smart Evacuation model.")
    parser.add_argument("--csv", required=True, help="Path to training/evaluation CSV")
    parser.add_argument("--out-dir", default="Code/metrics/full_evaluation", help="Output directory for artifacts")
    parser.add_argument("--epochs", type=int, default=50)
    parser.add_argument("--random-state", type=int, default=42)
    parser.add_argument("--test-size", type=float, default=0.2)
    args = parser.parse_args()

    run(
        csv_path=Path(args.csv),
        out_dir=Path(args.out_dir),
        epochs=args.epochs,
        random_state=args.random_state,
        test_size=args.test_size,
    )


if __name__ == "__main__":
    main()
