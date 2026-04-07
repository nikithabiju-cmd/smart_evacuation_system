from __future__ import annotations

import numpy as np

from .config import (
    GAS_CAUTION,
    GAS_HIGH_RISK,
    HUMIDITY_HIGH,
    SOUND_CAUTION,
    SOUND_HIGH_RISK,
    TEMP_CAUTION,
    TEMP_HIGH_RISK,
)


def state_to_level(state: str) -> int:
    mapping = {"SAFE": 0, "CAUTION": 1, "EVACUATE": 2}
    return mapping[state]


def level_to_state(level: int) -> str:
    mapping = {0: "SAFE", 1: "CAUTION", 2: "EVACUATE"}
    return mapping[int(level)]


def evaluate_firmware_state(
    temp_c: float,
    hum_pct: float,
    pir_a: int,
    pir_b: int,
    pir_c: int,
    sound_d: int,
    sound_a: float,
    gas_a: float,
    gas_d: int,
) -> str:
    """Exact rule mirror of the provided Arduino evaluateState function."""
    if temp_c > TEMP_HIGH_RISK:
        return "EVACUATE"
    if sound_a > SOUND_HIGH_RISK:
        return "EVACUATE"
    if gas_a > GAS_HIGH_RISK:
        return "EVACUATE"
    if gas_d == 1:
        return "EVACUATE"
    if (pir_a and pir_b) or (pir_a and pir_c) or (pir_b and pir_c) or (pir_a and pir_b and pir_c):
        return "EVACUATE"

    if temp_c > TEMP_CAUTION:
        return "CAUTION"
    if hum_pct > HUMIDITY_HIGH:
        return "CAUTION"
    if sound_a > SOUND_CAUTION:
        return "CAUTION"
    if sound_d == 1:
        return "CAUTION"
    if gas_a > GAS_CAUTION:
        return "CAUTION"
    if pir_a or pir_b or pir_c:
        return "CAUTION"

    return "SAFE"


def circuit_inputs_to_model_features(
    temp_c: float,
    hum_pct: float,
    pir_a: int,
    pir_b: int,
    pir_c: int,
    sound_d: int,
    sound_a: float,
    gas_a: float,
    gas_d: int,
) -> dict[str, float]:
    pir_level = (float(pir_a) + float(pir_b) + float(pir_c)) * (100.0 / 3.0)
    return {
        "pir_level": float(np.clip(pir_level, 0, 100)),
        "gas_level_ppm": float(gas_a),
        "sound_level_dB": float(sound_a),
        "temperature_C": float(temp_c),
        "humidity_percent": float(hum_pct),
        "smoke_ppm": float(gas_a) * 0.2,
        "co_ppm": float(gas_a) * 0.05,
        "speaker_on": 1.0 if int(sound_d) == 1 or int(gas_d) == 1 else 0.0,
    }


def build_thingspeak_fields(
    temp_c: float,
    hum_pct: float,
    pir_a: int,
    pir_b: int,
    pir_c: int,
    sound_a: float,
    state: str,
    gas_a: float,
) -> dict[str, str]:
    return {
        "field1": f"{float(temp_c):.2f}",
        "field2": f"{float(hum_pct):.2f}",
        "field3": str(int(pir_a)),
        "field4": str(int(pir_b)),
        "field5": str(int(pir_c)),
        "field6": str(int(sound_a)),
        "field7": str(state_to_level(state)),
        "field8": str(int(gas_a)),
    }
