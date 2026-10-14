"""Versioned, language-neutral seed derivation for named terrain stages."""

import re
from hashlib import sha256

SEED_POLICY_ID = "named-stage-sha256@1"
RELIEF_STAGE_ID = "terrain.relief"
LANDFORM_STAGE_ID = "terrain.landforms"
LOCAL_DETAIL_STAGE_ID = "terrain.local-detail"
_SEED_DOMAIN = b"dmtools.terrain-stage-seed@1\x00"
_STAGE_NAME = re.compile(r"[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*", re.ASCII)
MAX_MASTER_SEED = 0xFFFFFFFF


def validate_master_seed(seed: object) -> None:
    if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed <= MAX_MASTER_SEED:
        raise ValueError(f"Seed must be an integer between 0 and {MAX_MASTER_SEED:,}.")


def stage_seed(master_seed: int, stage_id: str) -> int:
    """Resolve one stream without depending on stage order, grid or process state.

    Named policy hashes the domain bytes, a four-byte big-endian unsigned
    master seed and an ASCII stage identifier; the first four digest bytes
    are interpreted as an unsigned big-endian integer. Names identify stages
    in build records; they are not user-facing labels. This is not a cryptographic secret.
    """
    validate_master_seed(master_seed)
    if not 1 <= len(stage_id) <= 128 or _STAGE_NAME.fullmatch(stage_id) is None:
        raise ValueError("Stage identifier must be 1-128 lowercase ASCII name characters.")
    payload = _SEED_DOMAIN + master_seed.to_bytes(4, "big") + stage_id.encode("ascii")
    return int.from_bytes(sha256(payload).digest()[:4], "big")
