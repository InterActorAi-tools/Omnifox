"""Encryption at rest for personal data (files and DB columns)."""
from utils.crypto import EncryptedJSON, EncryptedText, encrypt_file_in_place, is_encrypted, read_file, write_file


def test_file_round_trip_is_encrypted_on_disk(tmp_path):
    path = tmp_path / "result.xlsx"
    write_file(str(path), b"PK secret comments")

    assert b"secret" not in path.read_bytes()
    assert read_file(str(path)) == b"PK secret comments"


def test_legacy_plaintext_file_is_encrypted_once(tmp_path):
    path = tmp_path / "old.xlsx"
    path.write_bytes(b"PK plaintext")

    assert encrypt_file_in_place(str(path)) is True
    assert encrypt_file_in_place(str(path)) is False
    assert is_encrypted(path.read_bytes())
    assert read_file(str(path)) == b"PK plaintext"


def test_column_types_round_trip():
    text, js = EncryptedText(), EncryptedJSON()
    stored = text.process_bind_param("10.0.0.1", None)
    assert "10.0.0.1" not in stored
    assert text.process_result_value(stored, None) == "10.0.0.1"

    stored = js.process_bind_param({"summary": "private"}, None)
    assert "private" not in stored
    assert js.process_result_value(stored, None) == {"summary": "private"}
    assert js.process_bind_param(None, None) is None


def test_legacy_scan_keeps_file_age_and_runs_once(tmp_path, monkeypatch):
    import os
    import config
    from bootstrap import encrypt_legacy_files
    monkeypatch.setattr(config, "UPLOAD_FOLDER", str(tmp_path))
    old = tmp_path / "a@example.com" / "old.xlsx"
    old.parent.mkdir()
    old.write_bytes(b"PK legacy")
    os.utime(old, (1_000_000, 1_000_000))

    assert encrypt_legacy_files() == 1
    assert is_encrypted(old.read_bytes()) and os.path.getmtime(old) == 1_000_000
    (tmp_path / "a@example.com" / "new.xlsx").write_bytes(b"PK later")
    assert encrypt_legacy_files() == 0  # marker: the scan is not repeated on every boot


def test_project_key_that_fits_moves_to_front():
    import contextvars
    from cryptography.fernet import Fernet
    from utils import crypto

    def run():
        a, b = Fernet(Fernet.generate_key()), Fernet(Fernet.generate_key())
        crypto.use_read_keys([a, b])
        assert crypto.decrypt(b.encrypt(b"secret")) == b"secret"
        assert crypto._read_keys.get() == (b, a)

    contextvars.copy_context().run(run)  # keep the test's keys out of other tests
