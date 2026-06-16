import csv

from typing import Optional

ISLANDS_CSV = "data/islands.csv"

# name -> {url, next, logduration, q, r}
_islands: dict = {}

# Marine facilities that aren't in the CSV but should be navigable destinations.
# Tile rendering for these lives in map_render.py (GRAY_FACILITIES / IMPEL_DOWN);
# keep the centers below in sync with that file.
SPECIAL_ISLANDS = {
    "Impel Down":     (180,   0),
    "Marine Base G8": ( 50,  11),
    "Marine Base G6": (111, -25),
    "Marineford":     (228, -20),
}


def _register_special():
    """Inject the marine facilities into the island list (idempotent)."""
    for name, (q, r) in SPECIAL_ISLANDS.items():
        _islands.setdefault(name, {
            "url":         "",
            "next":        "",
            "logduration": "",
            "q":           q,
            "r":           r,
        })


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
    _register_special()


def get_island(name: str) -> Optional[dict]:
    return _islands.get(name)


def get_all() -> dict:
    return _islands


def get_urls() -> dict:
    return {name: data["url"] for name, data in _islands.items()}
