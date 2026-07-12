"""Identifier helpers. ULID-like ids are lexicographically sortable by time, which is
convenient for event ordering and debugging."""

from __future__ import annotations

import os
import time

_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def ulid_like() -> str:
    """A 26-char Crockford-base32 id: 48-bit timestamp + 80 bits of randomness."""
    ts = int(time.time() * 1000)
    ts_part = _encode(ts, 10)
    rnd = int.from_bytes(os.urandom(10), "big")
    rnd_part = _encode(rnd, 16)
    return ts_part + rnd_part


def new_id(prefix: str) -> str:
    return f"{prefix}_{ulid_like()}"


def _encode(value: int, length: int) -> str:
    chars = []
    for _ in range(length):
        value, rem = divmod(value, 32)
        chars.append(_ALPHABET[rem])
    return "".join(reversed(chars))
