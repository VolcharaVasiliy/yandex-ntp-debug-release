#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from screenshot_hotkey_patchlib import (
    default_yandex_root,
    install_startup_vbs,
    load_json,
    local_state_path,
    make_backup,
    patch_screenshot_hotkeys,
    patch_screenshot_ui_files,
    save_json,
    start_remap_process,
    stop_remap_processes,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Set Yandex Browser screenshot hotkeys to ScrollLock and start remap."
    )
    parser.add_argument(
        "--yandex-root",
        default=default_yandex_root(),
        help="Path to YandexBrowser root folder.",
    )
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="Do not create a Local State backup before patching.",
    )
    parser.add_argument(
        "--skip-remap",
        action="store_true",
        help="Only patch browser hotkey values and do not install/start remap.",
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
        backup = make_backup(local_state, disabled=args.no_backup)
        payload = load_json(local_state)
        logs = patch_screenshot_hotkeys(payload)
        save_json(local_state, payload)

        print("[OK] Screenshot hotkey patch finished")
        print(f"  Local State: {local_state}")
        for line in logs:
            print(f"    - {line}")
        if backup:
            print(f"  Backup: {backup}")

        ui_results = patch_screenshot_ui_files(yandex_root, no_backup=args.no_backup)
        print("[UI labels]")
        for result in ui_results:
            print(f"  File: {result.path}")
            for line in result.logs:
                print(f"    - {line}")
            if result.backup:
                print(f"    - backup: {result.backup}")

        if not args.skip_remap:
            stopped = stop_remap_processes()
            vbs_path = install_startup_vbs()
            start_remap_process()
            print("[Remap]")
            print(f"  - stopped previous remap processes: {stopped}")
            print(f"  - startup: {vbs_path}")
            print("  - daemon: started")
        return 0
    except Exception as exc:
        print(f"[ERROR] {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
