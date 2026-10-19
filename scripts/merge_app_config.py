#!/usr/bin/env python3

import argparse
import json
import os
import re
from typing import Any, Dict


_WINDOW_CONFIG_RE = re.compile(
    r"window\.APP_CONFIG\s*=\s*(\{.*\})\s*;?\s*$", re.DOTALL
)


def _parse_window_app_config(path: str) -> Dict[str, Any]:
    if not path or not os.path.exists(path):
        return {}

    content = ""
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read().strip()
    except Exception:
        return {}

    match = _WINDOW_CONFIG_RE.search(content)
    if not match:
        return {}

    try:
        value = json.loads(match.group(1))
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def merge_seed_into_config(seed_path: str, config_path: str) -> Dict[str, Any]:
    seed = _parse_window_app_config(seed_path)
    existing = _parse_window_app_config(config_path)

    merged: Dict[str, Any] = dict(existing)
    for key, value in seed.items():
        merged[key] = value

    os.makedirs(os.path.dirname(config_path) or ".", exist_ok=True)
    with open(config_path, "w", encoding="utf-8") as f:
        f.write("window.APP_CONFIG = " + json.dumps(merged, indent=2) + ";")

    return merged


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Merge config_seed.js into config.js. Only keys present in the seed overwrite the config; "
            "all other existing keys are preserved."
        )
    )
    parser.add_argument("--seed", required=True, help="Path to config_seed.js")
    parser.add_argument("--config", required=True, help="Path to config.js")
    args = parser.parse_args()

    merge_seed_into_config(args.seed, args.config)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
