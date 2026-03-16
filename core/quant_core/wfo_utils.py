"""WFO shared utilities — no imports from execute_run.py or pipeline.py."""
import hashlib
import json
import re


def _normalize_strategy_kind(sk: str) -> str:
    return sk.strip().lower()


def _canonical_variant_params(strategy_kind: str, raw_params: dict) -> dict:
    """Return the canonical dict used for trial_id hashing.

    Keeps only keys starting with ``strategy.`` or ``portfolio.``.
    Prepends ``_sk`` (normalised strategy_kind) so different strategy kinds
    with identical numeric params always produce different hashes.
    """
    keep = {
        k: v
        for k, v in raw_params.items()
        if k.startswith("strategy.") or k.startswith("portfolio.")
    }
    canonical: dict = {"_sk": _normalize_strategy_kind(strategy_kind)}
    canonical.update(dict(sorted(keep.items())))
    return canonical


def compute_trial_id(strategy_kind: str, raw_params: dict) -> str:
    """Return a stable ``p_<hex16>`` identifier for a (strategy_kind, params) pair.

    The algorithm is deterministic and ordering-invariant:
    - Builds canonical dict (strategy.* / portfolio.* keys only, plus _sk prefix)
    - json.dumps with sort_keys=True → sha256 → first 16 hex chars
    - Prefix "p_" distinguishes from other hash namespaces

    Does NOT import from execute_run.py — safe to import from both worker and API.
    """
    canonical = _canonical_variant_params(strategy_kind, raw_params)
    content = json.dumps(
        canonical,
        sort_keys=True,
        ensure_ascii=False,
        allow_nan=False,
        default=str,
    )
    hex16 = hashlib.sha256(content.encode()).hexdigest()[:16]
    return f"p_{hex16}"
