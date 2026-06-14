#!/usr/bin/env python3
"""
process_ebird.py
Reads MyEBirdData.csv (eBird personal data export), filters to India,
fetches fresh eBird taxonomy, and writes birds.json for the website grid.

Usage:
    python process_ebird.py --api-key YOUR_EBIRD_API_KEY
    python process_ebird.py --api-key YOUR_EBIRD_API_KEY --csv path/to/MyEBirdData.csv
"""

import argparse
import csv
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

EBIRD_TAXONOMY_URL = "https://api.ebird.org/v2/ref/taxonomy/ebird"
EBIRD_SPECIES_URL  = "https://ebird.org/species/{code}"

# eBird State/Province codes that belong to India (all start with "IN-")
INDIA_PREFIX = "IN-"


def fetch_taxonomy(api_key: str) -> dict:
    """
    Fetch the full eBird/Clements taxonomy (species only) from the API.
    Returns a dict keyed by sciName → {speciesCode, comName, taxonOrder, order, familyComName, familySciName}
    """
    print("Fetching eBird taxonomy…", flush=True)
    resp = requests.get(
        EBIRD_TAXONOMY_URL,
        params={"cat": "species", "locale": "en", "fmt": "json"},
        headers={"X-eBirdApiToken": api_key},
        timeout=60,
    )
    resp.raise_for_status()
    taxa = resp.json()
    print(f"  → {len(taxa)} species in taxonomy", flush=True)

    by_sci = {}
    for t in taxa:
        by_sci[t["sciName"]] = {
            "speciesCode":  t["speciesCode"],
            "comName":      t["comName"],
            "taxonOrder":   float(t.get("taxonOrder", 0)),
            "order":        t.get("order", "Unknown Order"),
            "familyComName":t.get("familyComName", "Unknown Family"),
            "familySciName":t.get("familySciName", ""),
        }
    return by_sci


def load_india_species(csv_path: Path) -> list[dict]:
    """
    Read eBird personal data CSV, filter to India observations,
    and return a deduplicated list of {comName, sciName}.

    eBird CSV columns include:
      'Scientific Name', 'Common Name', 'State/Province', 'Taxonomic Order'
    State/Province codes for India look like: IN-KA, IN-MH, IN-DL …
    """
    print(f"Reading {csv_path}…", flush=True)
    seen_sci: set[str] = set()
    species: list[dict] = []

    with open(csv_path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            state = row.get("State/Province", "")
            if not state.startswith(INDIA_PREFIX):
                continue
            sci = row.get("Scientific Name", "").strip()
            com = row.get("Common Name", "").strip()
            if sci and sci not in seen_sci:
                seen_sci.add(sci)
                species.append({"comName": com, "sciName": sci})

    print(f"  → {len(species)} unique species from India", flush=True)
    return species


def build_json(india_species: list[dict], taxonomy: dict) -> dict:
    """
    Merge personal India list with taxonomy data.
    Returns the final dict ready for JSON serialisation.
    """
    enriched = []
    unmatched = []

    for sp in india_species:
        sci = sp["sciName"]
        tx  = taxonomy.get(sci)
        if tx is None:
            # Try a loose match on the first two words (handles ssp. in CSV)
            base = " ".join(sci.split()[:2])
            tx = taxonomy.get(base)
        if tx is None:
            unmatched.append(sci)
            # Still include it with minimal data so nothing is silently dropped
            enriched.append({
                "comName":      sp["comName"],
                "sciName":      sci,
                "speciesCode":  "",
                "taxonOrder":   99999,
                "order":        "Unmatched",
                "familyComName":"Unmatched",
                "familySciName":"",
            })
        else:
            enriched.append({
                "comName":      sp["comName"],
                "sciName":      sci,
                "speciesCode":  tx["speciesCode"],
                "taxonOrder":   tx["taxonOrder"],
                "order":        tx["order"],
                "familyComName":tx["familyComName"],
                "familySciName":tx["familySciName"],
            })

    if unmatched:
        print(f"  ⚠ {len(unmatched)} species not matched in taxonomy:", flush=True)
        for s in unmatched[:10]:
            print(f"      {s}", flush=True)
        if len(unmatched) > 10:
            print(f"      … and {len(unmatched)-10} more", flush=True)

    # Sort by taxonomic order
    enriched.sort(key=lambda x: x["taxonOrder"])

    # Group by Order → Family
    orders_map: dict[str, dict] = {}
    for sp in enriched:
        ord_name = sp["order"]
        fam_name = sp["familyComName"]

        if ord_name not in orders_map:
            orders_map[ord_name] = {"name": ord_name, "families": {}}
        fam_map = orders_map[ord_name]["families"]
        if fam_name not in fam_map:
            fam_map[fam_name] = {
                "name":       fam_name,
                "sciName":    sp["familySciName"],
                "species":    [],
            }
        fam_map[fam_name]["species"].append({
            "comName":     sp["comName"],
            "sciName":     sp["sciName"],
            "speciesCode": sp["speciesCode"],
        })

    # Flatten to lists (order is preserved because enriched is already sorted)
    orders_list = []
    for ord_name, ord_data in orders_map.items():
        families_list = [fam for fam in ord_data["families"].values()]
        orders_list.append({
            "name":     ord_name,
            "count":    sum(len(f["species"]) for f in families_list),
            "families": families_list,
        })

    return {
        "generated":   datetime.now(timezone.utc).isoformat(),
        "total_seen":  len([s for s in enriched if s["speciesCode"]]),
        "orders":      orders_list,
    }


def main():
    parser = argparse.ArgumentParser(description="Build birds.json from eBird export + taxonomy")
    parser.add_argument("--api-key", default=os.environ.get("EBIRD_API_KEY"), help="eBird API key")
    parser.add_argument("--csv",     default="MyEBirdData.csv", help="Path to eBird CSV export")
    parser.add_argument("--out",     default="birds.json",      help="Output JSON path")
    args = parser.parse_args()

    if not args.api_key:
        sys.exit("Error: eBird API key required (--api-key or EBIRD_API_KEY env var)")

    csv_path = Path(args.csv)
    if not csv_path.exists():
        sys.exit(f"Error: CSV not found at {csv_path}")

    taxonomy       = fetch_taxonomy(args.api_key)
    india_species  = load_india_species(csv_path)
    result         = build_json(india_species, taxonomy)

    out_path = Path(args.out)
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"\n✓ Written {result['total_seen']} species across {len(result['orders'])} orders → {out_path}")


if __name__ == "__main__":
    main()
