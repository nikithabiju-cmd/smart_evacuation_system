# Smart Evacuation System

A Python-based smart evacuation monitoring system that:
- trains an ML model from your evacuation dataset,
- applies firmware-style safety rules,
- ingests live sensor values from ThingSpeak,
- supports single-floor and multi-floor monitoring,
- exposes a web dashboard + APIs,
- logs incidents to SQL Server (with SQLite fallback), CSV, and Excel.

## Project Structure

```text
Smart Evacuation System/
|- app.py                          # Root launcher (defaults to web mode)
|- README.md
|- system_architecture.md
|- Code/
|  |- app.py                       # Main runtime app
|  |- virtual_evacuation_model.py  # Train/simulate CLI
|  |- trained_evacuation_model.joblib
|  |- smart_evacuation_dataset_with_occupancy.csv
|  |- main.ckt
|  |- templates/                   # Web UI template
|  |- static/                      # Web UI assets
|  |- logs/                        # SQLite/CSV/Excel outputs
|  |- metrics/                     # Training metrics JSON
|  `- evacuation/                  # Core package modules
|- docs/
`- circuit_design/
```

## Prerequisites

- Python 3.10+ (3.11+ recommended)
- `pip`
- Internet connection (for ThingSpeak modes)
- Optional for SQL Server logging:
  - Microsoft SQL Server instance
  - ODBC Driver 18 for SQL Server
  - `pyodbc`

## 1. Setup Environment

From repository root (`Smart Evacuation System`):

### Windows (PowerShell)

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install flask numpy pandas scikit-learn joblib openpyxl
```

### macOS/Linux (bash/zsh)

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install flask numpy pandas scikit-learn joblib openpyxl
```

Optional (only if you want SQL Server backend):

```bash
pip install pyodbc
```

## 2. Train (or Re-Train) the Model

If `Code/trained_evacuation_model.joblib` is missing or you want fresh training:

```bash
python Code/virtual_evacuation_model.py train \
  --ckt Code/main.ckt \
  --csv Code/smart_evacuation_dataset_with_occupancy.csv \
  --epochs 20 \
  --model-out Code/trained_evacuation_model.joblib \
  --metrics-out Code/metrics/metrics_report.json
```

Optional circuit inspection:

```bash
python Code/virtual_evacuation_model.py inspect --ckt Code/main.ckt
```

Optional one-off simulation:

```bash
python Code/virtual_evacuation_model.py simulate \
  --model-in Code/trained_evacuation_model.joblib \
  --pir-level 90 \
  --gas-level-ppm 900 \
  --sound-level-db 80 \
  --temperature-c 62 \
  --humidity-percent 86 \
  --smoke-ppm 210 \
  --co-ppm 70 \
  --speaker-on on \
  --json
```

## 3. Run the Project

You can run from root using either launcher:
- `python app.py` (root wrapper)
- `python Code/app.py` (direct)

### A) Web Dashboard (recommended)

```bash
python app.py
```

This starts Flask UI at:
- `http://localhost:5000`

Equivalent explicit command:

```bash
python Code/app.py --input-mode web --host localhost --port 5000
```

### B) ThingSpeak Multi-Floor Polling (CLI)

```bash
python Code/app.py --input-mode thingspeak-multi
```

Custom channels/keys:

```bash
python Code/app.py --input-mode thingspeak-multi \
  --floor-channel-ids 3333445,3328061,3333277 \
  --floor-read-api-keys KEY_FLOOR0,KEY_FLOOR1,KEY_FLOOR2 \
  --poll-seconds 15
```

### C) ThingSpeak Single-Channel Polling (CLI)

```bash
python Code/app.py --input-mode thingspeak --channel-id 3328061 --read-api-key YOUR_READ_KEY
```

### D) Manual Sensor Input Mode (CLI)

```bash
python Code/app.py --input-mode manual
```

### E) Export Floor-wise Excel from Logs

```bash
python Code/app.py --input-mode export-floors --export-path Code/logs/incident_logs_by_floor.xlsx
```

## 4. Optional: Upload Predicted State Back to ThingSpeak

Add `--upload` to polling/manual modes:

```bash
python Code/app.py --input-mode thingspeak-multi --upload
```

## 5. Logging and Outputs

Generated artifacts:
- SQLite fallback DB: `Code/logs/incident_logs.db`
- CSV log: `Code/logs/incident_logs.csv`
- Floor-wise Excel export: `Code/logs/incident_logs_by_floor.xlsx`
- Training metrics: `Code/metrics/metrics_report.json`

## 6. SQL Server Configuration (Optional)

App tries SQL Server first, then falls back to SQLite if unavailable.

Set env var before running:

### Windows (PowerShell)

```powershell
$env:INCIDENT_SQLSERVER_CONN_STR = "DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\SQLEXPRESS;DATABASE=SmartEvacuation;Trusted_Connection=yes;TrustServerCertificate=yes;"
python app.py
```

### macOS/Linux

```bash
export INCIDENT_SQLSERVER_CONN_STR="DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\\SQLEXPRESS;DATABASE=SmartEvacuation;Trusted_Connection=yes;TrustServerCertificate=yes;"
python app.py
```

## 7. Useful API Endpoints (Web Mode)

When server is running on `localhost:5000`:
- `GET /api/config`
- `GET /api/history?limit=20`
- `GET /api/live/extract?after_id=0&limit=200`
- `POST /api/live/poll`
- `POST /api/live/poll-multi`
- `POST /api/predict`

## 8. Troubleshooting

- `Model not found: Code/trained_evacuation_model.joblib`
  - Run the training command in section 2.

- `ModuleNotFoundError` for Flask/Pandas/etc.
  - Activate virtual environment and reinstall dependencies.

- SQL Server connection errors
  - Ensure SQL Server is reachable, ODBC driver is installed, and `pyodbc` is installed.
  - If not available, app should automatically use SQLite.

- ThingSpeak read failures
  - Verify channel ID, read API key, internet connectivity, and field mappings.

## Quick Start (Minimal)

```bash
# 1) install deps (inside venv)
pip install flask numpy pandas scikit-learn joblib openpyxl

# 2) train (if needed)
python Code/virtual_evacuation_model.py train --ckt Code/main.ckt --csv Code/smart_evacuation_dataset_with_occupancy.csv

# 3) run web app
python app.py
```
