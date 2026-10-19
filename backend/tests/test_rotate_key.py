"""`python -m cli rotate-key`: after it runs, data decrypts with the new key alone."""
import os

from cryptography.fernet import Fernet, MultiFernet


def test_rotate_key_reencrypts_rows_and_files(task_db_session_factory, tmp_path, monkeypatch):
    import cli
    import config
    import database
    import utils.crypto as crypto
    from models import Task

    old, new = Fernet.generate_key(), Fernet.generate_key()
    monkeypatch.setattr(config, "UPLOAD_FOLDER", str(tmp_path))
    monkeypatch.setattr(database, "engine", task_db_session_factory.kw["bind"])

    monkeypatch.setattr(crypto, "_fernet", MultiFernet([Fernet(old)]))
    with task_db_session_factory() as db:
        db.add(Task(task_id="t1", client_id="a@x.com", status="completed", message="private", result_data={"s": 1}))
        db.commit()
    (tmp_path / "a@x.com").mkdir()
    crypto.write_file(str(tmp_path / "a@x.com" / "r.xlsx"), b"PK result")
    os.utime(tmp_path / "a@x.com" / "r.xlsx", (1_000_000, 1_000_000))

    monkeypatch.setattr(crypto, "_fernet", MultiFernet([Fernet(new), Fernet(old)]))
    assert cli.main(["rotate-key"]) == 0

    monkeypatch.setattr(crypto, "_fernet", MultiFernet([Fernet(new)]))  # old key removed
    with task_db_session_factory() as db:
        task = db.get(Task, "t1")
        assert task.message == "private" and task.result_data == {"s": 1}
    assert crypto.read_file(str(tmp_path / "a@x.com" / "r.xlsx")) == b"PK result"
    assert os.path.getmtime(tmp_path / "a@x.com" / "r.xlsx") == 1_000_000
