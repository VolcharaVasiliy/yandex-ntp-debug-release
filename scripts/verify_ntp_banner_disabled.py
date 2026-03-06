#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

MAX_HIDE_TIME = "9223372036854775807"


def default_yandex_root() -> str:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return str(Path(local_app_data) / "Yandex" / "YandexBrowser")
    return str(Path.home() / "AppData" / "Local" / "Yandex" / "YandexBrowser")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify that NTP promotional banner is disabled."
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
    return parser.parse_args()


def get_nested(payload: dict[str, object], path: tuple[str, ...]) -> object:
    current: object = payload
    for part in path:
        if not isinstance(current, dict):
            return None
        if part not in current:
            return None
        current = current[part]
    return current


def main() -> int:
    args = parse_args()
    yandex_root = Path(args.yandex_root)
    user_data = yandex_root / "User Data"
    preferences = user_data / args.profile / "Preferences"
    local_state = user_data / "Local State"

    required = [preferences, local_state]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        print("[ERROR] Missing required files:")
        for item in missing:
            print(f"  - {item}")
        return 1

    prefs_data = json.loads(preferences.read_text(encoding="utf-8"))
    local_state_data = json.loads(local_state.read_text(encoding="utf-8"))
    if not isinstance(prefs_data, dict) or not isinstance(local_state_data, dict):
        print("[ERROR] Unexpected JSON root type in Preferences/Local State")
        return 1

    failed = False
    print(f"[info] profile: {args.profile}")
    print("[Preferences]")

    checks: list[tuple[str, object, object]] = [
        (
            "ya.ntp.ads_disabled",
            get_nested(prefs_data, ("ya", "ntp", "ads_disabled")),
            True,
        ),
        (
            "ya.webntp_data.bannerOptionEnabled",
            get_nested(prefs_data, ("ya", "webntp_data", "bannerOptionEnabled")),
            False,
        ),
        (
            "ntp_widget_browser_promo.enabled",
            get_nested(prefs_data, ("ntp_widget_browser_promo", "enabled")),
            False,
        ),
        (
            "ntp_widget_disaster_promo.enabled",
            get_nested(prefs_data, ("ntp_widget_disaster_promo", "enabled")),
            False,
        ),
    ]

    for label, actual, expected in checks:
        ok = actual == expected
        failed = failed or (not ok)
        print(
            f"  - {'OK' if ok else 'FAIL'} {label}: actual={actual!r}, expected={expected!r}"
        )

    print("[Local State]")
    hide_time_actual = get_nested(local_state_data, ("ya", "ntp", "banner", "hide_time"))
    hide_time_ok = hide_time_actual == MAX_HIDE_TIME
    failed = failed or (not hide_time_ok)
    print(
        "  - "
        f"{'OK' if hide_time_ok else 'FAIL'} "
        f"ya.ntp.banner.hide_time: actual={hide_time_actual!r}, expected={MAX_HIDE_TIME!r}"
    )

    features = get_nested(
        local_state_data,
        (
            "ya",
            "ondemand_features_service",
            "config",
            "ondemand_features",
            "StaffForceRedesign",
            "features",
        ),
    )
    if isinstance(features, dict):
        feature_checks: list[tuple[str, object, object]] = [
            ("DisableBanner.enabled", get_nested(features, ("DisableBanner", "enabled")), True),
            (
                "NoAppPromoFeature.enabled",
                get_nested(features, ("NoAppPromoFeature", "enabled")),
                True,
            ),
            (
                "NTPW_browser_promo.enabled",
                get_nested(features, ("NTPW_browser_promo", "enabled")),
                False,
            ),
            ("NTPW_emercom.enabled", get_nested(features, ("NTPW_emercom", "enabled")), False),
        ]
        for label, actual, expected in feature_checks:
            ok = actual == expected
            failed = failed or (not ok)
            print(
                f"  - {'OK' if ok else 'FAIL'} feature {label}: "
                f"actual={actual!r}, expected={expected!r}"
            )
    else:
        print("  - WARN StaffForceRedesign.features not found")

    if failed:
        print("[RESULT] FAIL")
        return 2

    print("[RESULT] OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
