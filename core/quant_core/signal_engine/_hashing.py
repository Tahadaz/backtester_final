"""Deterministic variant ID hashing for the signal engine.

Separate from wfo_utils.compute_trial_id which filters to strategy.*/portfolio.* keys.
The signal engine uses plain param keys (window, fast, slow, archetype, etc.).
"""

import hashlib
import json


def compute_variant_id(family: str, params: dict) -> str:
    """Return a stable ``sv_<hex16>`` identifier for a (family, params) pair.

    Prefix ``sv_`` (signal variant) distinguishes from wfo_utils ``p_`` hashes.
    """
    canonical = {"_family": family.strip().lower()}
    canonical.update(dict(sorted(params.items())))
    content = json.dumps(
        canonical,
        sort_keys=True,
        ensure_ascii=False,
        allow_nan=False,
        default=str,
    )
    hex16 = hashlib.sha256(content.encode()).hexdigest()[:16]
    return f"sv_{hex16}"
