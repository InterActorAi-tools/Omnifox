"""Encryption of personal data at rest (files and database columns).

Fernet = AES-128-CBC + HMAC-SHA256. DATA_ENCRYPTION_KEY may hold several
comma-separated keys: the first encrypts, every key can decrypt, so a key
can be rotated without losing old data.
"""
import json
import os

from cryptography.fernet import Fernet, MultiFernet
from sqlalchemy.types import Text, TypeDecorator

from config import settings

_fernet = MultiFernet([Fernet(k.strip()) for k in settings.data_encryption_key.split(",") if k.strip()])


def encrypt(data: bytes) -> bytes:
    return _fernet.encrypt(data)


def decrypt(token: bytes) -> bytes:
    return _fernet.decrypt(token)


def rotate(token: bytes) -> bytes:
    """Re-encrypt a token with the first (newest) key."""
    return _fernet.rotate(token)


def is_encrypted(data: bytes) -> bool:
    # Every Fernet token starts with version byte 0x80, base64 "gAAAAA".
    return data.startswith(b"gAAAAA")


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
        if is_encrypted(f.read(6)):
            return False
        f.seek(0)
        data = f.read()
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
