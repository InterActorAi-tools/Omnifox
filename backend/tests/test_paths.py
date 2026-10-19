"""Tests for backend/utils/paths.py: path-traversal defense.

Covers SECURITY_ASSESSMENT.md C6 - the safe_upload_path helper that
gates user-controlled path components for the download / list / delete /
process endpoints.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi import HTTPException


@pytest.fixture
def upload_dir(tmp_path: Path) -> str:
    """Create a real on-disk upload base directory."""
    base = tmp_path / "uploads"
    base.mkdir()
    return str(base)


# ---- Happy path ------------------------------------------------------------

class TestHappyPath:
    def test_resolves_safe_filename(self, upload_dir):
        from utils.paths import safe_upload_path
        result = safe_upload_path(upload_dir, "client_42", "report.xlsx")
        expected = os.path.join(upload_dir, "client_42", "report.xlsx")
        assert result == os.path.realpath(expected)

    def test_resolves_safe_client_dir_only(self, upload_dir):
        from utils.paths import safe_upload_path
        result = safe_upload_path(upload_dir, "client_42")
        assert result == os.path.realpath(os.path.join(upload_dir, "client_42"))

    def test_allows_email_style_client_id(self, upload_dir):
        from utils.paths import safe_upload_path
        # @ is in the safe set so frontend-style email-as-client-id works.
        result = safe_upload_path(upload_dir, "alice@example.com", "x.xlsx")
        assert result.endswith(os.path.join("alice@example.com", "x.xlsx"))

    def test_allows_plus_addressed_email(self, upload_dir):
        # "ali+work@x.com" is a valid account email; rejecting it blocked
        # uploads, downloads, export and erasure for that user.
        from utils.paths import safe_upload_path
        result = safe_upload_path(upload_dir, "ali+work@example.com", "x.xlsx")
        assert result.endswith(os.path.join("ali+work@example.com", "x.xlsx"))

    def test_allows_dotted_filename(self, upload_dir):
        from utils.paths import safe_upload_path
        result = safe_upload_path(upload_dir, "c1", "report.with.dots.xlsx")
        assert result.endswith("report.with.dots.xlsx")


# ---- Traversal rejection ---------------------------------------------------

class TestTraversalRejection:
    @pytest.mark.parametrize(
        "client_id,filename",
        [
            (".", "config.py"),
            ("..", "config.py"),
            ("client", ".."),
            ("client", "."),
            ("../etc", "passwd"),
            ("client", "../../etc/passwd"),
            ("client/../other", "x.xlsx"),
            ("client", "x/y.xlsx"),
            ("client", "x\\y.xlsx"),
            ("", "x.xlsx"),
            ("client", ""),
        ],
    )
    def test_rejects_traversal_or_separators(self, upload_dir, client_id, filename):
        from utils.paths import safe_upload_path
        with pytest.raises(HTTPException) as exc:
            safe_upload_path(upload_dir, client_id, filename)
        assert exc.value.status_code == 400

    @pytest.mark.parametrize(
        "bad_char",
        [
            "client id",      # space
            "client;rm",      # shell metachar
            "client$x",       # shell metachar
            "client\0null",   # null byte
            "client\nnl",     # newline
            "client%20",      # URL escape that the regex would not undo
            "client'or'1",    # SQL-style injection chars
        ],
    )
    def test_rejects_special_chars(self, upload_dir, bad_char):
        from utils.paths import safe_upload_path
        with pytest.raises(HTTPException) as exc:
            safe_upload_path(upload_dir, bad_char, "x.xlsx")
        assert exc.value.status_code == 400

    def test_rejects_empty_args(self, upload_dir):
        from utils.paths import safe_upload_path
        with pytest.raises(HTTPException):
            safe_upload_path(upload_dir)


# ---- Symlink escape rejection ---------------------------------------------

class TestSymlinkRejection:
    def test_rejects_symlink_pointing_outside_base(self, tmp_path):
        """If an attacker plants a symlink inside the upload dir that
        points to /etc, the realpath check must still reject the resolved
        path because it falls outside the realpath of base."""
        from utils.paths import safe_upload_path
        base = tmp_path / "uploads"
        base.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "secret").write_text("PWN")
        # Symlink: <base>/escape -> <outside>
        (base / "escape").symlink_to(outside)

        # Component name "escape" matches the safe regex, so the regex
        # alone would pass. The realpath check is what catches it.
        with pytest.raises(HTTPException) as exc:
            safe_upload_path(str(base), "escape", "secret")
        assert exc.value.status_code == 400
