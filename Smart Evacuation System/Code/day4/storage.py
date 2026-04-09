from __future__ import annotations

from pathlib import Path
from typing import Any

import joblib

from .cirkit import CircuitSummary
from .config import ID_TO_STATE, MODEL_FEATURE_COLUMNS, STATE_TO_ID
from .model import EvacuationVirtualModel


def save_bundle(
    model_path: Path,
    model: EvacuationVirtualModel,
    circuit_summary: CircuitSummary,
    metrics: dict[str, Any],
) -> None:
    bundle = {
        "model": model.model,
        "scaler": model.scaler,
        "feature_columns": MODEL_FEATURE_COLUMNS,
        "state_to_id": STATE_TO_ID,
        "id_to_state": ID_TO_STATE,
        "circuit_summary": {
            "components_by_name": circuit_summary.components_by_name,
            "missing_required": circuit_summary.missing_required,
        },
        "train_metrics": metrics,
    }
    joblib.dump(bundle, model_path)


def load_bundle(model_path: Path | str) -> dict[str, Any]:
    model_path = Path(model_path)
    if not model_path.exists():
        raise FileNotFoundError(f"Model file not found: {model_path}")
    return joblib.load(model_path)


def predict_from_bundle(bundle: dict[str, Any], conditions: dict[str, Any]) -> dict[str, Any]:
    model = EvacuationVirtualModel()
    model.model = bundle["model"]
    model.scaler = bundle["scaler"]
    return model.predict_one(conditions)
