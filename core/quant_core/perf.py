"""Lightweight wall-clock timing helpers for the backtester pipeline.

Designed for zero-allocation use in production: each ``lap()`` call allocates
only a single float and two dict operations.  No global state.
"""
from __future__ import annotations

import time
import logging
from contextlib import contextmanager
from typing import Any, Generator

_logger = logging.getLogger(__name__)


@contextmanager
def lap(
    label: str,
    sink: "dict[str, Any]",
    *,
    log: bool = False,
) -> "Generator[None, None, None]":
    """Measure elapsed wall-clock time of a code block and record the result.

    The value stored in *sink* is a ``float`` (milliseconds, rounded to 2 dp).
    If *label* already exists in *sink* it is **overwritten** (last-writer wins).

    Parameters
    ----------
    label:
        Key name written into *sink*.
    sink:
        Plain ``dict``; mutated in-place.
    log:
        When ``True``, emit a single ``INFO`` log line after the block finishes.

    Example::

        phases: dict = {}
        with lap("load_ms", phases, log=True):
            data = load_bars()
        # phases == {"load_ms": 134.56}
    """
    t0 = time.perf_counter()
    try:
        yield
    finally:
        ms = (time.perf_counter() - t0) * 1000.0
        sink[label] = round(ms, 2)
        if log:
            _logger.info("[perf] %s %.1f ms", label, ms)
