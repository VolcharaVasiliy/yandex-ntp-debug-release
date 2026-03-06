#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

MAX_HIDE_TIME = "9223372036854775807"


def default_yandex_root() -> str:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return str(Path(local_app_data) / "Yandex" / "YandexBrowser")
    return str(Path.home() / "AppData" / "Local" / "Yandex" / "YandexBrowser")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Disable promotional banner on Yandex Browser new tab page."
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
        "--no-backup",
        action="store_true",
        help="Do not create backup copies before patching.",
    )
    return parser.parse_args()


def make_backup(path: Path, stamp: str, disabled: bool) -> Path | None:
    if disabled:
        return None
    backup = path.with_name(f"{path.name}.bak_patchkit_{stamp}")
    idx = 1
    while backup.exists():
        backup = path.with_name(f"{path.name}.bak_patchkit_{stamp}_{idx}")
        idx += 1
    shutil.copy2(path, backup)
    return backup


def set_nested_value(
    payload: dict[str, object],
    path: tuple[str, ...],
    value: object,
    label: str,
) -> str:
    current: dict[str, object] = payload
    for part in path[:-1]:
        next_value = current.get(part)
        if not isinstance(next_value, dict):
            next_value = {}
            current[part] = next_value
        current = next_value

    leaf = path[-1]
    before = current.get(leaf)
    if before == value:
        return f"already patched ({label})"

    current[leaf] = value
    return f"patched ({label}: {before!r} -> {value!r})"


def set_feature_flag(features: dict[str, object], name: str, enabled: bool) -> str:
    feature_value = features.get(name)
    if not isinstance(feature_value, dict):
        feature_value = {}
        features[name] = feature_value

    before = feature_value.get("enabled")
    if before == enabled:
        return f"already patched (feature {name}.enabled)"

    feature_value["enabled"] = enabled
    return f"patched (feature {name}.enabled: {before!r} -> {enabled!r})"


def patch_preferences(path: Path) -> list[str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Preferences root is not a JSON object")

    logs = [
        set_nested_value(
            payload,
            ("ya", "ntp", "ads_disabled"),
            True,
            "ya.ntp.ads_disabled",
        ),
        set_nested_value(
            payload,
            ("ya", "webntp_data", "bannerOptionEnabled"),
            False,
            "ya.webntp_data.bannerOptionEnabled",
        ),
        set_nested_value(
            payload,
            ("ntp_widget_browser_promo", "enabled"),
            False,
            "ntp_widget_browser_promo.enabled",
        ),
        set_nested_value(
            payload,
            ("ntp_widget_disaster_promo", "enabled"),
            False,
            "ntp_widget_disaster_promo.enabled",
        ),
    ]

    path.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    return logs


def patch_local_state(path: Path) -> list[str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Local State root is not a JSON object")

    logs = [
        set_nested_value(
            payload,
            ("ya", "ntp", "banner", "hide_time"),
            MAX_HIDE_TIME,
            "ya.ntp.banner.hide_time",
        )
    ]

    features = (
        payload.get("ya", {})
        .get("ondemand_features_service", {})
        .get("config", {})
        .get("ondemand_features", {})
        .get("StaffForceRedesign", {})
        .get("features")
    )
    if isinstance(features, dict):
        logs.append(set_feature_flag(features, "DisableBanner", True))
        logs.append(set_feature_flag(features, "NoAppPromoFeature", True))
        logs.append(set_feature_flag(features, "NTPW_browser_promo", False))
        logs.append(set_feature_flag(features, "NTPW_emercom", False))
    else:
        logs.append("skip (StaffForceRedesign.features not found in Local State)")

    path.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    return logs


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

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    try:
        pref_backup = make_backup(preferences, stamp, args.no_backup)
        state_backup = make_backup(local_state, stamp, args.no_backup)

        pref_logs = patch_preferences(preferences)
        state_logs = patch_local_state(local_state)

        print("[OK] NTP banner patch finished")
        print(f"  profile: {args.profile}")
        print(f"  Preferences: {preferences}")
        for line in pref_logs:
            print(f"    - {line}")
        print(f"  Local State: {local_state}")
        for line in state_logs:
            print(f"    - {line}")

        if not args.no_backup:
            print("[Backups]")
            if pref_backup:
                print(f"  - {pref_backup}")
            if state_backup:
                print(f"  - {state_backup}")

        return 0
    except Exception as exc:
        print(f"[ERROR] {exc}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
