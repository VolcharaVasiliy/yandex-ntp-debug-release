#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from shared_patchlib import (
    ASK_ALICE_LABEL,
    ASK_ALICE_LABEL_WITH_ARG,
    ASK_ALICE_LABEL_WITH_ARG_GUILLEMETS,
    ASK_CHATGPT_LABEL,
    ASK_CHATGPT_LABEL_WITH_ARG,
    ASK_CHATGPT_LABEL_WITH_ARG_GUILLEMETS,
    CONTEXT_JOINT_PATCHED,
    CONTEXT_JOINT_PATCHED_LABEL_ONLY,
    CONTEXT_JOINT_STOCK,
    ICON_PACK_FILES,
    INSTASERP_FLAG,
    LEGACY_PATCHED_LABEL,
    NEW_LABEL,
    OLD_LABEL,
    PREVIOUS_NEW_LABEL,
    SEARCH_REPLACEMENTS,
    default_yandex_root,
    resolve_app_version,
)
import json
from shared_icon_verify import verify_copysearch_icon_pack


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify only safe context/popup Google + ChatGPT changes."
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


def verify_browser_dll_context_only(path: Path) -> tuple[bool, list[str]]:
    data = path.read_bytes()
    logs: list[str] = []
    failed = False
    for old, new, key in SEARCH_REPLACEMENTS:
        if key == "ntp_topbar_chatgpt_default_url_cluster":
            continue
        old_count = data.count(old)
        new_count = data.count(new)
        ok = old_count == 0 and new_count >= 1
        failed = failed or (not ok)
        logs.append(f"{'OK' if ok else 'FAIL'} {key}: old={old_count}, new={new_count}")
    return (not failed), logs


def verify_ru_pak_context_only(path: Path) -> tuple[bool, list[str]]:
    data = path.read_bytes()
    joint_patched = (
        data.count(CONTEXT_JOINT_PATCHED_LABEL_ONLY) + data.count(CONTEXT_JOINT_PATCHED)
    )
    checks = [
        ("context_menu_label",
         data.count(CONTEXT_JOINT_STOCK) == 0 and data.count(LEGACY_PATCHED_LABEL) == 0 and data.count(PREVIOUS_NEW_LABEL) == 0 and data.count(NEW_LABEL) >= 1 and joint_patched >= 1,
         f"old={data.count(OLD_LABEL)}, legacy={data.count(LEGACY_PATCHED_LABEL)}, previous={data.count(PREVIOUS_NEW_LABEL)}, new={data.count(NEW_LABEL)}, joint_stock={data.count(CONTEXT_JOINT_STOCK)}, joint_patched={joint_patched}"),
        ("ask_ai_button_label", data.count(ASK_ALICE_LABEL) == 0 and data.count(ASK_CHATGPT_LABEL) >= 1,
         f"old={data.count(ASK_ALICE_LABEL)}, new={data.count(ASK_CHATGPT_LABEL)}"),
        ("ask_ai_button_label_with_arg", data.count(ASK_ALICE_LABEL_WITH_ARG) == 0 and data.count(ASK_CHATGPT_LABEL_WITH_ARG) >= 1,
         f"old={data.count(ASK_ALICE_LABEL_WITH_ARG)}, new={data.count(ASK_CHATGPT_LABEL_WITH_ARG)}"),
        ("ask_ai_button_label_with_arg_guillemets", data.count(ASK_ALICE_LABEL_WITH_ARG_GUILLEMETS) == 0 and data.count(ASK_CHATGPT_LABEL_WITH_ARG_GUILLEMETS) >= 1,
         f"old={data.count(ASK_ALICE_LABEL_WITH_ARG_GUILLEMETS)}, new={data.count(ASK_CHATGPT_LABEL_WITH_ARG_GUILLEMETS)}"),
    ]
    logs: list[str] = []
    failed = False
    for name, ok, detail in checks:
        failed = failed or (not ok)
        logs.append(f"{'OK' if ok else 'FAIL'} {name}: {detail}")
    return (not failed), logs


def verify_instaserp(local_state_path: Path) -> tuple[bool, str]:
    payload = json.loads(local_state_path.read_text(encoding="utf-8"))
    enabled = payload.get("browser", {}).get("enabled_labs_experiments")
    ok = isinstance(enabled, list) and INSTASERP_FLAG in enabled
    return ok, f"{'OK' if ok else 'FAIL'} instaserp_flag_present: {ok}"


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
    ru_pak = app_root / "Locales" / "ru.pak"
    local_state = yandex_root / "User Data" / "Local State"
    icon_paks = [app_root / name for name in ICON_PACK_FILES]

    required = [browser_dll, ru_pak, local_state, *icon_paks]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        print("[ERROR] Missing required files:")
        for item in missing:
            print(f"  - {item}")
        return 1

    print(f"[info] App version: {app_version}")

    dll_ok, dll_logs = verify_browser_dll_context_only(browser_dll)
    print("[browser.dll]")
    for line in dll_logs:
        print(f"  - {line}")

    ru_ok, ru_logs = verify_ru_pak_context_only(ru_pak)
    print("[ru.pak]")
    for line in ru_logs:
        print(f"  - {line}")

    icon_failed = False
    print("[icon packs]")
    for icon_path in icon_paks:
        ok, message = verify_copysearch_icon_pack(icon_path)
        icon_failed = icon_failed or (not ok)
        print(f"  - {'OK' if ok else 'FAIL'} {message}")

    state_ok, state_message = verify_instaserp(local_state)
    print("[Local State]")
    print(f"  - {state_message}")

    if not (dll_ok and ru_ok and not icon_failed and state_ok):
        print("[RESULT] FAIL")
        return 2

    print("[RESULT] OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
