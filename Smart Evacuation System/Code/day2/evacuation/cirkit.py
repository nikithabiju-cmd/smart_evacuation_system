from __future__ import annotations

import json
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class CircuitSummary:
    components_by_name: dict[str, int]
    missing_required: list[str]


class CirkitProject:
    """Reads the `.ckt` archive and summarizes relevant components."""

    REQUIRED_COMPONENTS = [
        "ESP32-S3",
        "DHT11",
        "KY-037",
        "PIR Motion Sensor",
        "Piezo Speaker",
        "LED Two Pin (Red)",
        "LED Two Pin (Green)",
    ]

    def __init__(self, ckt_path: Path) -> None:
        self.ckt_path = ckt_path
        self.cirkit_json: dict[str, Any] = {}
        self.user_defined_json: dict[str, Any] = {}

    def load(self) -> None:
        if not self.ckt_path.exists():
            raise FileNotFoundError(f"Circuit file not found: {self.ckt_path}")

        with zipfile.ZipFile(self.ckt_path, "r") as zf:
            with zf.open("cirkitFile.json") as f:
                self.cirkit_json = json.load(f)
            with zf.open("jsons/user_defined.json") as f:
                self.user_defined_json = json.load(f)

    def summarize(self) -> CircuitSummary:
        type_id_to_name = self._type_id_to_name_map()
        component_instances = self._collect_component_instances(self.cirkit_json)
        by_name: dict[str, int] = {}

        for comp in component_instances:
            type_id = comp.get("typeId")
            name = type_id_to_name.get(type_id, f"Unknown<{type_id}>")
            by_name[name] = by_name.get(name, 0) + 1

        missing: list[str] = []
        for required in self.REQUIRED_COMPONENTS:
            if not any(required in name for name in by_name):
                missing.append(required)

        return CircuitSummary(components_by_name=dict(sorted(by_name.items())), missing_required=missing)

    def _type_id_to_name_map(self) -> dict[str, str]:
        mapping: dict[str, str] = {}
        for subtype in self.user_defined_json.get("subtypes", []):
            sid = subtype.get("id")
            sname = subtype.get("subtypeName")
            if sid and sname:
                mapping[sid] = sname
        return mapping

    def _collect_component_instances(self, payload: Any) -> list[dict[str, Any]]:
        found: list[dict[str, Any]] = []

        def walk(node: Any) -> None:
            if isinstance(node, dict):
                if "typeId" in node and "instanceId" in node:
                    found.append(node)
                for value in node.values():
                    walk(value)
            elif isinstance(node, list):
                for item in node:
                    walk(item)

        walk(payload)
        dedup: dict[str, dict[str, Any]] = {}
        for item in found:
            instance_id = item.get("instanceId")
            if instance_id:
                dedup[instance_id] = item
        return list(dedup.values())
