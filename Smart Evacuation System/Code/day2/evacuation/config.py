from __future__ import annotations

STATE_TO_ID = {"SAFE": 0, "CAUTION": 1, "EVACUATE": 2}
ID_TO_STATE = {v: k for k, v in STATE_TO_ID.items()}

MODEL_FEATURE_COLUMNS = [
    "pir_level",
    "gas_level_ppm",
    "sound_level_dB",
    "temperature_C",
    "humidity_percent",
    "smoke_ppm",
    "co_ppm",
    "speaker_on",
]

# Firmware-aligned thresholds from ESP32 sketch.
TEMP_HIGH_RISK = 50.0
TEMP_CAUTION = 35.0
HUMIDITY_HIGH = 80.0
SOUND_HIGH_RISK = 3000.0
SOUND_CAUTION = 1500.0
GAS_HIGH_RISK = 2500.0
GAS_CAUTION = 1000.0

THINGSPEAK_DEFAULT_SERVER = "http://api.thingspeak.com/update"
