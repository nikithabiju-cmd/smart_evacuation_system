from __future__ import annotations

import json
import urllib.parse
import urllib.request

from .config import GAS_HIGH_RISK, SOUND_CAUTION, THINGSPEAK_DEFAULT_SERVER


def upload_to_thingspeak(
    api_key: str,
    fields: dict[str, str],
    server: str = THINGSPEAK_DEFAULT_SERVER,
    timeout_sec: float = 10.0,
) -> tuple[bool, str]:
    params = {"api_key": api_key}
    params.update(fields)
    url = f"{server}?{urllib.parse.urlencode(params)}"
    try:
        with urllib.request.urlopen(url, timeout=timeout_sec) as resp:
            body = resp.read().decode("utf-8", errors="ignore").strip()
            if resp.status == 200 and body != "0":
                return True, f"Upload SUCCESS | HTTP: {resp.status} | Entry ID: {body}"
            return False, f"Upload FAILED | HTTP: {resp.status} | Body: {body}"
    except Exception as exc:
        return False, f"Upload FAILED | Error: {exc}"


def _to_float(value: str | None, default: float = 0.0) -> float:
    if value is None or value == "":
        return default
    return float(value)


def _to_binary_from_field(value: str | None) -> int:
    if value is None or value == "":
        return 0
    return 1 if float(value) >= 0.5 else 0


def fetch_latest_from_thingspeak(channel_id: str, read_api_key: str = "") -> dict:
    params = {}
    if read_api_key:
        params["api_key"] = read_api_key
    query = urllib.parse.urlencode(params)
    url = f"https://api.thingspeak.com/channels/{channel_id}/feeds/last.json"
    if query:
        url += f"?{query}"

    with urllib.request.urlopen(url, timeout=15) as resp:
        if resp.status != 200:
            raise RuntimeError(f"ThingSpeak read failed with HTTP {resp.status}")
        payload = json.loads(resp.read().decode("utf-8", errors="ignore"))

    raw_fields = {f"field{i}": payload.get(f"field{i}") for i in range(1, 9)}
    f1 = payload.get("field1")
    f2 = payload.get("field2")
    f3 = payload.get("field3")
    f4 = payload.get("field4")
    f5 = payload.get("field5")
    f6 = payload.get("field6")
    f8 = payload.get("field8")

    # Two feed schemas are supported:
    # 1) Standard app schema: field1=temp, field2=hum, field3-5=PIR, field6=sound, field8=gas
    # 2) Floor hardware schema: field1=floor_id, field2=temp, field3=hum, field4=sound, field5=PIR, field6=gas
    alt_floor_schema = f1 in {"0", "1", "2"} and f2 not in {None, ""} and f3 not in {None, ""}
    if alt_floor_schema:
        temp_c = _to_float(f2)
        hum_pct = _to_float(f3)
        pir_a = _to_binary_from_field(f5)
        pir_b = 0
        pir_c = 0
        sound_a = _to_float(f4)
        gas_a = _to_float(f6)
    else:
        temp_c = _to_float(f1)
        hum_pct = _to_float(f2)
        pir_a = _to_binary_from_field(f3)
        pir_b = _to_binary_from_field(f4)
        pir_c = _to_binary_from_field(f5)
        sound_a = _to_float(f6)
        gas_a = _to_float(f8)

    sound_d = 1 if sound_a > SOUND_CAUTION else 0
    gas_d = 1 if gas_a > GAS_HIGH_RISK else 0

    return {
        "temp_c": temp_c,
        "hum_pct": hum_pct,
        "pir_a": pir_a,
        "pir_b": pir_b,
        "pir_c": pir_c,
        "sound_d": sound_d,
        "sound_a": sound_a,
        "gas_a": gas_a,
        "gas_d": gas_d,
        "timestamp": payload.get("created_at"),
        "entry_id": payload.get("entry_id"),
        "raw_fields": raw_fields,
    }
