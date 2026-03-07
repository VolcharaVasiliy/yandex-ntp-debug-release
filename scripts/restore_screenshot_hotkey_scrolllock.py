#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from screenshot_hotkey_patchlib import (
    default_yandex_root,
    latest_backup,
    load_json,
    local_state_path,
    remove_startup_vbs,
    restore_default_screenshot_hotkeys,
    restore_screenshot_ui_files,
    save_json,
    stop_remap_processes,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Restore screenshot hotkeys and stop ScrollLock remap."
    )
    parser.add_argument(
        "--yandex-root",
        default=default_yandex_root(),
        help="Path to YandexBrowser root folder.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    yandex_root = Path(args.yandex_root)
    local_state = local_state_path(yandex_root)

    if not local_state.exists():
        print(f"[ERROR] Missing Local State: {local_state}")
        return 1

    try:
        restored_from_backup = False
        backup = latest_backup(local_state)
        if backup:
            shutil.copy2(backup, local_state)
            restored_from_backup = True
            print(f"[RESTORED] {backup} -> {local_state}")
        else:
            payload = load_json(local_state)
            logs = restore_default_screenshot_hotkeys(payload)
            save_json(local_state, payload)
            print("[RESTORED] No screenshot backup found; default hotkeys were written instead.")
            print(f"  Local State: {local_state}")
            for line in logs:
                print(f"    - {line}")

        print("[UI restore]")
        for result in restore_screenshot_ui_files(yandex_root):
            print(f"  File: {result.path}")
            for line in result.logs:
                print(f"    - {line}")
            if result.backup:
                print(f"    - backup: {result.backup}")

        stopped = stop_remap_processes()
        startup_removed = remove_startup_vbs()

        print("[Remap cleanup]")
        print(f"  - stopped remap processes: {stopped}")
        print(f"  - removed startup VBS: {startup_removed}")

        if restored_from_backup:
            print("[RESULT] OK restored from backup")
        else:
            print("[RESULT] OK restored defaults")
        return 0
    except Exception as exc:
        print(f"[ERROR] {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
