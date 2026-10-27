#!/usr/bin/env python3
"""Compare saved MOSCEYE results with human labels and report error metrics.

Usage:
    ./mosceye/.venv/bin/python mosceye/audit/evaluate.py
    ./mosceye/.venv/bin/python mosceye/audit/evaluate.py --check-labels

Labels live in audit/labels.json. A null label means "not labeled yet"; that
metric is skipped instead of being counted as zero. This is deliberately
separate from the detector so a model change cannot silently change the score.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
EVIDENCE = HERE / "evidence" / "core-v2"
LABELS = HERE / "labels.json"


def load_labels(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1 or not isinstance(data.get("frames"), dict):
        raise SystemExit(f"{path}: expected schema_version 1 and a 'frames' object")
    return data


def mean_absolute_error(pairs: list[tuple[float, float]]) -> float | None:
    if not pairs:
        return None
    return sum(abs(a - b) for a, b in pairs) / len(pairs)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--labels", type=Path, default=LABELS)
    parser.add_argument("--evidence", type=Path, default=EVIDENCE)
    parser.add_argument("--check-labels", action="store_true", help="validate labels and exit")
    args = parser.parse_args()

    labels = load_labels(args.labels)
    frame_ids = sorted(p.stem for p in args.evidence.glob("*.json") if p.stem.isdigit())

    if args.check_labels:
        missing = [f for f in frame_ids if f not in labels["frames"]]
        unlabeled = [f for f in frame_ids if all(
            labels["frames"].get(f, {}).get(k) is None
            for k in ("people_in_store", "people_in_queue", "cashier_present"))]
        print(json.dumps({
            "frames_in_evidence": len(frame_ids),
            "frames_in_labels": len(labels["frames"]),
            "missing_frames": missing,
            "fully_unlabeled_frames": unlabeled,
            "reviewed": bool(labels.get("reviewed")),
        }, ensure_ascii=False, indent=2))
        return 0 if not missing else 1

    store_pairs, queue_pairs, cashier_pairs, rows = [], [], [], []
    for frame_id in frame_ids:
        label = labels["frames"].get(frame_id)
        model_path = args.evidence / f"{frame_id}.json"
        if not label or not model_path.exists():
            continue
        model = json.loads(model_path.read_text(encoding="utf-8"))
        row = {"frame": frame_id}
        if label.get("people_in_store") is not None and model.get("people_in_store") is not None:
            store_pairs.append((label["people_in_store"], model["people_in_store"]))
            row["store_label"] = label["people_in_store"]
            row["store_model"] = model["people_in_store"]
        if label.get("people_in_queue") is not None and model.get("people_in_queue") is not None:
            queue_pairs.append((label["people_in_queue"], model["people_in_queue"]))
            row["queue_label"] = label["people_in_queue"]
            row["queue_model"] = model["people_in_queue"]
        if label.get("cashier_present") is not None and model.get("cashier_present") is not None:
            cashier_pairs.append((bool(label["cashier_present"]), bool(model["cashier_present"])))
            row["cashier_label"] = label["cashier_present"]
            row["cashier_model"] = model["cashier_present"]
        rows.append(row)

    report = {
        "frames_evaluated": len(rows),
        "labels_reviewed": bool(labels.get("reviewed")),
        "store": {
            "n": len(store_pairs),
            "mae": mean_absolute_error(store_pairs),
        },
        "queue": {
            "n": len(queue_pairs),
            "mae": mean_absolute_error(queue_pairs),
        },
        "cashier": {
            "n": len(cashier_pairs),
            "accuracy": (sum(a == b for a, b in cashier_pairs) / len(cashier_pairs))
            if cashier_pairs else None,
        },
        "frames": rows,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
