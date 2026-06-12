import csv

from typing import Optional

ISLANDS_CSV = "data/islands.csv"

# name -> {url, next, logduration, q, r}
_islands: dict = {}


def load_islands():
    global _islands
    try:
        with open(ISLANDS_CSV, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                name = (row.get("island") or "").strip()
                if not name:
                    continue
                q_raw = (row.get("q") or "").strip()
                r_raw = (row.get("r") or "").strip()
                _islands[name] = {
                    "url":         (row.get("url")         or "").strip(),
                    "next":        (row.get("next")        or "").strip(),
                    "logduration": (row.get("logduration") or "").strip(),
                    "q":           int(q_raw) if q_raw else None,
                    "r":           int(r_raw) if r_raw else None,
                }
        print(f"[islands] loaded {len(_islands)} island entries")
    except FileNotFoundError:
        print("[islands] data/islands.csv not found")


def get_island(name: str) -> Optional[dict]:
    return _islands.get(name)


def get_all() -> dict:
    return _islands


def get_urls() -> dict:
    return {name: data["url"] for name, data in _islands.items()}
