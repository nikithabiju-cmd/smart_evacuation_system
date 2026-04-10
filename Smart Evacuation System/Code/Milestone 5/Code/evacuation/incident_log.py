from __future__ import annotations

import csv
import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from openpyxl import Workbook


@dataclass
class IncidentLogger:
    sqlite_path: Path | None = None
    sqlserver_conn_str: str | None = None
    csv_path: Path | None = None
    backend: str = field(init=False)

    def __post_init__(self) -> None:
        self.backend = "sqlserver" if self.sqlserver_conn_str else "sqlite"
        if self.csv_path is not None:
            self.csv_path.parent.mkdir(parents=True, exist_ok=True)
            self._init_csv()
        if self.backend == "sqlite":
            if self.sqlite_path is None:
                raise ValueError("sqlite_path is required when sqlserver_conn_str is not provided.")
            self.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_csv(self) -> None:
        if self.csv_path is None:
            return
        fieldnames = self._fieldnames()
        if not self.csv_path.exists():
            with self.csv_path.open("w", newline="", encoding="utf-8") as fh:
                writer = csv.DictWriter(fh, fieldnames=fieldnames)
                writer.writeheader()
            return
        with self.csv_path.open("r", newline="", encoding="utf-8") as fh:
            reader = csv.reader(fh)
            existing_header = next(reader, [])
        if existing_header == fieldnames:
            return
        with self.csv_path.open("r", newline="", encoding="utf-8") as fh:
            old_reader = csv.DictReader(fh)
            existing_rows = list(old_reader)
        with self.csv_path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames)
            writer.writeheader()
            for old_row in existing_rows:
                writer.writerow({name: old_row.get(name, "") for name in fieldnames})

    def _connect(self):
        if self.backend == "sqlserver":
            try:
                import pyodbc
            except ImportError as exc:
                raise RuntimeError(
                    "pyodbc is required for SQL Server logging. Install with: pip install pyodbc"
                ) from exc
            return pyodbc.connect(self.sqlserver_conn_str, timeout=10)

        conn = sqlite3.connect(self.sqlite_path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    def _parse_sqlserver_conn_str(self) -> dict[str, str]:
        parsed: dict[str, str] = {}
        for part in (self.sqlserver_conn_str or "").split(";"):
            if "=" not in part:
                continue
            key, value = part.split("=", 1)
            key = key.strip().lower()
            value = value.strip()
            if key:
                parsed[key] = value
        return parsed

    def _with_sqlserver_database(self, database: str | None) -> str:
        parts: list[str] = []
        replaced = False
        for part in (self.sqlserver_conn_str or "").split(";"):
            if not part.strip():
                continue
            if "=" not in part:
                parts.append(part)
                continue
            key, _ = part.split("=", 1)
            k = key.strip().lower()
            if k in {"database", "initial catalog"}:
                replaced = True
                if database:
                    parts.append(f"{key}= {database}".replace("= ", "="))
                continue
            parts.append(part)

        if database and not replaced:
            parts.append(f"DATABASE={database}")
        return ";".join(parts) + ";"

    def _init_db(self) -> None:
        if self.backend == "sqlserver":
            self._init_sqlserver()
            return
        self._init_sqlite()

    def _init_sqlite(self) -> None:
        conn = self._connect()
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=5000")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS incident_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    logged_at_utc TEXT NOT NULL,
                    floor_id INTEGER,
                    channel_id TEXT,
                    source TEXT,
                    timestamp TEXT,
                    entry_id TEXT,
                    temp_c REAL,
                    hum_pct REAL,
                    pir_a INTEGER,
                    pir_b INTEGER,
                    pir_c INTEGER,
                    sound_d INTEGER,
                    sound_a REAL,
                    gas_a REAL,
                    gas_d INTEGER,
                    firmware_rule_state TEXT,
                    ml_predicted_state TEXT,
                    ml_confidence REAL,
                    final_state TEXT,
                    virtual_outputs_json TEXT,
                    thingspeak_fields_json TEXT
                )
                """
            )
            cols = {row[1] for row in conn.execute("PRAGMA table_info(incident_logs)").fetchall()}
            if "floor_id" not in cols:
                conn.execute("ALTER TABLE incident_logs ADD COLUMN floor_id INTEGER")
            if "channel_id" not in cols:
                conn.execute("ALTER TABLE incident_logs ADD COLUMN channel_id TEXT")
            conn.commit()
        finally:
            conn.close()


    def _init_sqlserver(self) -> None:
        parsed = self._parse_sqlserver_conn_str()
        db_name = parsed.get("database") or parsed.get("initial catalog")
        if db_name:
            admin_conn_str = self._with_sqlserver_database("master")
            conn_admin = None
            try:
                conn_admin = self._connect_sqlserver(admin_conn_str=admin_conn_str)
                conn_admin.autocommit = True
                cursor_admin = conn_admin.cursor()
                safe_db_name = db_name.replace("]", "]]")
                cursor_admin.execute(f"IF DB_ID(N'{safe_db_name}') IS NULL CREATE DATABASE [{safe_db_name}]")
            finally:
                if conn_admin is not None:
                    conn_admin.close()

        conn = self._connect()
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                IF OBJECT_ID(N'dbo.incident_logs', N'U') IS NULL
                BEGIN
                    CREATE TABLE dbo.incident_logs (
                        id BIGINT IDENTITY(1,1) PRIMARY KEY,
                        logged_at_utc NVARCHAR(64) NOT NULL,
                        floor_id INT NULL,
                        channel_id NVARCHAR(64) NULL,
                        source NVARCHAR(64) NULL,
                        timestamp NVARCHAR(64) NULL,
                        entry_id NVARCHAR(64) NULL,
                        temp_c FLOAT NULL,
                        hum_pct FLOAT NULL,
                        pir_a INT NULL,
                        pir_b INT NULL,
                        pir_c INT NULL,
                        sound_d INT NULL,
                        sound_a FLOAT NULL,
                        gas_a FLOAT NULL,
                        gas_d INT NULL,
                        firmware_rule_state NVARCHAR(32) NULL,
                        ml_predicted_state NVARCHAR(32) NULL,
                        ml_confidence FLOAT NULL,
                        final_state NVARCHAR(32) NULL,
                        virtual_outputs_json NVARCHAR(MAX) NULL,
                        thingspeak_fields_json NVARCHAR(MAX) NULL
                    );
                END
                """
            )
            conn.commit()
        finally:
            conn.close()

    def _connect_sqlserver(self, admin_conn_str: str):
        import pyodbc

        return pyodbc.connect(admin_conn_str, timeout=10)

    @staticmethod
    def _fieldnames() -> list[str]:
        return [
            "logged_at_utc",
            "floor_id",
            "channel_id",
            "source",
            "timestamp",
            "entry_id",
            "temp_c",
            "hum_pct",
            "pir_a",
            "pir_b",
            "pir_c",
            "sound_d",
            "sound_a",
            "gas_a",
            "gas_d",
            "firmware_rule_state",
            "ml_predicted_state",
            "ml_confidence",
            "final_state",
            "virtual_outputs_json",
            "thingspeak_fields_json",
        ]

    @staticmethod
    def _select_columns() -> list[str]:
        return [
            "id",
            "logged_at_utc",
            "floor_id",
            "channel_id",
            "source",
            "timestamp",
            "entry_id",
            "temp_c",
            "hum_pct",
            "pir_a",
            "pir_b",
            "pir_c",
            "sound_d",
            "sound_a",
            "gas_a",
            "gas_d",
            "firmware_rule_state",
            "ml_predicted_state",
            "ml_confidence",
            "final_state",
            "virtual_outputs_json",
            "thingspeak_fields_json",
        ]

    def _fetchall_dicts(self, conn, query: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        if self.backend == "sqlite":
            rows = conn.execute(query, params).fetchall()
            return [dict(row) for row in rows]

        cursor = conn.cursor()
        cursor.execute(query, params)
        rows = cursor.fetchall()
        if not rows:
            return []
        col_names = [col[0] for col in cursor.description]
        return [dict(zip(col_names, row)) for row in rows]

    def _fetch_scalar(self, conn, query: str, params: tuple[Any, ...] = ()) -> Any:
        if self.backend == "sqlite":
            row = conn.execute(query, params).fetchone()
            return row[0] if row else None

        cursor = conn.cursor()
        cursor.execute(query, params)
        row = cursor.fetchone()
        return row[0] if row else None

    @staticmethod
    def _decode_json_fields(item: dict[str, Any]) -> dict[str, Any]:
        try:
            item["virtual_outputs"] = json.loads(item.pop("virtual_outputs_json") or "{}")
        except json.JSONDecodeError:
            item["virtual_outputs"] = {}
        try:
            item["thingspeak_fields"] = json.loads(item.pop("thingspeak_fields_json") or "{}")
        except json.JSONDecodeError:
            item["thingspeak_fields"] = {}
        return item

    def log(
        self,
        circuit: dict[str, Any],
        result: dict[str, Any],
        floor_id: int | None = None,
        channel_id: str | None = None,
    ) -> None:
        row = {
            "logged_at_utc": datetime.now(timezone.utc).isoformat(),
            "floor_id": floor_id,
            "channel_id": channel_id,
            "source": result.get("source"),
            "timestamp": result.get("timestamp"),
            "entry_id": str(result.get("entry_id") or ""),
            "temp_c": circuit.get("temp_c"),
            "hum_pct": circuit.get("hum_pct"),
            "pir_a": int(circuit.get("pir_a", 0)),
            "pir_b": int(circuit.get("pir_b", 0)),
            "pir_c": int(circuit.get("pir_c", 0)),
            "sound_d": int(circuit.get("sound_d", 0)),
            "sound_a": circuit.get("sound_a"),
            "gas_a": circuit.get("gas_a"),
            "gas_d": int(circuit.get("gas_d", 0)),
            "firmware_rule_state": result.get("firmware_rule_state"),
            "ml_predicted_state": result.get("ml_predicted_state"),
            "ml_confidence": result.get("ml_confidence"),
            "final_state": result.get("final_state"),
            "virtual_outputs_json": json.dumps(result.get("virtual_outputs", {}), separators=(",", ":")),
            "thingspeak_fields_json": json.dumps(result.get("thingspeak_fields", {}), separators=(",", ":")),
        }

        values = (
            row["logged_at_utc"],
            row["floor_id"],
            row["channel_id"],
            row["source"],
            row["timestamp"],
            row["entry_id"],
            row["temp_c"],
            row["hum_pct"],
            row["pir_a"],
            row["pir_b"],
            row["pir_c"],
            row["sound_d"],
            row["sound_a"],
            row["gas_a"],
            row["gas_d"],
            row["firmware_rule_state"],
            row["ml_predicted_state"],
            row["ml_confidence"],
            row["final_state"],
            row["virtual_outputs_json"],
            row["thingspeak_fields_json"],
        )

        conn = self._connect()
        try:
            query = """
                INSERT INTO incident_logs (
                    logged_at_utc, floor_id, channel_id, source, timestamp, entry_id, temp_c, hum_pct,
                    pir_a, pir_b, pir_c, sound_d, sound_a, gas_a, gas_d,
                    firmware_rule_state, ml_predicted_state, ml_confidence,
                    final_state, virtual_outputs_json, thingspeak_fields_json
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?,
                    ?, ?, ?
                )
            """
            if self.backend == "sqlite":
                conn.execute(query, values)
            else:
                cursor = conn.cursor()
                cursor.execute(query, values)
            conn.commit()
        finally:
            conn.close()

    def recent(self, limit: int = 20) -> list[dict[str, Any]]:
        safe_limit = max(1, min(int(limit), 1000))
        cols = ", ".join(self._select_columns())

        conn = self._connect()
        try:
            if self.backend == "sqlite":
                rows = self._fetchall_dicts(
                    conn,
                    f"SELECT {cols} FROM incident_logs ORDER BY id DESC LIMIT ?",
                    (safe_limit,),
                )
            else:
                rows = self._fetchall_dicts(
                    conn,
                    f"SELECT TOP ({safe_limit}) {cols} FROM incident_logs ORDER BY id DESC",
                )
        finally:
            conn.close()

        return [self._decode_json_fields(dict(row)) for row in rows]

    def latest_per_floor(self, floor_ids: list[int] | None = None) -> list[dict[str, Any]]:
        selected_floors = floor_ids if floor_ids is not None else [0, 1, 2]
        cols = ", ".join(self._select_columns())
        snapshots: list[dict[str, Any]] = []

        conn = self._connect()
        try:
            for floor_id in selected_floors:
                if self.backend == "sqlite":
                    rows = self._fetchall_dicts(
                        conn,
                        f"""
                        SELECT {cols}
                        FROM incident_logs
                        WHERE floor_id = ?
                        ORDER BY id DESC
                        LIMIT 1
                        """,
                        (int(floor_id),),
                    )
                else:
                    rows = self._fetchall_dicts(
                        conn,
                        f"""
                        SELECT TOP (1) {cols}
                        FROM incident_logs
                        WHERE floor_id = ?
                        ORDER BY id DESC
                        """,
                        (int(floor_id),),
                    )
                if rows:
                    snapshots.append(self._decode_json_fields(dict(rows[0])))
        finally:
            conn.close()

        return snapshots

    def stream(
        self,
        after_id: int = 0,
        limit: int = 200,
        floor_id: int | None = None,
    ) -> dict[str, Any]:
        safe_after_id = max(0, int(after_id))
        safe_limit = max(1, min(int(limit), 1000))
        cols = ", ".join(self._select_columns())

        conn = self._connect()
        try:
            params: list[Any] = [safe_after_id]
            where_sql = "WHERE id > ?"
            if floor_id is not None:
                where_sql += " AND floor_id = ?"
                params.append(int(floor_id))

            if self.backend == "sqlite":
                query = f"SELECT {cols} FROM incident_logs {where_sql} ORDER BY id ASC LIMIT ?"
                params.append(safe_limit)
                rows = self._fetchall_dicts(conn, query, tuple(params))
            else:
                query = f"SELECT TOP ({safe_limit}) {cols} FROM incident_logs {where_sql} ORDER BY id ASC"
                rows = self._fetchall_dicts(conn, query, tuple(params))

            latest_id = self._fetch_scalar(conn, "SELECT COALESCE(MAX(id), 0) FROM incident_logs") or 0
        finally:
            conn.close()

        stream_rows = [self._decode_json_fields(dict(row)) for row in rows]
        return {
            "after_id": safe_after_id,
            "latest_id": int(latest_id),
            "count": len(stream_rows),
            "rows": stream_rows,
        }

    def summary_counts(self) -> dict[str, int]:
        conn = self._connect()
        try:
            rows = self._fetchall_dicts(
                conn,
                """
                SELECT final_state, COUNT(*) as total
                FROM incident_logs
                GROUP BY final_state
                """,
            )
        finally:
            conn.close()

        counts = {"SAFE": 0, "CAUTION": 0, "EVACUATE": 0}
        for row in rows:
            key = str(row.get("final_state") or "").upper()
            if key in counts:
                counts[key] = int(row.get("total") or 0)
        counts["TOTAL"] = int(sum(counts.values()))
        return counts

    def export_floor_workbook(
        self,
        output_path: Path,
        floors: list[int] | None = None,
    ) -> Path:
        selected_floors = floors if floors is not None else [0, 1, 2]
        fieldnames = self._fieldnames()
        export_columns = ", ".join(fieldnames)

        conn = self._connect()
        try:
            workbook = Workbook()
            default_sheet = workbook.active
            workbook.remove(default_sheet)

            for floor in selected_floors:
                rows = self._fetchall_dicts(
                    conn,
                    f"""
                    SELECT {export_columns}
                    FROM incident_logs
                    WHERE floor_id = ?
                    ORDER BY id ASC
                    """,
                    (floor,),
                )

                ws = workbook.create_sheet(title=f"floor_{floor}")
                ws.append(fieldnames)
                for row in rows:
                    ws.append([row.get(col) for col in fieldnames])

            output_path.parent.mkdir(parents=True, exist_ok=True)
            workbook.save(output_path)
            return output_path
        finally:
            conn.close()
