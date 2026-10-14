"""Bounded current numeric formats shared by immutable terrain and context products."""

import io
from math import prod
from typing import Any, cast
from zipfile import BadZipFile, ZipFile

import numpy as np
from numpy.typing import NDArray


def read_numeric_array(data: bytes, shape: tuple[int, ...], dtype: str, label: str) -> NDArray[Any]:
    """Validate the NPY header and exact payload length before NumPy allocates."""
    stream = io.BytesIO(data)
    try:
        version = np.lib.format.read_magic(stream)
        if version != (1, 0):
            raise ValueError("Only current NPY v1 numeric payloads are supported.")
        actual_shape, fortran, actual_dtype = np.lib.format.read_array_header_1_0(stream)
        expected = np.dtype(dtype)
        if (
            actual_shape != shape
            or fortran
            or actual_dtype != expected
            or len(data) - stream.tell() != prod(shape) * expected.itemsize
        ):
            raise ValueError("Array shape, dtype, order or payload length mismatch.")
        stream.seek(0)
        result = cast(NDArray[Any], np.load(stream, allow_pickle=False))
        result.setflags(write=False)
        return result
    except (OSError, ValueError, EOFError) as error:
        raise ValueError(f"Invalid numeric array {label}: {error}") from error


def read_numeric_archive(
    data: bytes,
    specs: dict[str, tuple[tuple[int, ...], str]],
) -> dict[str, NDArray[Any]]:
    """Require exact members and cap decompression before reading any NPY payload."""
    try:
        with ZipFile(io.BytesIO(data)) as archive:
            expected = {f"{key}.npy" for key in specs}
            if set(archive.namelist()) != expected or len(archive.namelist()) != len(expected):
                raise ValueError("Numeric archive members do not match the current contract.")
            arrays: dict[str, NDArray[Any]] = {}
            for key, (shape, dtype) in specs.items():
                info = archive.getinfo(f"{key}.npy")
                limit = prod(shape) * np.dtype(dtype).itemsize + 10_000
                if info.file_size > limit or info.flag_bits & 1:
                    raise ValueError("Oversized or encrypted numeric archive entry.")
                with archive.open(info) as stream:
                    payload = stream.read(limit + 1)
                if len(payload) > limit:
                    raise ValueError("Numeric archive expanded beyond its admitted size.")
                arrays[key] = read_numeric_array(payload, shape, dtype, key)
            return arrays
    except (BadZipFile, KeyError, OSError, EOFError, NotImplementedError) as error:
        raise ValueError(f"Invalid numeric archive: {error}") from error
