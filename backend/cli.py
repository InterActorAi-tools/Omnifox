"""
Operator CLI for one-shot administrative tasks.

Use cases:
- `python -m cli init` - seed roles + permissions on a fresh database.
  Bootstrap runs on every FastAPI startup, so this is rarely needed except
  for offline DB inspection.
- `python -m cli create-admin` - interactive admin creation when the
  FIRST_ADMIN_* env-var auto-seed path was not used.
- `python -m cli rotate-key` - re-encrypt all data with the newest key.

All commands are idempotent and safe to re-run.
"""
from __future__ import annotations

import argparse
import getpass
import logging
import sys

from sqlalchemy.orm import Session

from bootstrap import (
    WeakPasswordError,
    ensure_first_admin,
    ensure_permissions,
    ensure_roles,
    validate_admin_email,
    validate_admin_password,
)
from database import SessionLocal, bootstrap_lock, run_migrations
from models import Role
from utils.dependencies import find_user_by_email


def _configure_logging() -> None:
    logging.basicConfig(
        format="%(levelname)s %(name)s: %(message)s",
        level=logging.INFO,
    )


def _cmd_init(_args: argparse.Namespace) -> int:
    with bootstrap_lock():
        run_migrations()
        db: Session = SessionLocal()
        try:
            ensure_permissions(db)
            ensure_roles(db)
        finally:
            db.close()
    print("Init complete: schema, permissions, and roles are up to date.")
    return 0


def _prompt_for_password() -> str:
    """Prompt twice via getpass and ensure the two entries match."""
    while True:
        first = getpass.getpass("Admin password: ")
        try:
            validate_admin_password(first)
        except WeakPasswordError as exc:
            print(f"Rejected: {exc}", file=sys.stderr)
            continue
        second = getpass.getpass("Confirm password: ")
        if first != second:
            print("Passwords do not match. Try again.", file=sys.stderr)
            continue
        return first


def _cmd_create_admin(args: argparse.Namespace) -> int:
    email = args.email or input("Admin email: ").strip()
    try:
        validate_admin_email(email)
    except ValueError as exc:
        print(f"Rejected: {exc}", file=sys.stderr)
        return 2

    password = _prompt_for_password()
    name = args.name or input("Display name [Super Admin]: ").strip() or "Super Admin"

    db: Session = SessionLocal()
    try:
        ensure_permissions(db)
        ensure_roles(db)
        created = ensure_first_admin(db, email=email, password=password, name=name)
    finally:
        db.close()

    if created:
        print(f"Admin {email} created.")
        return 0
    print(
        f"Did not create {email}: the users table already has users. "
        "Use `python -m cli promote-admin {email}` to grant admin to an "
        "existing user, or add additional accounts from the admin UI.",
        file=sys.stderr,
    )
    return 1


def _cmd_promote_admin(args: argparse.Namespace) -> int:
    try:
        validate_admin_email(args.email)
    except ValueError as exc:
        print(f"Rejected: {exc}", file=sys.stderr)
        return 2

    db: Session = SessionLocal()
    try:
        user = find_user_by_email(db, args.email)
        if user is None:
            print(f"User {args.email} not found.", file=sys.stderr)
            return 1
        admin_role = db.query(Role).filter(Role.name == "admin").first()
        if admin_role is None:
            print(
                "Admin role not found. Run `python -m cli init` first.",
                file=sys.stderr,
            )
            return 1
        if admin_role in user.roles:
            print(f"{args.email} is already an admin.")
            return 0
        user.roles.append(admin_role)
        db.commit()
        print(f"{args.email} is now an admin.")
        return 0
    finally:
        db.close()


