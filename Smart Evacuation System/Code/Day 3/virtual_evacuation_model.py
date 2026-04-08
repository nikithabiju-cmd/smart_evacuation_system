#!/usr/bin/env python3
"""
CLI entrypoint for training and simulation.
Core logic is split into the `evacuation` package modules.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from evacuation.cirkit import CirkitProject
from evacuation.model import EvacuationVirtualModel
from evacuation.storage import load_bundle, predict_from_bundle, save_bundle


def cmd_inspect(args: argparse.Namespace) -> None:
    project = CirkitProject(Path(args.ckt))
    project.load()
    summary = project.summarize()
    print("Cirkit component summary:")
    for name, count in summary.components_by_name.items():
        print(f"  - {name}: {count}")
    if summary.missing_required:
        print("\nMissing expected components:")
        for name in summary.missing_required:
            print(f"  - {name}")
    else:
        print("\nAll expected evacuation-system components were found.")


def cmd_train(args: argparse.Namespace) -> None:
    project = CirkitProject(Path(args.ckt))
    project.load()
    summary = project.summarize()

    model = EvacuationVirtualModel()
    metrics = model.train(
        csv_path=Path(args.csv),
        target_col=args.target_col,
        epochs=args.epochs,
    )
    save_bundle(Path(args.model_out), model, summary, metrics)
    metrics_out = Path(args.metrics_out)
    metrics_out.parent.mkdir(parents=True, exist_ok=True)
    metrics_out.write_text(
        json.dumps(
            {
                "rows": metrics["rows"],
                "epochs": metrics["epochs"],
                "accuracy": metrics["accuracy"],
                "macro_recall": metrics["macro_recall"],
                "macro_f1": metrics["macro_f1"],
                "labels_used": metrics["labels_used"],
                "auto_labeled": metrics["auto_labeled"],
                "classification_report": metrics["classification_report_dict"],
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    print(f"\nModel trained and saved: {args.model_out}")
    print(f"Metrics saved: {args.metrics_out}")
    print(f"Rows used: {metrics['rows']}")
    print(f"Epochs: {metrics['epochs']}")
    print(f"Accuracy: {metrics['accuracy']:.4f}")
    print(f"Recall (macro): {metrics['macro_recall']:.4f}")
    print(f"F1-score (macro): {metrics['macro_f1']:.4f}")
    if metrics["auto_labeled"]:
        print("Note: target labels were auto-generated (no target column found).")
    print("\nClassification report:\n")
    print(metrics["classification_report"])


def cmd_simulate(args: argparse.Namespace) -> None:
    bundle = load_bundle(Path(args.model_in))
    conditions = {
        "pir_level": args.pir_level,
        "gas_level_ppm": args.gas_level_ppm,
        "sound_level_dB": args.sound_level_db,
        "temperature_C": args.temperature_c,
        "humidity_percent": args.humidity_percent,
        "smoke_ppm": args.smoke_ppm,
        "co_ppm": args.co_ppm,
        "speaker_on": args.speaker_on,
    }
    result = predict_from_bundle(bundle, conditions)

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"Predicted state: {result['predicted_state']}")
        print(f"Confidence: {result['confidence']:.3f}")
        print("Virtual outputs:")
        for k, v in result["virtual_outputs"].items():
            print(f"  - {k}: {v}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Train and simulate a virtual evacuation model from Cirkit .ckt + CSV data."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_inspect = sub.add_parser("inspect", help="Inspect the Cirkit .ckt component layout.")
    p_inspect.add_argument("--ckt", required=True, help="Path to .ckt file")
    p_inspect.set_defaults(func=cmd_inspect)

    p_train = sub.add_parser("train", help="Train a model from CSV data.")
    p_train.add_argument("--ckt", required=True, help="Path to .ckt file")
    p_train.add_argument("--csv", required=True, help="Training CSV path")
    p_train.add_argument("--model-out", default="Code/trained_evacuation_model.joblib", help="Output model bundle")
    p_train.add_argument("--metrics-out", default="Code/metrics/metrics_report.json", help="Output metrics JSON file")
    p_train.add_argument("--target-col", default="target_state", help="Target column in CSV")
    p_train.add_argument("--epochs", type=int, default=20, help="Training epochs")
    p_train.set_defaults(func=cmd_train)

    p_sim = sub.add_parser("simulate", help="Simulate one virtual condition from trained model.")
    p_sim.add_argument("--model-in", required=True, help="Path to trained model bundle")
    p_sim.add_argument("--pir-level", type=float, required=True)
    p_sim.add_argument("--gas-level-ppm", type=float, required=True)
    p_sim.add_argument("--sound-level-db", type=float, required=True)
    p_sim.add_argument("--temperature-c", type=float, required=True)
    p_sim.add_argument("--humidity-percent", type=float, required=True)
    p_sim.add_argument("--smoke-ppm", type=float, required=True)
    p_sim.add_argument("--co-ppm", type=float, required=True)
    p_sim.add_argument("--speaker-on", required=True, help="on/off or 1/0")
    p_sim.add_argument("--json", action="store_true")
    p_sim.set_defaults(func=cmd_simulate)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
