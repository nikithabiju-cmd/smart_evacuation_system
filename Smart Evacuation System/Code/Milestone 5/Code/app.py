#!/usr/bin/env python3
"""
Main interactive app for virtual evacuation prediction.
"""

from __future__ import annotations

import argparse
import json
import os
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
FLOOR_READ_API_KEYS_DEFAULT = ",".join(
    [
        "TJH75U3FO9R0C8C9",  # floor_0 (ground)
        "MEA0BVFA9LIRWD8Z",  # floor_1
        "KDG5KPHE7C88AMMD",  # floor_2
    ]
)
FLOOR_CHANNEL_IDS_DEFAULT = ",".join(
    [
        "3333445",  # floor_0 (ground)
        "3328061",  # floor_1
        "3333277",  # floor_2
    ]
)
WEB_HOST = "localhost"
WEB_PORT = 5000
LOG_DIR = APP_DIR / "logs"
INCIDENT_SQLITE_PATH = LOG_DIR / "incident_logs.db"
INCIDENT_CSV_PATH = LOG_DIR / "incident_logs.csv"
INCIDENT_SQLSERVER_CONN_STR = os.getenv("INCIDENT_SQLSERVER_CONN_STR", "").strip()
DEFAULT_SQLSERVER_CONN_STR = (
    "DRIVER={ODBC Driver 18 for SQL Server};"
    "SERVER=localhost\\SQLEXPRESS;"
    "DATABASE=SmartEvacuation;"
    "Trusted_Connection=yes;"
    "TrustServerCertificate=yes;"
)
FLOOR_EXPORT_XLSX_PATH = LOG_DIR / "incident_logs_by_floor.xlsx"


def _build_incident_logger() -> IncidentLogger:
    sqlserver_conn_str = INCIDENT_SQLSERVER_CONN_STR or DEFAULT_SQLSERVER_CONN_STR
    try:
        return IncidentLogger(sqlserver_conn_str=sqlserver_conn_str, csv_path=INCIDENT_CSV_PATH)
    except Exception as exc:
        print(f"[IncidentLog] SQL Server unavailable ({exc}). Falling back to SQLite: {INCIDENT_SQLITE_PATH}")
        return IncidentLogger(sqlite_path=INCIDENT_SQLITE_PATH, csv_path=INCIDENT_CSV_PATH)


INCIDENT_LOGGER = _build_incident_logger()


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


def analyze_prediction(
    bundle: dict,
    circuit: dict,
    floor_id: int | None = None,
    channel_id: str | None = None,
) -> tuple[dict, dict[str, str]]:
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
    upload_fields = build_thingspeak_fields(
        temp_c=circuit["temp_c"],
        hum_pct=circuit["hum_pct"],
        pir_a=circuit["pir_a"],
        pir_b=circuit["pir_b"],
        pir_c=circuit["pir_c"],
        sound_a=circuit["sound_a"],
        state=final_state,
        gas_a=circuit["gas_a"],
    )
    raw_fields = circuit.get("raw_fields") or {}

    result = {
        "source": "thingspeak" if "timestamp" in circuit else "manual",
        "floor_id": floor_id,
        "channel_id": channel_id,
        "timestamp": circuit.get("timestamp"),
        "entry_id": circuit.get("entry_id"),
        "firmware_rule_state": fw_state,
        "ml_predicted_state": ml_result["predicted_state"],
        "ml_confidence": ml_result["confidence"],
        "final_state": final_state,
        "virtual_outputs": final_outputs,
        "thingspeak_fields": raw_fields if raw_fields else upload_fields,
        "thingspeak_upload_fields": upload_fields,
    }
    INCIDENT_LOGGER.log(circuit=circuit, result=result, floor_id=floor_id, channel_id=channel_id)
    try:
        export_floor_sheets(FLOOR_EXPORT_XLSX_PATH)
    except Exception as exc:
        print(f"[Export] floor workbook update failed: {exc}")
    floor_label = floor_id if floor_id is not None else "-"
    print(
        f"[LIVE] floor={floor_label} channel={channel_id or '-'} "
        f"temp={circuit.get('temp_c')} hum={circuit.get('hum_pct')} "
        f"gas={circuit.get('gas_a')} sound={circuit.get('sound_a')} state={final_state}"
    )
    return result, upload_fields


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


