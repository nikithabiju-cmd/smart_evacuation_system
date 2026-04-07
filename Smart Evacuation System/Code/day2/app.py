#!/usr/bin/env python3
"""
Main interactive app for virtual evacuation prediction.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from evacuation.config import THINGSPEAK_DEFAULT_SERVER
from evacuation.model import EvacuationVirtualModel
from evacuation.rules import (
    build_thingspeak_fields,
    circuit_inputs_to_model_features,
    evaluate_firmware_state,
)
from evacuation.storage import load_bundle, predict_from_bundle
from evacuation.thingspeak import fetch_latest_from_thingspeak, upload_to_thingspeak

MODEL_PATH = Path("Code/trained_evacuation_model.joblib")
THINGSPEAK_API_KEY = "05F2R8EVL3CC31QD"
THINGSPEAK_SERVER = THINGSPEAK_DEFAULT_SERVER
THINGSPEAK_CHANNEL_ID = "3328061"
THINGSPEAK_READ_API_KEY = "MEA0BVFA9LIRWD8Z"


def ask_float(prompt: str) -> float:
    while True:
        try:
            return float(input(prompt).strip())
        except ValueError:
            print("Please enter a numeric value.")


def ask_binary(prompt: str) -> int:
    while True:
        text = input(prompt).strip().lower()
        if text in {"1", "high", "h", "true", "yes", "y", "on"}:
            return 1
        if text in {"0", "low", "l", "false", "no", "n", "off"}:
            return 0
        print("Enter HIGH/LOW or 1/0.")


def ask_yes_no(prompt: str) -> bool:
    while True:
        text = input(prompt).strip().lower()
        if text in {"y", "yes"}:
            return True
        if text in {"n", "no"}:
            return False
        print("Enter y or n.")


def run_manual(bundle: dict, upload: bool) -> None:
    print("Virtual Evacuation App (Manual Circuit Input)")
    print("Type circuit sensor inputs to predict SAFE / CAUTION / EVACUATE.\n")

    while True:
        circuit = {
            "temp_c": ask_float("Temperature C (DHT11): "),
            "hum_pct": ask_float("Humidity % (DHT11): "),
            "pir_a": ask_binary("PIR Zone A (HIGH/LOW): "),
            "pir_b": ask_binary("PIR Zone B (HIGH/LOW): "),
            "pir_c": ask_binary("PIR Zone C (HIGH/LOW): "),
            "sound_d": ask_binary("Sound Digital DO (HIGH/LOW): "),
            "sound_a": ask_float("Sound Analog AO (0-4095): "),
            "gas_a": ask_float("Gas Analog AO (0-4095): "),
            "gas_d": ask_binary("Gas Digital DO (HIGH/LOW): "),
        }
        _process_and_print(bundle, circuit, upload)
        if not ask_yes_no("Check another condition? (y/n): "):
            break


def _process_and_print(bundle: dict, circuit: dict, upload: bool) -> None:
    sensor_payload = {
        "temp_c": circuit["temp_c"],
        "hum_pct": circuit["hum_pct"],
        "pir_a": circuit["pir_a"],
        "pir_b": circuit["pir_b"],
        "pir_c": circuit["pir_c"],
        "sound_d": circuit["sound_d"],
        "sound_a": circuit["sound_a"],
        "gas_a": circuit["gas_a"],
        "gas_d": circuit["gas_d"],
    }

    model_features = circuit_inputs_to_model_features(**sensor_payload)
    ml_result = predict_from_bundle(bundle, model_features)
    fw_state = evaluate_firmware_state(**sensor_payload)

    # Final decision follows firmware rules exactly; ML is shown as advisory.
    final_state = fw_state
    final_outputs = EvacuationVirtualModel.state_to_virtual_outputs(final_state)
    fields = build_thingspeak_fields(
        temp_c=circuit["temp_c"],
        hum_pct=circuit["hum_pct"],
        pir_a=circuit["pir_a"],
        pir_b=circuit["pir_b"],
        pir_c=circuit["pir_c"],
        sound_a=circuit["sound_a"],
        state=final_state,
        gas_a=circuit["gas_a"],
    )

    result = {
        "source": "thingspeak" if "timestamp" in circuit else "manual",
        "timestamp": circuit.get("timestamp"),
        "entry_id": circuit.get("entry_id"),
        "firmware_rule_state": fw_state,
        "ml_predicted_state": ml_result["predicted_state"],
        "ml_confidence": ml_result["confidence"],
        "final_state": final_state,
        "virtual_outputs": final_outputs,
        "thingspeak_fields": fields,
    }

    print("\nPrediction:")
    print(json.dumps(result, indent=2))
    print()

    if upload:
        ok, msg = upload_to_thingspeak(
            api_key=THINGSPEAK_API_KEY,
            fields=fields,
            server=THINGSPEAK_SERVER,
        )
        print(f"[ThingSpeak] {msg}")
        if not ok:
            print("[ThingSpeak] Check internet/API key/channel write permissions.")
        print()


def run_thingspeak_polling(bundle: dict, channel_id: str, read_api_key: str, poll_seconds: int, upload: bool) -> None:
    print("Virtual Evacuation App (ThingSpeak Input Mode)")
    print(f"Reading from ThingSpeak channel: {channel_id}")
    print(f"Polling every {poll_seconds} seconds. Press Ctrl+C to stop.\n")
    while True:
        try:
            circuit = fetch_latest_from_thingspeak(channel_id=channel_id, read_api_key=read_api_key)
            _process_and_print(bundle, circuit, upload)
        except KeyboardInterrupt:
            raise
        except Exception as exc:
            print(f"[ThingSpeak] Read failed: {exc}\n")
        time.sleep(max(1, poll_seconds))


def main() -> None:
    parser = argparse.ArgumentParser(description="Virtual evacuation app (manual or ThingSpeak input).")
    parser.add_argument(
        "--input-mode",
        choices=["thingspeak", "manual"],
        default="thingspeak",
        help="Input source for conditions.",
    )
    parser.add_argument("--channel-id", default=THINGSPEAK_CHANNEL_ID, help="ThingSpeak channel ID for read mode.")
    parser.add_argument("--read-api-key", default=THINGSPEAK_READ_API_KEY, help="ThingSpeak read API key (optional).")
    parser.add_argument("--poll-seconds", type=int, default=15, help="Polling interval in seconds.")
    parser.add_argument(
        "--upload",
        action="store_true",
        help="Upload predicted final state back to ThingSpeak using configured write API key.",
    )
    args = parser.parse_args()

    if not MODEL_PATH.exists():
        print(f"Model not found: {MODEL_PATH}")
        print("Train first:")
        print(
            "python Code/virtual_evacuation_model.py train "
            "--ckt Code/main.ckt --csv Code/smart_evacuation_dataset_realtime.csv "
            "--epochs 20 --model-out Code/trained_evacuation_model.joblib"
        )
        return

    bundle = load_bundle(MODEL_PATH)
    if args.input_mode == "manual":
        run_manual(bundle, upload=args.upload)
        return

    if not args.channel_id:
        print("ThingSpeak input mode needs a channel ID.")
        print("Run with: python Code/app.py --channel-id <YOUR_CHANNEL_ID> [--read-api-key <READ_KEY>]")
        return

    run_thingspeak_polling(
        bundle=bundle,
        channel_id=args.channel_id,
        read_api_key=args.read_api_key,
        poll_seconds=args.poll_seconds,
        upload=args.upload,
    )


if __name__ == "__main__":
    main()
