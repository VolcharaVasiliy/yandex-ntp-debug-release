#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path


def default_yandex_root() -> str:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return str(Path(local_app_data) / "Yandex" / "YandexBrowser")
    return str(Path.home() / "AppData" / "Local" / "Yandex" / "YandexBrowser")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Restore latest NTP banner patch backups (Preferences + Local State)."
    )
    parser.add_argument(
        "--yandex-root",
        default=default_yandex_root(),
        help="Path to YandexBrowser root folder.",
    )
    parser.add_argument(
        "--profile",
        default="Default",
        help="Profile folder inside <root>\\User Data (default: Default).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print actions without restoring files.",
    )
    return parser.parse_args()


def latest_backup(path: Path) -> Path | None:
    pattern = f"{path.name}.bak_patchkit_*"
    backups = list(path.parent.glob(pattern))
    if not backups:
        return None
    backups.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return backups[0]


def main() -> int:
    args = parse_args()
    yandex_root = Path(args.yandex_root)
    user_data = yandex_root / "User Data"

    targets = [
        user_data / args.profile / "Preferences",
        user_data / "Local State",
    ]

    missing_targets = [str(path) for path in targets if not path.exists()]
    if missing_targets:
        print("[ERROR] Missing target files:")
        for item in missing_targets:
            print(f"  - {item}")
        return 1

    restored = 0
    missing_backups = 0

    for target in targets:
        backup = latest_backup(target)
        if not backup:
            missing_backups += 1
            print(f"[WARN] No patchkit backup found for: {target}")
            continue

        if args.dry_run:
            print(f"[DRY-RUN] {backup} -> {target}")
        else:
            shutil.copy2(backup, target)
            restored += 1
            print(f"[RESTORED] {backup} -> {target}")

    if args.dry_run:
        print("[RESULT] DRY-RUN finished")
        return 0

    if restored == 0:
        print("[RESULT] FAIL: nothing restored")
        return 2

    if missing_backups > 0:
        print("[RESULT] PARTIAL: restored with missing backup(s)")
        return 3

    print("[RESULT] OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
