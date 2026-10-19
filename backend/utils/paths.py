"""
Path-safety helpers for user-supplied filesystem paths.

The download, list, and delete endpoints used to do:

    os.path.join(UPLOAD_FOLDER, client_id, filename)

with no validation. An authenticated user could send `client_id="."` and
`filename="../config.py"` to read backend source. `safe_upload_path()`
defends against that by validating each path component against an
allowlist character class AND verifying the resolved path stays inside
the base directory.

The helper is HTTP-aware: it raises HTTPException(400) on any rejection
so endpoints can use it inline without a separate try/except.
"""
from __future__ import annotations

import os
import re

from fastapi import HTTPException


# Components that look the same on disk but are special in path semantics.
_FORBIDDEN_COMPONENTS = frozenset({"", ".", ".."})

# What we accept as a filesystem-safe component. Conservative on purpose:
# letters, digits, underscore, hyphen, dot - covers UUIDs, timestamps,
# typical filenames (foo.xlsx), and email-as-client-id (alice@x.com -> @
# blocked, but the upload code prefixes client_id with sanitization
# elsewhere; an email-derived client_id would be encoded before reaching
# this helper).
#
# "+" is allowed for plus-addressed emails (ali+work@x.com).
# IMPORTANT: '/' and '\' are NOT in this set, which is the point - we
# reject any component that contains a path separator.
_SAFE_COMPONENT = re.compile(r"^[A-Za-z0-9._@+-]+$")


def _validate_component(component: str, label: str) -> None:
    """Raise HTTPException(400) if `component` is empty, ".", "..", or
    contains characters outside the safe set."""
    if component in _FORBIDDEN_COMPONENTS:
        raise HTTPException(status_code=400, detail=f"Invalid {label}")
    if not _SAFE_COMPONENT.match(component):
        raise HTTPException(status_code=400, detail=f"Invalid {label}")


def safe_upload_path(base_dir: str, *parts: str) -> str:
    """Build a path inside `base_dir` from `parts`, rejecting traversal.

    Validates each part against the safe-component pattern (no slashes,
    no "..", no empties) and then verifies that the resolved real path
    is still inside the resolved base directory. Catches:
      - literal traversal: parts=("foo", "../../etc/passwd")
      - symlink-based escapes: a symlink inside the upload dir pointing
        outside (realpath follows symlinks before comparison)
      - mixed-separator attacks on Windows-style inputs (\\ is rejected
        by the regex)

    Returns the absolute, real path. Caller is responsible for any
    further checks (existence, ownership, MIME).

    Raises HTTPException(400) on any rejection - intended for direct
    use inside FastAPI route handlers.
    """
    if not parts:
        raise HTTPException(status_code=400, detail="Path components required")

    # Label first component "client_id" and remaining as "filename" - this
    # matches the call sites and produces useful error messages without
    # leaking what the server expects.
    for index, part in enumerate(parts):
        label = "client_id" if index == 0 else "filename"
        _validate_component(part, label)

    base_real = os.path.realpath(base_dir)
    target_real = os.path.realpath(os.path.join(base_real, *parts))

    # Must be exactly the base, or somewhere strictly under it.
    if target_real != base_real and not target_real.startswith(base_real + os.sep):
        raise HTTPException(status_code=400, detail="Invalid path")

    return target_real
