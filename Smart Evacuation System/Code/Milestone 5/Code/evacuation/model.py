from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.linear_model import SGDClassifier
from sklearn.metrics import accuracy_score, classification_report
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler

from .config import ID_TO_STATE, MODEL_FEATURE_COLUMNS
from .data_prep import prepare_training_dataframe, speaker_to_numeric


class EvacuationVirtualModel:
    """Train/predict evacuation state from sensor readings."""

    def __init__(self) -> None:
        self.scaler = StandardScaler()
        self.model = SGDClassifier(
            loss="log_loss",
            alpha=0.0005,
            random_state=42,
        )
        self.classes_ = np.array([0, 1, 2], dtype=int)

    def train(self, csv_path: Path, target_col: str = "target_state", epochs: int = 20) -> dict[str, Any]:
        df = pd.read_csv(csv_path)
        X, y, auto_labeled = prepare_training_dataframe(df, target_col=target_col)
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=0.2, random_state=42, stratify=y
        )

        X_train_scaled = self.scaler.fit_transform(X_train)
        X_test_scaled = self.scaler.transform(X_test)

        rng = np.random.default_rng(42)
        n = X_train_scaled.shape[0]
        epoch_losses: list[float] = []

        for epoch in range(epochs):
            idx = rng.permutation(n)
            X_epoch = X_train_scaled[idx]
            y_epoch = y_train.iloc[idx].to_numpy()
            self.model.partial_fit(X_epoch, y_epoch, classes=self.classes_)

            p = np.clip(self.model.predict_proba(X_epoch), 1e-9, 1.0)
            y_onehot = np.eye(len(self.classes_))[y_epoch]
            loss = float(-np.mean(np.sum(y_onehot * np.log(p), axis=1)))
            epoch_losses.append(loss)
            print(f"Epoch {epoch + 1}/{epochs} - loss: {loss:.5f}")

        y_pred = self.model.predict(X_test_scaled)
        acc = float(accuracy_score(y_test, y_pred))
        labels_present = sorted(np.unique(np.concatenate([y_test, y_pred])))
        report_dict = classification_report(
            y_test,
            y_pred,
            labels=labels_present,
            target_names=[ID_TO_STATE[i] for i in labels_present],
            zero_division=0,
            output_dict=True,
        )
        report = classification_report(
            y_test,
            y_pred,
            labels=labels_present,
            target_names=[ID_TO_STATE[i] for i in labels_present],
            zero_division=0,
        )
        macro_recall = float(report_dict["macro avg"]["recall"])
        macro_f1 = float(report_dict["macro avg"]["f1-score"])

        return {
            "rows": int(len(df)),
            "accuracy": acc,
            "macro_recall": macro_recall,
            "macro_f1": macro_f1,
            "epochs": int(epochs),
            "epoch_loss": epoch_losses,
            "classification_report": report,
            "classification_report_dict": report_dict,
            "labels_used": sorted([ID_TO_STATE[i] for i in sorted(y.unique().tolist())]),
            "auto_labeled": auto_labeled,
        }

    def predict_one(self, conditions: dict[str, Any]) -> dict[str, Any]:
        row = pd.DataFrame([conditions], columns=MODEL_FEATURE_COLUMNS)
        for c in MODEL_FEATURE_COLUMNS[:-1]:
            row[c] = pd.to_numeric(row[c], errors="coerce")
        row["speaker_on"] = row["speaker_on"].apply(speaker_to_numeric)
        row = row.replace([np.inf, -np.inf], np.nan)
        if row[MODEL_FEATURE_COLUMNS].isna().any().any():
            raise ValueError("Input conditions contain invalid values.")

        x = self.scaler.transform(row[MODEL_FEATURE_COLUMNS].astype(float))
        proba = self.model.predict_proba(x)[0]
        pred_id = int(np.argmax(proba))
        state = ID_TO_STATE[pred_id]
        outputs = self.state_to_virtual_outputs(state)
        return {
            "predicted_state": state,
            "confidence": float(np.max(proba)),
            "virtual_outputs": outputs,
        }

    @staticmethod
    def state_to_virtual_outputs(state: str) -> dict[str, Any]:
        if state == "EVACUATE":
            return {
                "red_led": 1,
                "green_led": 0,
                "buzzer_mode": "continuous",
                "speaker_on": 1,
                "evacuation_signal": 1,
            }
        if state == "CAUTION":
            return {
                "red_led": 1,
                "green_led": 0,
                "buzzer_mode": "intermittent",
                "speaker_on": 1,
                "evacuation_signal": 0,
            }
        return {
            "red_led": 0,
            "green_led": 1,
            "buzzer_mode": "off",
            "speaker_on": 0,
            "evacuation_signal": 0,
        }
