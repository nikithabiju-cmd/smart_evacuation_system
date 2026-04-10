from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from .config import MODEL_FEATURE_COLUMNS, STATE_TO_ID


def speaker_to_numeric(value: Any) -> float:
    text = str(value).strip().lower()
    return 1.0 if text in {"1", "on", "true", "yes", "y"} else 0.0


def to_state_label(value: Any) -> str:
    text = str(value).strip().upper()
    mapping = {
        "SAFE": "SAFE",
        "NORMAL": "SAFE",
        "STAY": "SAFE",
        "CAUTION": "CAUTION",
        "WARNING": "CAUTION",
        "PREPARE": "CAUTION",
        "EVACUATE": "EVACUATE",
        "ALERT": "EVACUATE",
        "DANGER": "EVACUATE",
    }
    if text not in mapping:
        raise ValueError(f"Unsupported target label: {value}")
    return mapping[text]


def auto_label_from_realtime(df: pd.DataFrame) -> pd.Series:
    evac = (
        (df["temperature_C"] >= 58)
        | (df["smoke_ppm"] >= 180)
        | (df["co_ppm"] >= 60)
        | (df["gas_level_ppm"] >= 800)
    )
    caution = (
        (df["temperature_C"] >= 45)
        | (df["smoke_ppm"] >= 100)
        | (df["co_ppm"] >= 30)
        | (df["gas_level_ppm"] >= 500)
        | (df["pir_level"] >= 50)
        | (df["sound_level_dB"] >= 65)
    )
    labels = pd.Series(np.full(len(df), "SAFE"), index=df.index)
    labels[caution] = "CAUTION"
    labels[evac] = "EVACUATE"
    return labels


def prepare_training_dataframe(df: pd.DataFrame, target_col: str) -> tuple[pd.DataFrame, pd.Series, bool]:
    """Normalize supported CSV schemas into model features + y labels."""
    auto_labeled = False

    realtime_required = {
        "pir_level",
        "gas_level_ppm",
        "sound_level_dB",
        "temperature_C",
        "humidity_percent",
        "smoke_ppm",
        "co_ppm",
        "speaker_on",
    }
    occupancy_required = {
        "pir_level",
        "gas_level_ppm",
        "sound_level_dB",
        "temperature_C",
        "occupancy_count",
        "speaker_on",
    }
    legacy_required = {"temp_c", "humidity_pct", "sound_level", "pir_zone_1", "pir_zone_2", "pir_zone_3"}

    if realtime_required.issubset(set(df.columns)):
        xdf = df.copy()
        for c in MODEL_FEATURE_COLUMNS[:-1]:
            xdf[c] = pd.to_numeric(xdf[c], errors="coerce")
        xdf["speaker_on"] = xdf["speaker_on"].apply(speaker_to_numeric)
        xdf = xdf[MODEL_FEATURE_COLUMNS]

        if target_col in df.columns:
            y_labels = df[target_col].apply(to_state_label)
        elif "vacate_condition" in df.columns:
            y_labels = df["vacate_condition"].apply(to_state_label)
        elif "scenario" in df.columns:
            y_labels = df["scenario"].apply(to_state_label)
        else:
            y_labels = auto_label_from_realtime(df)
            auto_labeled = True

    elif occupancy_required.issubset(set(df.columns)):
        xdf = pd.DataFrame(
            {
                "pir_level": pd.to_numeric(df["pir_level"], errors="coerce"),
                "gas_level_ppm": pd.to_numeric(df["gas_level_ppm"], errors="coerce"),
                "sound_level_dB": pd.to_numeric(df["sound_level_dB"], errors="coerce"),
                "temperature_C": pd.to_numeric(df["temperature_C"], errors="coerce"),
                "humidity_percent": 50.0,
                "smoke_ppm": pd.to_numeric(df["gas_level_ppm"], errors="coerce") * 0.2,
                "co_ppm": pd.to_numeric(df["gas_level_ppm"], errors="coerce") * 0.05,
                "speaker_on": df["speaker_on"].apply(speaker_to_numeric),
            }
        )
        occ = pd.to_numeric(df["occupancy_count"], errors="coerce").fillna(0.0)
        xdf["pir_level"] = np.clip(xdf["pir_level"] + occ * 2.0, 0, 100)

        if target_col in df.columns:
            y_labels = df[target_col].apply(to_state_label)
        elif "vacate_condition" in df.columns:
            y_labels = df["vacate_condition"].apply(to_state_label)
        elif "scenario" in df.columns:
            y_labels = df["scenario"].apply(to_state_label)
        else:
            auto_labeled = True
            y_labels = auto_label_from_realtime(
                pd.DataFrame(
                    {
                        "temperature_C": xdf["temperature_C"],
                        "smoke_ppm": xdf["smoke_ppm"],
                        "co_ppm": xdf["co_ppm"],
                        "gas_level_ppm": xdf["gas_level_ppm"],
                        "pir_level": xdf["pir_level"],
                        "sound_level_dB": xdf["sound_level_dB"],
                    }
                )
            )

    elif legacy_required.issubset(set(df.columns)):
        xdf = pd.DataFrame(
            {
                "pir_level": pd.to_numeric(
                    (df["pir_zone_1"] + df["pir_zone_2"] + df["pir_zone_3"]) * (100.0 / 3.0), errors="coerce"
                ),
                "gas_level_ppm": 0.0,
                "sound_level_dB": pd.to_numeric(df["sound_level"], errors="coerce"),
                "temperature_C": pd.to_numeric(df["temp_c"], errors="coerce"),
                "humidity_percent": pd.to_numeric(df["humidity_pct"], errors="coerce"),
                "smoke_ppm": 0.0,
                "co_ppm": 0.0,
                "speaker_on": 0.0,
            }
        )
        mask = xdf["sound_level_dB"] <= 1.0
        xdf.loc[mask, "sound_level_dB"] = xdf.loc[mask, "sound_level_dB"] * 100.0

        if target_col in df.columns:
            y_labels = df[target_col].apply(to_state_label)
        else:
            auto_labeled = True
            zones = df[["pir_zone_1", "pir_zone_2", "pir_zone_3"]].sum(axis=1)
            y_labels = pd.Series(np.full(len(df), "SAFE"), index=df.index)
            y_labels[(xdf["temperature_C"] >= 45) | (zones == 1)] = "CAUTION"
            y_labels[(xdf["temperature_C"] >= 55) | (zones >= 2)] = "EVACUATE"
    else:
        raise ValueError(
            "CSV schema not recognized. Expected realtime, occupancy, or legacy sample schema."
        )

    xdf["humidity_percent"] = xdf["humidity_percent"].clip(0, 100)
    xdf["pir_level"] = xdf["pir_level"].clip(0, 100)
    xdf = xdf.replace([np.inf, -np.inf], np.nan)
    if xdf[MODEL_FEATURE_COLUMNS].isna().any().any():
        raise ValueError("Feature columns contain invalid/empty values after preprocessing.")

    y = y_labels.map(STATE_TO_ID)
    if y.isna().any():
        bad = sorted(y_labels[y.isna()].astype(str).unique().tolist())
        raise ValueError(f"Unsupported labels after mapping: {bad}")

    return xdf[MODEL_FEATURE_COLUMNS].astype(float), y.astype(int), auto_labeled
