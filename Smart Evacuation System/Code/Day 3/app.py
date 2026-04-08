#!/usr/bin/env python3
"""
Main interactive app for virtual evacuation prediction.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from flask import Flask, jsonify, render_template, request

from evacuation.config import THINGSPEAK_DEFAULT_SERVER
from evacuation.incident_log import IncidentLogger
from evacuation.model import EvacuationVirtualModel
from evacuation.rules import (
    build_thingspeak_fields,
    circuit_inputs_to_model_features,
    evaluate_firmware_state,
)
from evacuation.storage import load_bundle, predict_from_bundle
from evacuation.thingspeak import fetch_latest_from_thingspeak, upload_to_thingspeak

APP_DIR = Path(__file__).resolve().parent
MODEL_PATH = APP_DIR / "trained_evacuation_model.joblib"
THINGSPEAK_API_KEY = "05F2R8EVL3CC31QD"
THINGSPEAK_SERVER = THINGSPEAK_DEFAULT_SERVER
THINGSPEAK_CHANNEL_ID = "3328061"
THINGSPEAK_READ_API_KEY = "MEA0BVFA9LIRWD8Z"
WEB_HOST = "localhost"
WEB_PORT = 5000
LOG_DIR = APP_DIR / "logs"
INCIDENT_SQLITE_PATH = LOG_DIR / "incident_logs.db"
INCIDENT_CSV_PATH = LOG_DIR / "incident_logs.csv"
INCIDENT_LOGGER = IncidentLogger(sqlite_path=INCIDENT_SQLITE_PATH, csv_path=INCIDENT_CSV_PATH)


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


def analyze_prediction(bundle: dict, circuit: dict) -> tuple[dict, dict[str, str]]:
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
    INCIDENT_LOGGER.log(circuit=circuit, result=result)
    return result, fields


def run_manual(bundle: dict, upload: bool) -> None:
    print("Virtual Evacuation App (Manual Circuit Input)")
    print("Type circuit sensor inputs to predict SAFE / CAUTION / EVACUATE.\n")

    while True:
        circuit = {
            "temp_c": ask_float("Temperature C (DHT11): "),
            "hum_pct": ask_float("Humidity % (DHT11): "),
            "pir_a": ask_binary("PIR Sensor A (HIGH/LOW): "),
            "pir_b": ask_binary("PIR Sensor B (HIGH/LOW): "),
            "pir_c": ask_binary("PIR Sensor C (HIGH/LOW): "),
            "sound_d": ask_binary("Sound Digital DO (HIGH/LOW): "),
            "sound_a": ask_float("Sound Analog AO (0-4095): "),
            "gas_a": ask_float("Gas Analog AO (0-4095): "),
            "gas_d": ask_binary("Gas Digital DO (HIGH/LOW): "),
        }
        _process_and_print(bundle, circuit, upload)
        if not ask_yes_no("Check another condition? (y/n): "):
            break


def _process_and_print(bundle: dict, circuit: dict, upload: bool) -> None:
    result, fields = analyze_prediction(bundle, circuit)

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


def create_web_app(bundle: dict) -> Flask:
    flask_app = Flask(
        __name__,
        template_folder=str(APP_DIR / "templates"),
        static_folder=str(APP_DIR / "static"),
    )
    state = {
        "bundle": bundle,
        "channel_id": THINGSPEAK_CHANNEL_ID,
        "read_api_key": THINGSPEAK_READ_API_KEY,
    }

    @flask_app.get("/")
    def index():
        return render_template("index.html")

    @flask_app.get("/api/config")
    def get_config():
        return jsonify(
            {
                "channel_id": state["channel_id"],
                "read_api_key": state["read_api_key"],
            }
        )

    @flask_app.get("/api/history")
    def get_history():
        limit = request.args.get("limit", default=20, type=int)
        return jsonify(
            {
                "counts": INCIDENT_LOGGER.summary_counts(),
                "recent": INCIDENT_LOGGER.recent(limit=limit),
            }
        )

    @flask_app.post("/api/live/poll")
    def live_poll():
        payload = request.get_json(silent=True) or {}
        channel_id = str(payload.get("channel_id") or state["channel_id"])
        read_api_key = str(payload.get("read_api_key") or state["read_api_key"])

        circuit = fetch_latest_from_thingspeak(channel_id=channel_id, read_api_key=read_api_key)
        state["channel_id"] = channel_id
        state["read_api_key"] = read_api_key

        result, fields = analyze_prediction(state["bundle"], circuit)
        if payload.get("upload"):
            ok, msg = upload_to_thingspeak(
                api_key=THINGSPEAK_API_KEY,
                fields=fields,
                server=THINGSPEAK_SERVER,
            )
            result["thingspeak_upload"] = {"ok": ok, "message": msg}
        return jsonify(result)

    @flask_app.post("/api/predict")
    def predict():
        payload = request.get_json(force=True) or {}
        use_thingspeak = bool(payload.get("use_thingspeak"))

        if use_thingspeak:
            channel_id = str(payload.get("channel_id") or state["channel_id"])
            read_api_key = str(payload.get("read_api_key") or state["read_api_key"])
            circuit = fetch_latest_from_thingspeak(channel_id=channel_id, read_api_key=read_api_key)
            state["channel_id"] = channel_id
            state["read_api_key"] = read_api_key
        else:
            raw = payload.get("sensors", {})
            try:
                circuit = {
                    "temp_c": float(raw.get("temp_c", 0)),
                    "hum_pct": float(raw.get("hum_pct", 0)),
                    "pir_a": int(raw.get("pir_a", 0)),
                    "pir_b": int(raw.get("pir_b", 0)),
                    "pir_c": int(raw.get("pir_c", 0)),
                    "sound_d": int(raw.get("sound_d", 0)),
                    "sound_a": float(raw.get("sound_a", 0)),
                    "gas_a": float(raw.get("gas_a", 0)),
                    "gas_d": int(raw.get("gas_d", 0)),
                }
            except (TypeError, ValueError) as exc:
                return jsonify({"error": f"Invalid sensor payload: {exc}"}), 400

        result, fields = analyze_prediction(state["bundle"], circuit)
        if payload.get("upload"):
            ok, msg = upload_to_thingspeak(
                api_key=THINGSPEAK_API_KEY,
                fields=fields,
                server=THINGSPEAK_SERVER,
            )
            result["thingspeak_upload"] = {"ok": ok, "message": msg}
        return jsonify(result)

    return flask_app


def run_web_server(bundle: dict, host: str, port: int) -> None:
    flask_app = create_web_app(bundle)
    print(f"Web UI running at http://{host}:{port}")
    flask_app.run(host=host, port=port, debug=False)


def main() -> None:
    parser = argparse.ArgumentParser(description="Virtual evacuation app (manual, ThingSpeak, or web UI).")
    parser.add_argument(
        "--input-mode",
        choices=["thingspeak", "manual", "web"],
        default="thingspeak",
        help="Input source for conditions.",
    )
    parser.add_argument("--channel-id", default=THINGSPEAK_CHANNEL_ID, help="ThingSpeak channel ID for read mode.")
    parser.add_argument("--read-api-key", default=THINGSPEAK_READ_API_KEY, help="ThingSpeak read API key (optional).")
    parser.add_argument("--poll-seconds", type=int, default=15, help="Polling interval in seconds.")
    parser.add_argument("--host", default=WEB_HOST, help="Host for web mode.")
    parser.add_argument("--port", type=int, default=WEB_PORT, help="Port for web mode.")
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
            "--ckt Code/main.ckt --csv Code/smart_evacuation_dataset_with_occupancy.csv "
            "--epochs 20 --model-out Code/trained_evacuation_model.joblib"
        )
        return

    bundle = load_bundle(MODEL_PATH)

    if args.input_mode == "web":
        run_web_server(bundle=bundle, host=args.host, port=args.port)
        return

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
