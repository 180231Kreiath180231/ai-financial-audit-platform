from __future__ import annotations

import ctypes
import os
import uuid
from ctypes import wintypes
from pathlib import Path


class SecretStoreUnavailable(RuntimeError):
    pass


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


def _protect_windows(value: bytes) -> bytes:
    source_buffer = ctypes.create_string_buffer(value)
    source = _DataBlob(len(value), ctypes.cast(source_buffer, ctypes.POINTER(ctypes.c_byte)))
    protected = _DataBlob()
    crypt32 = ctypes.windll.crypt32
    if not crypt32.CryptProtectData(
        ctypes.byref(source),
        "Hengjian model credential",
        None,
        None,
        None,
        0x1,
        ctypes.byref(protected),
    ):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(protected.pbData, protected.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(protected.pbData)


def _unprotect_windows(value: bytes) -> bytes:
    source_buffer = ctypes.create_string_buffer(value)
    source = _DataBlob(len(value), ctypes.cast(source_buffer, ctypes.POINTER(ctypes.c_byte)))
    clear = _DataBlob()
    if not ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(source), None, None, None, None, 0x1, ctypes.byref(clear)
    ):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(clear.pbData, clear.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(clear.pbData)


class DpapiSecretStore:
    """Stores only DPAPI ciphertext on disk and returns opaque references to SQLite."""

    prefix = "dpapi:"

    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def put(self, value: str) -> str:
        if os.name != "nt":
            raise SecretStoreUnavailable("DPAPI is only available on Windows")
        secret_id = str(uuid.uuid4())
        target = self.root / f"{secret_id}.bin"
        temporary = self.root / f".{secret_id}.tmp"
        temporary.write_bytes(_protect_windows(value.encode("utf-8")))
        temporary.replace(target)
        return f"{self.prefix}{secret_id}"

    def get(self, reference: str) -> str:
        secret_id = self._parse_reference(reference)
        if os.name != "nt":
            raise SecretStoreUnavailable("DPAPI is only available on Windows")
        return _unprotect_windows((self.root / f"{secret_id}.bin").read_bytes()).decode("utf-8")

    def delete(self, reference: str | None) -> None:
        if not reference:
            return
        secret_id = self._parse_reference(reference)
        (self.root / f"{secret_id}.bin").unlink(missing_ok=True)

    def _parse_reference(self, reference: str) -> str:
        if not reference.startswith(self.prefix):
            raise ValueError("Unsupported secret reference")
        secret_id = reference.removeprefix(self.prefix)
        parsed = uuid.UUID(secret_id)
        if str(parsed) != secret_id:
            raise ValueError("Invalid secret reference")
        return secret_id
