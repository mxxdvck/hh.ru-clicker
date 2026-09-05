"""Encrypted-at-rest JSON storage for cookies, OAuth tokens and API keys.

Windows uses DPAPI bound to the current user. Linux/macOS use AES-GCM when
HH_BOT_DATA_KEY is set. Without an available backend files remain plaintext
for backward compatibility unless HH_BOT_REQUIRE_ENCRYPTION=1.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

MAGIC = "_hh_secure_store"
VERSION = 1
AAD = b"hh.ru-clicker:secure-store:v1"


class SecureStoreError(RuntimeError):
    pass


def backend_name() -> str:
    disabled = os.environ.get("HH_BOT_DISABLE_DATA_ENCRYPTION", "").strip().lower()
    if disabled in {"1", "true", "yes", "on"}:
        return "plaintext"
    # An explicit key wins on every OS and makes encrypted data portable.
    if os.environ.get("HH_BOT_DATA_KEY", "").strip():
        return "aesgcm"
    if os.name == "nt":
        return "dpapi"
    return "plaintext"


def _dpapi_transform(data: bytes, decrypt: bool = False) -> bytes:
    if os.name != "nt":
        raise SecureStoreError("DPAPI is only available on Windows")
    import ctypes
    from ctypes import wintypes

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD),
                    ("pbData", ctypes.POINTER(ctypes.c_byte))]

    buf = ctypes.create_string_buffer(data)
    in_blob = DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_byte)))
    out_blob = DATA_BLOB()
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    flags = 0x1  # CRYPTPROTECT_UI_FORBIDDEN
    func = crypt32.CryptUnprotectData if decrypt else crypt32.CryptProtectData
    func.restype = wintypes.BOOL
    # ctypes defaults are unsafe for pointer-sized Windows handles on 64-bit.
    kernel32.LocalFree.argtypes = [wintypes.HLOCAL]
    kernel32.LocalFree.restype = wintypes.HLOCAL
    ok = func(ctypes.byref(in_blob), None, None, None, None, flags, ctypes.byref(out_blob))
    if not ok:
        raise ctypes.WinError()
    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        kernel32.LocalFree(ctypes.cast(out_blob.pbData, wintypes.HLOCAL))


def _aes_key() -> bytes:
    raw = os.environ.get("HH_BOT_DATA_KEY", "").strip()
    if not raw:
        raise SecureStoreError("HH_BOT_DATA_KEY is not configured")
    return hashlib.sha256(raw.encode("utf-8")).digest()


def protect_bytes(data: bytes, provider: str | None = None) -> tuple[str, bytes]:
    provider = provider or backend_name()
    if provider == "dpapi":
        return provider, _dpapi_transform(data)
    if provider == "aesgcm":
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        nonce = os.urandom(12)
        ciphertext = AESGCM(_aes_key()).encrypt(nonce, data, AAD)
        return provider, nonce + ciphertext
    if provider == "plaintext":
        return provider, data
    raise SecureStoreError(f"Unknown secure-store provider: {provider}")


def unprotect_bytes(provider: str, payload: bytes) -> bytes:
    if provider == "dpapi":
        return _dpapi_transform(payload, decrypt=True)
    if provider == "aesgcm":
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        return AESGCM(_aes_key()).decrypt(payload[:12], payload[12:], AAD)
    if provider == "plaintext":
        return payload
    raise SecureStoreError(f"Unknown secure-store provider: {provider}")


def _envelope(data: Any, provider: str) -> dict:
    raw = json.dumps(data, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8")
    provider, encrypted = protect_bytes(raw, provider)
    return {
        MAGIC: VERSION,
        "provider": provider,
        "payload": base64.b64encode(encrypted).decode("ascii"),
    }


def encode_envelope(data: Any, provider: str | None = None) -> dict:
    provider = provider or backend_name()
    if provider == "plaintext":
        if encryption_required():
            raise SecureStoreError("Encryption is required but no secure backend is configured")
        raise SecureStoreError("No encrypted secure-store backend is configured")
    return _envelope(data, provider)


def is_secure_envelope(value: Any) -> bool:
    return isinstance(value, dict) and value.get(MAGIC) == VERSION and "payload" in value


def decode_envelope(value: dict) -> Any:
    try:
        provider = str(value.get("provider") or "")
        if provider not in {"dpapi", "aesgcm"}:
            raise SecureStoreError(
                f"Insecure or unsupported envelope provider: {provider or '<missing>'}"
            )
        payload = base64.b64decode(str(value.get("payload") or ""), validate=True)
        raw = unprotect_bytes(provider, payload)
        return json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise SecureStoreError(f"Cannot decrypt secure JSON: {exc}") from exc


def encryption_required() -> bool:
    return os.environ.get("HH_BOT_REQUIRE_ENCRYPTION", "").strip().lower() in {
        "1", "true", "yes", "on",
    }


def write_json_atomic(path: Path, data: Any, *, encrypt: bool = True) -> str:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Never clobber an encrypted file we cannot decrypt with the current user/key.
    # This turns a wrong/missing key into a hard failure instead of silent data loss.
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            existing = None
        if is_secure_envelope(existing):
            try:
                decode_envelope(existing)
            except SecureStoreError as exc:
                raise SecureStoreError(
                    f"Refusing to overwrite encrypted file that cannot be decrypted: {path}"
                ) from exc
    provider = backend_name() if encrypt else "plaintext"
    if encrypt and provider == "plaintext" and encryption_required():
        raise SecureStoreError("Encryption is required but no secure backend is configured")
    value = _envelope(data, provider) if provider != "plaintext" else data
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, default=str)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        tmp.replace(path)
        return provider
    finally:
        tmp.unlink(missing_ok=True)


def read_json(path: Path, default: Any = None, *, migrate: bool = False) -> Any:
    path = Path(path)
    if not path.exists():
        return default
    value = json.loads(path.read_text(encoding="utf-8"))
    if is_secure_envelope(value):
        return decode_envelope(value)
    provider = backend_name()
    if encryption_required() and provider == "plaintext":
        raise SecureStoreError("Encryption is required but plaintext data was found and no secure backend is configured")
    if migrate and provider != "plaintext":
        write_json_atomic(path, value, encrypt=True)
    return value
