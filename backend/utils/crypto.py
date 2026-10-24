"""Encryption of personal data at rest (files and database columns).

Fernet = AES-128-CBC + HMAC-SHA256. DATA_ENCRYPTION_KEY may hold several
comma-separated keys: the first encrypts, every key can decrypt, so a key
can be rotated without losing old data.
"""
import json
import os
import re

from cryptography.fernet import Fernet, MultiFernet
from sqlalchemy.types import Text, TypeDecorator

from config import settings

_fernet = MultiFernet([Fernet(k.strip()) for k in settings.data_encryption_key.split(",") if k.strip()])
_BASE64URL = re.compile(rb"[A-Za-z0-9_-]+={0,2}")


def encrypt(data: bytes) -> bytes:
    return _fernet.encrypt(data)


def decrypt(token: bytes) -> bytes:
    return _fernet.decrypt(token)


def rotate(token: bytes) -> bytes:
    """Re-encrypt a token with the first (newest) key."""
    return _fernet.rotate(token)


def is_encrypted(data: bytes) -> bool:
    """True for a Fernet token: base64 of version byte 0x80 + timestamp + IV +
    AES blocks + HMAC. Checking the whole layout, not just the "gAAAAA"
    prefix, keeps plain text such as a User-Agent from being mistaken for one."""
    if not data.startswith(b"gAAAAA") or len(data) % 4 or not _BASE64URL.fullmatch(data):
        return False
    raw_len = len(data) // 4 * 3 - data[-2:].count(b"=")
    return raw_len >= 73 and (raw_len - 57) % 16 == 0


def write_file(path: str, data: bytes) -> None:
    """Write bytes to disk encrypted. Temp file + rename so readers never see half a file."""
    tmp = f"{path}.tmp"
    with open(tmp, "wb") as f:
        f.write(encrypt(data))
    os.replace(tmp, path)


def read_file(path: str) -> bytes:
    """Read and decrypt a file written by write_file()."""
    with open(path, "rb") as f:
        return decrypt(f.read())


def encrypt_file_in_place(path: str) -> bool:
    """Encrypt a legacy plaintext file, keeping its age for retention.
    Returns False if it already was encrypted."""
    with open(path, "rb") as f:
        data = f.read()
    if is_encrypted(data):
        return False
    modified = os.path.getmtime(path)
    write_file(path, data)
    os.utime(path, (modified, modified))
    return True


class EncryptedText(TypeDecorator):
    """A text column stored encrypted. Not searchable: never filter on it."""
    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        return encrypt(str(value).encode()).decode()

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return decrypt(value.encode()).decode()


class EncryptedJSON(EncryptedText):
    """A JSON value stored as encrypted text."""
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        return super().process_bind_param(json.dumps(value, default=str), dialect)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return json.loads(super().process_result_value(value, dialect))
