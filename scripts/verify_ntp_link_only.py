#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from shared_patchlib import (
    NTP_ROUTE_REPLACEMENTS,
    SEARCH_REPLACEMENTS,
    default_yandex_root,
    find_ntp_bundle_path,
    resolve_app_version,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify only the new-tab Alice button URL patch."
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
    return parser.parse_args()


def verify_browser_dll_link_only(path: Path) -> tuple[bool, list[str]]:
    data = path.read_bytes()
    logs: list[str] = []
    failed = False
    for old, new, key in SEARCH_REPLACEMENTS:
        if key != "ntp_topbar_chatgpt_default_url_cluster":
            continue
        old_count = data.count(old)
        new_count = data.count(new)
        ok = old_count == 0 and new_count >= 1
        failed = failed or (not ok)
        logs.append(
            f"{'OK' if ok else 'FAIL'} {key}: old={old_count}, new={new_count}"
        )
    return (not failed), logs


def verify_ntp_bundle_link_only(path: Path) -> tuple[bool, list[str]]:
    data = path.read_bytes()
    logs: list[str] = []
    failed = False
    for old, new, key in NTP_ROUTE_REPLACEMENTS:
        old_count = data.count(old)
        new_count = data.count(new)
        ok = old_count == 0 and new_count >= 1
        failed = failed or (not ok)
        logs.append(
            f"{'OK' if ok else 'FAIL'} {key}: old={old_count}, new={new_count}"
        )
    return (not failed), logs


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

    missing = [str(path) for path in (browser_dll, ntp_bundle) if not path.exists()]
    if missing:
        print("[ERROR] Missing required files:")
        for item in missing:
            print(f"  - {item}")
        return 1

    print(f"[info] App version: {app_version}")
    dll_ok, dll_logs = verify_browser_dll_link_only(browser_dll)
    print("[browser.dll]")
    for line in dll_logs:
        print(f"  - {line}")

    ntp_ok, ntp_logs = verify_ntp_bundle_link_only(ntp_bundle)
    print("[NTP bundle]")
    for line in ntp_logs:
        print(f"  - {line}")

    if not (dll_ok and ntp_ok):
        print("[RESULT] FAIL")
        return 2

    print("[RESULT] OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
