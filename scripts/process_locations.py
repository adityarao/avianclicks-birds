#!/usr/bin/env python3
"""
process_locations.py
Reads MyEBirdData.csv, deduplicates by Submission ID (so each checklist
counts once), groups by eBird Location ID, and writes locations.json.

Each location entry contains all visit dates so the browser can filter
by any time window without a server roundtrip.

Output structure:
[
  {
    "lat":   12.97,
    "lng":   77.59,
    "name":  "Hebbal Lake",
    "locId": "L1234567",
    "dates": ["2024-01-15", "2024-03-02", ...]   // sorted ascending
  },
  ...
]

Usage:
    python process_locations.py
    python process_locations.py --csv MyEBirdData.csv --out locations.json
"""

import argparse
import csv
import json
from pathlib import Path
from datetime import datetime


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", default="MyEBirdData.csv")
    parser.add_argument("--out", default="locations.json")
    args = parser.parse_args()

    csv_path = Path(args.csv)
    if not csv_path.exists():
        raise SystemExit(f"CSV not found: {csv_path}")

    print(f"Reading {csv_path} …", flush=True)

    # ── Pass 1: one row per unique Submission ID ──────────────────────────────
    # The CSV has one row per species, so the same checklist appears many times.
    # We only need one row per submission to count a single visit.
    seen_subs: dict[str, dict] = {}

    with open(csv_path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            sub_id = row.get("Submission ID", "").strip()
            if not sub_id or sub_id in seen_subs:
                continue
            lat_str = row.get("Latitude", "").strip()
            lng_str = row.get("Longitude", "").strip()
            if not lat_str or not lng_str:
                continue
            try:
                lat = float(lat_str)
                lng = float(lng_str)
            except ValueError:
                continue
            seen_subs[sub_id] = {
                "locId": row.get("Location ID", "").strip(),
                "name":  row.get("Location",    "").strip(),
                "lat":   lat,
                "lng":   lng,
                "date":  row.get("Date", "").strip(),
            }

    print(f"  → {len(seen_subs)} unique checklists", flush=True)

    # ── Pass 2: group by Location ID ─────────────────────────────────────────
    locations: dict[str, dict] = {}

    for cl in seen_subs.values():
        loc_id = cl["locId"] or f"{cl['lat']:.4f},{cl['lng']:.4f}"
        if loc_id not in locations:
            locations[loc_id] = {
                "lat":   cl["lat"],
                "lng":   cl["lng"],
                "name":  cl["name"],
                "locId": cl["locId"],
                "dates": set(),
            }
        if cl["date"]:
            locations[loc_id]["dates"].add(cl["date"])

    # Serialise: sort dates ascending, convert set → list
    result = []
    for loc in locations.values():
        sorted_dates = sorted(loc["dates"])
        result.append({
            "lat":   loc["lat"],
            "lng":   loc["lng"],
            "name":  loc["name"],
            "locId": loc["locId"],
            "dates": sorted_dates,
        })

    # Sort output by number of visits descending (most-visited first)
    result.sort(key=lambda x: len(x["dates"]), reverse=True)

    out_path = Path(args.out)
    out_path.write_text(json.dumps(result, ensure_ascii=False, separators=(",", ":")))

    total_visits = sum(len(r["dates"]) for r in result)
    print(f"✓ {len(result)} locations · {total_visits} total checklist visits → {out_path}")


if __name__ == "__main__":
    main()
