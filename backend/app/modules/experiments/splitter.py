"""Deterministic splitter (TZ 3.4, Should): the same user always gets the same variant of an experiment.

bucket = sha256(salt:experiment_key:user_id) mod 10000. The first ``traffic_share`` of buckets take part
in the experiment; within them buckets are split by variant weights. SDKs can reproduce it locally
(same algorithm in TS/Kotlin/Swift/C#) or call the assignment API.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence

BUCKETS = 10_000


def bucket(salt: str, experiment_key: str, user_id: str) -> int:
    digest = hashlib.sha256(f"{salt}:{experiment_key}:{user_id}".encode()).digest()
    return int.from_bytes(digest[:8], "big") % BUCKETS


def assign(
    experiment_key: str,
    user_id: str,
    variants: Sequence[tuple[str, float]],
    traffic_share: float = 1.0,
    salt: str = "v1",
) -> str | None:
    """Returns the variant key or ``None`` when the user is outside the experiment traffic."""
    b = bucket(salt, experiment_key, user_id)
    in_traffic = round(traffic_share * BUCKETS)
    if b >= in_traffic:
        return None
    # second, independent hash for the variant so that changing traffic does not reshuffle variants
    v = bucket(salt + ":variant", experiment_key, user_id) / BUCKETS
    total = sum(w for _, w in variants)
    acc = 0.0
    for key, weight in variants:
        acc += weight / total
        if v < acc:
            return key
    return variants[-1][0]
