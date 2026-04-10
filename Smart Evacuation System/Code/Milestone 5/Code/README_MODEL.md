# Virtual Evacuation Model (Cirkit-Compatible)

This setup trains a software model using your Cirkit circuit (`main.ckt`) and CSV data, then allows live condition checks.

## Train with your current CSV

```bash
python Code/virtual_evacuation_model.py train ^
  --ckt Code/main.ckt ^
  --csv Code/smart_evacuation_dataset_with_occupancy.csv ^
  --epochs 50 ^
  --model-out Code/trained_evacuation_model.joblib
```

## Run one prediction from CLI

```bash
python Code/virtual_evacuation_model.py simulate ^
  --model-in Code/trained_evacuation_model.joblib ^
  --pir-level 90 ^
  --gas-level-ppm 900 ^
  --sound-level-db 80 ^
  --temperature-c 62 ^
  --humidity-percent 86 ^
  --smoke-ppm 210 ^
  --co-ppm 70 ^
  --speaker-on on ^
  --json
```

## Use app.py with ThingSpeak as input (no manual typing)

```bash
python Code/app.py
```

Notes:

- Default channel/read key are already configured in `app.py` (`3328061`).
- You can still override via `--channel-id` and `--read-api-key`.
- Polling interval default is 15 seconds; change with `--poll-seconds 10`.
- Add `--upload` if you also want to push the processed final state back using the configured write API key.

The app reads `field1..field8` from ThingSpeak and returns:

- `SAFE`
- `CAUTION`
- `EVACUATE`

Decision behavior:

- Final state follows your firmware rule logic exactly (`evaluateState` thresholds from your ESP32 code).
- ML prediction is also shown as advisory.

It also prepares and can upload ThingSpeak fields exactly like your firmware:

- `field1` = temperature
- `field2` = humidity
- `field3` = PIR A
- `field4` = PIR B
- `field5` = PIR C
- `field6` = sound analog
- `field7` = state (0/1/2)
- `field8` = gas analog

Cirkit-oriented virtual outputs:

- `red_led`
- `green_led`
- `buzzer_mode`
- `speaker_on`
- `evacuation_signal`

## Manual input mode (optional)

```bash
python Code/app.py --input-mode manual
```
