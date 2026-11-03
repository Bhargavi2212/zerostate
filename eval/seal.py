"""Seal a benchmark batch: draw scoring seeds, write the manifest and a random salt OUTSIDE the repo,
and write only sha256(salt + manifest) into eval/sealed_hash_<batch>.txt, to be committed before the
first scoring episode. After scoring, publishing the manifest and salt lets anyone check the hash.

    python eval/seal.py --batch p1
"""

import argparse
import hashlib
import json
import os
import random
from pathlib import Path

ROOT = Path(__file__).parents[1]
SEALED = Path(os.environ.get("ZS_SEALED", r"D:\grfics\sealed"))
P1_FAULTS = ("S1", "S1b", "S2", "S3", "S4-small", "S4-large", "S5", "S6", "S8", "S12")
BATCHES = {
    "p1": [("p1", "S0", 15)] + [("p1", s, 5) for s in P1_FAULTS],  # headline, phase-1.1 code, no S7
    "dryrun": [("p1", "S0", 1)],  # exercises the scoring path once; never part of a result
}
MIN_SCORING_SEED = 10000


def digest(salt: bytes, manifest: bytes) -> str:
    return hashlib.sha256(salt + manifest).hexdigest()


def draw(batch: str) -> list[dict]:
    rng = random.SystemRandom()  # os.urandom underneath: nobody, including us, picks the seeds
    seen, entries = set(), []
    for plant, scenario, n in BATCHES[batch]:
        for _ in range(n):
            seed = rng.randrange(MIN_SCORING_SEED, 2**31)
            while seed in seen:
                seed = rng.randrange(MIN_SCORING_SEED, 2**31)
            seen.add(seed)
            entries.append({"plant": plant, "scenario": scenario, "seed": seed})
    rng.shuffle(entries)  # interleave scenarios so slow lab drift can't line up with one of them
    return entries


def paths(batch: str, sealed: Path = SEALED) -> tuple[Path, Path, Path]:
    return sealed / f"manifest_{batch}.json", sealed / f"salt_{batch}", ROOT / "eval" / f"sealed_hash_{batch}.txt"


def seal(batch: str, sealed: Path = SEALED) -> str:
    manifest_p, salt_p, hash_p = paths(batch, sealed)
    if manifest_p.exists() or salt_p.exists():
        raise SystemExit(f"{manifest_p} already exists: a batch is sealed once")
    sealed.mkdir(parents=True, exist_ok=True)
    manifest = json.dumps({"batch": batch, "entries": draw(batch)}, indent=1).encode()
    salt = os.urandom(32).hex().encode()
    manifest_p.write_bytes(manifest)
    salt_p.write_bytes(salt)
    h = digest(salt, manifest)
    hash_p.write_text(h + "\n", encoding="utf-8")
    return h


def load(manifest_p: Path, salt_p: Path) -> tuple[dict, str]:
    """The manifest and its hash, computed over the exact bytes on disk."""
    manifest = Path(manifest_p).read_bytes()
    return json.loads(manifest), digest(Path(salt_p).read_bytes(), manifest)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch", required=True, choices=sorted(BATCHES))
    a = ap.parse_args()
    h = seal(a.batch)
    manifest_p, _, hash_p = paths(a.batch)
    print(f"sealed {a.batch}: {manifest_p} (keep outside the repo); commit {hash_p.relative_to(ROOT)} = {h}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
