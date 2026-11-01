"""Settings and threshold loading. Plant thresholds may only override known keys."""

from pathlib import Path

import yaml

DEFAULT_THRESHOLDS = Path(__file__).parent / "thresholds" / "default.yaml"
UNIT_SUFFIXES = ("_process_s", "_wall_s", "_kpa", "_pct", "_per_process_s", "_samples")


def _read(path: Path) -> dict:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8-sig")) or {}


def load_thresholds(plant_file: str | Path | None = None) -> dict:
    base = _read(DEFAULT_THRESHOLDS)
    plant = _read(plant_file) if plant_file else {}
    unknown = set(plant) - set(base)
    if unknown:
        raise ValueError(f"unknown threshold keys in {plant_file}: {sorted(unknown)}")
    bad = [k for k in base if k != "version" and not k.endswith(UNIT_SUFFIXES)]
    if bad:
        raise ValueError(f"threshold names must end in a unit: {bad}")
    merged = {**base, **plant}
    merged["version"] = f"{base['version']}+{plant.get('version', 'none')}"
    return merged