def _process_and_print(
    bundle: dict,
    circuit: dict,
    upload: bool,
    floor_id: int | None = None,
    channel_id: str | None = None,
) -> None:
    result, fields = analyze_prediction(bundle, circuit, floor_id=floor_id, channel_id=channel_id)

    print("\nPrediction:")
    if floor_id is not None:
        print(f"Floor: {floor_id} | Channel: {channel_id}")
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
            _process_and_print(bundle, circuit, upload, floor_id=0, channel_id=channel_id)
        except KeyboardInterrupt:
            raise
        except Exception as exc:
            print(f"[ThingSpeak] Read failed: {exc}\n")
        time.sleep(max(1, poll_seconds))


def _parse_csv_arg(text: str) -> list[str]:
    return [part.strip() for part in text.split(",")]


def _build_floor_configs(channel_ids_csv: str, read_api_keys_csv: str) -> list[dict[str, str | int]]:
    channel_ids = _parse_csv_arg(channel_ids_csv)
    read_api_keys = _parse_csv_arg(read_api_keys_csv)

    if len(channel_ids) != 3:
        raise ValueError("Expected exactly 3 channel IDs for floors 0, 1, and 2.")
    if len(read_api_keys) < 3:
        read_api_keys.extend([""] * (3 - len(read_api_keys)))

    floor_configs: list[dict[str, str | int]] = []
    for floor_id in range(3):
        channel_id = channel_ids[floor_id]
        if not channel_id:
            raise ValueError(f"Missing channel ID for floor {floor_id}.")
        floor_configs.append(
            {
                "floor_id": floor_id,
                "channel_id": channel_id,
                "read_api_key": read_api_keys[floor_id] if floor_id < len(read_api_keys) else "",
            }
        )
    return floor_configs


def run_multi_floor_thingspeak_polling(
    bundle: dict,
    floor_configs: list[dict[str, str | int]],
    poll_seconds: int,
    upload: bool,
    auto_export: bool = True,
    export_path: Path = FLOOR_EXPORT_XLSX_PATH,
) -> None:
    print("Virtual Evacuation App (ThingSpeak Multi-Floor Input Mode)")
    print("Configured floors and channels:")
    for cfg in floor_configs:
        print(f"- Floor {cfg['floor_id']}: channel {cfg['channel_id']}")
    print(f"Polling every {poll_seconds} seconds. Press Ctrl+C to stop.")
    if auto_export:
        print(f"Auto-export to Excel enabled: {export_path}")
    print()

    while True:
        try:
            for cfg in floor_configs:
                floor_id = int(cfg["floor_id"])
                channel_id = str(cfg["channel_id"])
                read_api_key = str(cfg["read_api_key"])
                circuit = fetch_latest_from_thingspeak(channel_id=channel_id, read_api_key=read_api_key)
                _process_and_print(
                    bundle,
                    circuit,
                    upload,
                    floor_id=floor_id,
                    channel_id=channel_id,
                )
            if auto_export:
                export_floor_sheets(export_path)
        except KeyboardInterrupt:
            raise
        except Exception as exc:
            print(f"[ThingSpeak Multi-Floor] Read failed: {exc}\n")
        time.sleep(max(1, poll_seconds))