# Every encrypted column: table -> (primary key, columns).
ENCRYPTED_COLUMNS = {
    "tasks": ("task_id", ["message", "metadata_json", "result_data"]),
    "url_cache": ("url_hash", ["url", "sentiment_data"]),
    "activity_logs": ("id", ["ip_address", "user_agent", "extra_data"]),
    "refresh_tokens": ("id", ["device_name", "ip_address", "user_agent"]),
    "users": ("id", ["two_factor_secret"]),
    "chat_messages": ("id", ["content"]),
}


def _cmd_rotate_key(_args: argparse.Namespace) -> int:
    """Re-encrypt all data with the first key in DATA_ENCRYPTION_KEY, so older
    keys can be removed afterwards. Best run with the app stopped; safe to re-run."""
    import os

    from sqlalchemy import text

    from config import UPLOAD_FOLDER
    from database import engine
    from utils.crypto import is_encrypted, rotate

    rows = 0
    for table, (pk, columns) in ENCRYPTED_COLUMNS.items():
        last = None
        while True:
            # One short transaction per batch; each row is only updated if it
            # still holds the value we read (compare-and-set), so a write by
            # the running app is never overwritten. Re-run to pick up skips.
            with engine.begin() as conn:
                where = f"WHERE {pk} > :last " if last is not None else ""
                batch = conn.execute(text(
                    f"SELECT {pk}, {', '.join(columns)} FROM {table} {where}ORDER BY {pk} LIMIT 500"),
                    {"last": last}).fetchall()
                if not batch:
                    break
                for row in batch:
                    old = {c: v for c, v in zip(columns, row[1:]) if v}
                    if not old:
                        continue
                    new = {f"new_{c}": rotate(v.encode()).decode() for c, v in old.items()}
                    sets = ", ".join(f"{c} = :new_{c}" for c in old)
                    same = " AND ".join(f"{c} = :old_{c}" for c in old)
                    result = conn.execute(text(f"UPDATE {table} SET {sets} WHERE {pk} = :pk AND {same}"),
                                          {**new, **{f"old_{c}": v for c, v in old.items()}, "pk": row[0]})
                    rows += result.rowcount
                last = batch[-1][0]

    files = 0
    for root, _dirs, names in os.walk(UPLOAD_FOLDER):
        for name in names:
            path = os.path.join(root, name)
            if name.endswith(".tmp"):
                continue
            try:
                modified = os.path.getmtime(path)
                with open(path, "rb") as f:
                    data = f.read()
                if not is_encrypted(data):
                    continue
                tmp = path + ".rotate.tmp"  # every .tmp is ignored by export and scans
                with open(tmp, "wb") as f:
                    f.write(rotate(data))
                if os.path.getmtime(path) != modified:  # rewritten meanwhile: leave it for a re-run
                    os.remove(tmp)
                    continue
                os.replace(tmp, path)
                os.utime(path, (modified, modified))  # retention counts from creation
                files += 1
            except FileNotFoundError:
                pass
    print(f"Re-encrypted {rows} row(s) and {files} file(s) with the newest key. Older keys can now be removed.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cli",
        description="Omnifox operator CLI.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser(
        "init",
        help="Create tables and seed baseline roles + permissions (idempotent).",
    )
    init.set_defaults(func=_cmd_init)

    admin = sub.add_parser(
        "create-admin",
        help="Interactively create the first admin user.",
    )
    admin.add_argument("--email", help="Admin email (prompted if omitted).")
    admin.add_argument("--name", help="Display name (prompted if omitted).")
    admin.set_defaults(func=_cmd_create_admin)

    promote = sub.add_parser(
        "promote-admin",
        help="Grant admin role to an existing user.",
    )
    promote.add_argument("email", help="Email of the existing user.")
    promote.set_defaults(func=_cmd_promote_admin)

    rotate = sub.add_parser(
        "rotate-key",
        help="Re-encrypt all data with the first DATA_ENCRYPTION_KEY (run before removing an old key).",
    )
    rotate.set_defaults(func=_cmd_rotate_key)

    return parser


def main(argv: list[str] | None = None) -> int:
    _configure_logging()
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
