#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

from shared_patchlib import (
    NTP_ROUTE_REPLACEMENTS,
    SEARCH_REPLACEMENTS,
    default_yandex_root,
    find_ntp_bundle_path,
    make_backup,
    patch_unique,
    resolve_app_version,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Patch only the new-tab Alice button URL to ChatGPT."
    )
    parser.add_argument(
        "--yandex-root",
        default=default_yandex_root(),
        help="Path to YandexBrowser root folder.",
    )
    parser.add_argument(
        "--app-version",
        default=None,
        help=(
            "Application version folder inside <root>\\Application. "
            "If omitted, latest numeric version folder is auto-detected."
        ),
    )
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="Do not create backup copies before patching.",
    )
    return parser.parse_args()


def patch_browser_dll_link_only(path: Path) -> list[str]:
    data = path.read_bytes()
    logs: list[str] = []
    for old, new, key in SEARCH_REPLACEMENTS:
        if key != "ntp_topbar_chatgpt_default_url_cluster":
            continue
        data, message = patch_unique(data, old, new, key)
        logs.append(message)
    path.write_bytes(data)
    return logs


def patch_ntp_bundle_link_only(path: Path) -> list[str]:
    data = path.read_bytes()
    logs: list[str] = []
    for old, new, key in NTP_ROUTE_REPLACEMENTS:
        data, message = patch_unique(data, old, new, key)
        logs.append(message)
    path.write_bytes(data)
    return logs


def main() -> int:
    args = parse_args()
    yandex_root = Path(args.yandex_root)
    application_root = yandex_root / "Application"

    try:
        app_version = resolve_app_version(application_root, args.app_version)
    except Exception as exc:
        print(f"[ERROR] {exc}")
        return 1

    app_root = application_root / app_version
    browser_dll = app_root / "browser.dll"

    try:
        ntp_bundle = find_ntp_bundle_path(app_root)
    except Exception as exc:
        print(f"[ERROR] {exc}")
        return 1

    required = [browser_dll, ntp_bundle]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        print("[ERROR] Missing required files:")
        for item in missing:
            print(f"  - {item}")
        return 1

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    try:
        backups = [
            make_backup(browser_dll, stamp, args.no_backup),
            make_backup(ntp_bundle, stamp, args.no_backup),
        ]

        dll_logs = patch_browser_dll_link_only(browser_dll)
        ntp_logs = patch_ntp_bundle_link_only(ntp_bundle)

        print("[OK] Link-only NTP patch finished")
        print(f"  App version: {app_version}")
        print(f"  browser.dll: {browser_dll}")
        for line in dll_logs:
            print(f"    - {line}")
        print(f"  NTP bundle: {ntp_bundle}")
        for line in ntp_logs:
            print(f"    - {line}")

        if not args.no_backup:
            print("[Backups]")
            for backup in backups:
                if backup:
                    print(f"  - {backup}")

        return 0
    except Exception as exc:
        print(f"[ERROR] {exc}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
