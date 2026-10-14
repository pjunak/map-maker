"""Authored documents saved beside a world: hashed reads and atomic replacement."""

import os
import tempfile
from hashlib import sha256
from pathlib import Path


def document_file_hash(path: Path, max_bytes: int, label: str) -> str | None:
    """The file's SHA-256, or None when it does not exist yet."""
    try:
        with path.open("rb") as stream:
            raw = stream.read(max_bytes + 1)
    except FileNotFoundError:
        return None
    if len(raw) > max_bytes:
        raise ValueError(
            f"Existing {label} file exceeds {max_bytes // (1024 * 1024)} MiB; "
            "choose another path."
        )
    return sha256(raw).hexdigest()


def write_document(
    path: Path, data: bytes, expected_hash: str | None, max_bytes: int, label: str
) -> str:
    """Replace ``path`` atomically with ``data``; returns its SHA-256.

    ``expected_hash`` is the file's hash when it was opened (None for a new file),
    so a file changed or created by something else is never overwritten.
    """
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=path.parent, prefix=f".{label.replace(' ', '-')}-", delete=False
        ) as stream:
            temporary = stream.name
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if document_file_hash(path, max_bytes, label) != expected_hash:
            raise ValueError(
                f"{label.capitalize()} file changed outside the editor. Reopen it or use Save As."
            )
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            Path(temporary).unlink(missing_ok=True)
    return sha256(data).hexdigest()