def export_floor_sheets(output_path: Path) -> Path:
    return INCIDENT_LOGGER.export_floor_workbook(output_path=output_path, floors=[0, 1, 2])


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
        "last_seen_entries": {},
    }

    @flask_app.get("/")
    def index():
        return render_template("index.html")

    @flask_app.after_request
    def add_no_cache_headers(response):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response

    @flask_app.get("/api/config")
    def get_config():
        try:
            floor_configs = _build_floor_configs(FLOOR_CHANNEL_IDS_DEFAULT, FLOOR_READ_API_KEYS_DEFAULT)
        except Exception:
            floor_configs = []
        return jsonify(
            {
                "channel_id": state["channel_id"],
                "read_api_key": state["read_api_key"],
                "incident_log_backend": INCIDENT_LOGGER.backend,
                "floor_configs": floor_configs,
            }
        )

    @flask_app.get("/api/floors")
    def get_floors():
        latest_rows = INCIDENT_LOGGER.latest_per_floor([0, 1, 2])
        by_floor = {int(row.get("floor_id")): row for row in latest_rows if row.get("floor_id") is not None}
        floors = []
        for floor_id in [0, 1, 2]:
            row = by_floor.get(floor_id)
            floors.append(
                {
                    "floor_id": floor_id,
                    "label": f"Floor {floor_id}",
                    "channel_id": row.get("channel_id") if row else None,
                    "entry_id": row.get("entry_id") if row else None,
                    "logged_at_utc": row.get("logged_at_utc") if row else None,
                    "timestamp": row.get("timestamp") if row else None,
                    "source": row.get("source") if row else None,
                    "temp_c": row.get("temp_c") if row else None,
                    "hum_pct": row.get("hum_pct") if row else None,
                    "gas_a": row.get("gas_a") if row else None,
                    "gas_d": row.get("gas_d") if row else None,
                    "sound_a": row.get("sound_a") if row else None,
                    "sound_d": row.get("sound_d") if row else None,
                    "final_state": row.get("final_state") if row else None,
                    "firmware_rule_state": row.get("firmware_rule_state") if row else None,
                    "ml_predicted_state": row.get("ml_predicted_state") if row else None,
                    "ml_confidence": row.get("ml_confidence") if row else None,
                    "virtual_outputs": row.get("virtual_outputs") if row else {},
                    "thingspeak_fields": row.get("thingspeak_fields") if row else {},
                    "raw_event": row if row else {},
                    "id": row.get("id") if row else None,
                }
            )
        return jsonify(floors)

    @flask_app.get("/api/history")
    def get_history():
        limit = request.args.get("limit", default=20, type=int)
        return jsonify(INCIDENT_LOGGER.recent(limit=limit))

    @flask_app.get("/api/stats")
    def get_stats():
        counts = INCIDENT_LOGGER.summary_counts()
        return jsonify(
            {
                "safe_count": int(counts.get("SAFE", 0)),
                "caution_count": int(counts.get("CAUTION", 0)),
                "evacuate_count": int(counts.get("EVACUATE", 0)),
                "total": int(counts.get("TOTAL", 0)),
            }
        )

    @flask_app.get("/api/live/extract")
    def extract_live_data():
        after_id = request.args.get("after_id", default=0, type=int)
        limit = request.args.get("limit", default=200, type=int)
        floor_id = request.args.get("floor_id", default=None, type=int)
        return jsonify(
            INCIDENT_LOGGER.stream(
                after_id=after_id,
                limit=limit,
                floor_id=floor_id,
            )
        )

    @flask_app.post("/api/live/poll")
    def live_poll():
        payload = request.get_json(silent=True) or {}
        channel_id = str(payload.get("channel_id") or state["channel_id"])
        read_api_key = str(payload.get("read_api_key") or state["read_api_key"])
        floor_id = payload.get("floor_id", None)
        if floor_id is not None:
            try:
                floor_id = int(floor_id)
            except (TypeError, ValueError):
                return jsonify({"error": "floor_id must be an integer"}), 400

        circuit = fetch_latest_from_thingspeak(channel_id=channel_id, read_api_key=read_api_key)
        entry_key = f"{channel_id}"
        entry_id = str(circuit.get("entry_id") or "")
        if entry_id and state["last_seen_entries"].get(entry_key) == entry_id:
            return jsonify(
                {
                    "status": "stale",
                    "message": f"No new ThingSpeak entry for channel {channel_id}",
                    "floor_id": floor_id,
                    "channel_id": channel_id,
                    "entry_id": entry_id,
                }
            )
        state["channel_id"] = channel_id
        state["read_api_key"] = read_api_key

        result, fields = analyze_prediction(state["bundle"], circuit, floor_id=floor_id, channel_id=channel_id)
        if entry_id:
            state["last_seen_entries"][entry_key] = entry_id
        if payload.get("upload"):
            ok, msg = upload_to_thingspeak(
                api_key=THINGSPEAK_API_KEY,
                fields=fields,
                server=THINGSPEAK_SERVER,
            )
            result["thingspeak_upload"] = {"ok": ok, "message": msg}
        return jsonify(result)

    @flask_app.post("/api/live/poll-multi")
    def live_poll_multi():
        payload = request.get_json(silent=True) or {}
        floor_configs = payload.get("floor_configs")
        if not isinstance(floor_configs, list) or len(floor_configs) == 0:
            return jsonify({"error": "floor_configs must be a non-empty list"}), 400

        upload = bool(payload.get("upload"))
        results: list[dict] = []
        errors: list[dict] = []
        for cfg in floor_configs:
            if not isinstance(cfg, dict):
                continue
            try:
                floor_id = int(cfg.get("floor_id"))
            except (TypeError, ValueError):
                continue
            channel_id = str(cfg.get("channel_id") or "").strip()
            read_api_key = str(cfg.get("read_api_key") or "").strip()
            if not channel_id:
                continue

            try:
                circuit = fetch_latest_from_thingspeak(channel_id=channel_id, read_api_key=read_api_key)
                entry_key = f"{channel_id}"
                entry_id = str(circuit.get("entry_id") or "")
                if entry_id and state["last_seen_entries"].get(entry_key) == entry_id:
                    continue
                result, fields = analyze_prediction(
                    state["bundle"],
                    circuit,
                    floor_id=floor_id,
                    channel_id=channel_id,
                )
                if entry_id:
                    state["last_seen_entries"][entry_key] = entry_id
                if upload:
                    ok, msg = upload_to_thingspeak(
                        api_key=THINGSPEAK_API_KEY,
                        fields=fields,
                        server=THINGSPEAK_SERVER,
                    )
                    result["thingspeak_upload"] = {"ok": ok, "message": msg}
                results.append(result)
            except Exception as exc:
                errors.append(
                    {
                        "floor_id": floor_id,
                        "channel_id": channel_id,
                        "error": str(exc),
                    }
                )

        return jsonify({"count": len(results), "results": results, "errors": errors})

    @flask_app.post("/api/poll")
    def dashboard_poll():
        payload = request.get_json(silent=True) or {}
        ingest = bool(payload.get("ingest", True))
        upload = bool(payload.get("upload"))
        floor_configs = payload.get("floor_configs")

        if floor_configs is None:
            try:
                floor_configs = _build_floor_configs(FLOOR_CHANNEL_IDS_DEFAULT, FLOOR_READ_API_KEYS_DEFAULT)
            except Exception:
                floor_configs = []

        if not ingest:
            return jsonify({"status": "skipped", "count": 0, "results": [], "errors": []})

        if not isinstance(floor_configs, list) or len(floor_configs) == 0:
            return jsonify({"error": "floor_configs must be a non-empty list"}), 400

        results: list[dict] = []
        errors: list[dict] = []

        for cfg in floor_configs:
            if not isinstance(cfg, dict):
                continue

            try:
                floor_id = int(cfg.get("floor_id"))
            except (TypeError, ValueError):
                continue

            channel_id = str(cfg.get("channel_id") or "").strip()
            read_api_key = str(cfg.get("read_api_key") or "").strip()
            if not channel_id:
                continue

            try:
                circuit = fetch_latest_from_thingspeak(channel_id=channel_id, read_api_key=read_api_key)
                entry_key = str(channel_id)
                entry_id = str(circuit.get("entry_id") or "")
                if entry_id and state["last_seen_entries"].get(entry_key) == entry_id:
                    continue

                result, fields = analyze_prediction(
                    state["bundle"],
                    circuit,
                    floor_id=floor_id,
                    channel_id=channel_id,
                )
                if entry_id:
                    state["last_seen_entries"][entry_key] = entry_id
                if upload:
                    ok, msg = upload_to_thingspeak(
                        api_key=THINGSPEAK_API_KEY,
                        fields=fields,
                        server=THINGSPEAK_SERVER,
                    )
                    result["thingspeak_upload"] = {"ok": ok, "message": msg}
                results.append(result)
            except Exception as exc:
                errors.append(
                    {
                        "floor_id": floor_id,
                        "channel_id": channel_id,
                        "error": str(exc),
                    }
                )

        return jsonify(
            {
                "status": "ok",
                "count": len(results),
                "results": results,
                "errors": errors,
            }
        )

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

        result, fields = analyze_prediction(
            state["bundle"],
            circuit,
            channel_id=channel_id if use_thingspeak else None,
        )
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
    print(f"Incident log backend: {INCIDENT_LOGGER.backend}")
    flask_app.run(host=host, port=port, debug=False)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Virtual evacuation app (manual, ThingSpeak single/multi-floor, web UI, or export)."
    )
    parser.add_argument(
        "--input-mode",
        choices=["thingspeak", "thingspeak-multi", "manual", "web", "export-floors"],
        default="thingspeak-multi",
        help="Input source for conditions.",
    )
    parser.add_argument("--channel-id", default=THINGSPEAK_CHANNEL_ID, help="ThingSpeak channel ID for read mode.")
    parser.add_argument("--read-api-key", default=THINGSPEAK_READ_API_KEY, help="ThingSpeak read API key (optional).")
    parser.add_argument("--poll-seconds", type=int, default=15, help="Polling interval in seconds.")
    parser.add_argument(
        "--floor-channel-ids",
        default=FLOOR_CHANNEL_IDS_DEFAULT,
        help="Comma-separated channel IDs for floor_0,floor_1,floor_2 (used in thingspeak-multi mode).",
    )
    parser.add_argument(
        "--floor-read-api-keys",
        default=FLOOR_READ_API_KEYS_DEFAULT,
        help="Comma-separated read API keys for floor_0,floor_1,floor_2 (used in thingspeak-multi mode).",
    )
    parser.add_argument(
        "--export-path",
        default=str(FLOOR_EXPORT_XLSX_PATH),
        help="Excel output path for export-floors mode.",
    )
    parser.add_argument(
        "--no-auto-export",
        action="store_true",
        help="Disable automatic floor-wise Excel export during thingspeak-multi polling.",
    )
    parser.add_argument("--host", default=WEB_HOST, help="Host for web mode.")
    parser.add_argument("--port", type=int, default=WEB_PORT, help="Port for web mode.")
    parser.add_argument(
        "--upload",
        action="store_true",
        help="Upload predicted final state back to ThingSpeak using configured write API key.",
    )
    args = parser.parse_args()

    if args.input_mode == "export-floors":
        output = export_floor_sheets(Path(args.export_path))
        print(f"Exported floor workbook: {output}")
        return

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

    if args.input_mode == "thingspeak-multi":
        try:
            floor_configs = _build_floor_configs(args.floor_channel_ids, args.floor_read_api_keys)
        except ValueError as exc:
            print(f"Invalid multi-floor config: {exc}")
            print(
                "Example: python Code/app.py --input-mode thingspeak-multi "
                "--floor-channel-ids 111111,222222,333333 "
                "--floor-read-api-keys KEY0,KEY1,KEY2"
            )
            return
        run_multi_floor_thingspeak_polling(
            bundle=bundle,
            floor_configs=floor_configs,
            poll_seconds=args.poll_seconds,
            upload=args.upload,
            auto_export=not args.no_auto_export,
            export_path=Path(args.export_path),
        )
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
