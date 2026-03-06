#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

from shared_patchlib import (
    ASK_ALICE_LABEL,
    ASK_ALICE_LABEL_WITH_ARG,
    ASK_ALICE_LABEL_WITH_ARG_GUILLEMETS,
    ASK_CHATGPT_LABEL,
    ASK_CHATGPT_LABEL_WITH_ARG,
    ASK_CHATGPT_LABEL_WITH_ARG_GUILLEMETS,
    ICON_PACK_FILES,
    LEGACY_PATCHED_LABEL,
    NEW_LABEL,
    OLD_LABEL,
    PREVIOUS_NEW_LABEL,
    SEARCH_REPLACEMENTS,
    default_yandex_root,
    ensure_instaserp,
    make_backup,
    patch_copysearch_icon_pack,
    patch_multi,
    patch_unique,
    resolve_app_version,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Apply only safe context/popup Google + ChatGPT changes."
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


def patch_browser_dll_context_only(path: Path) -> list[str]:
    data = path.read_bytes()
    logs: list[str] = []
    for old, new, key in SEARCH_REPLACEMENTS:
        if key == "ntp_topbar_chatgpt_default_url_cluster":
            continue
        data, message = patch_unique(data, old, new, key)
        logs.append(message)
    path.write_bytes(data)
    return logs


def patch_ru_pak_context_only(path: Path) -> list[str]:
    data = path.read_bytes()
    logs: list[str] = []

    old_count = data.count(OLD_LABEL)
    legacy_count = data.count(LEGACY_PATCHED_LABEL)
    previous_new_count = data.count(PREVIOUS_NEW_LABEL)
    new_count = data.count(NEW_LABEL)

    if old_count == 1 and legacy_count == 0 and previous_new_count == 0 and new_count == 0:
        data = data.replace(OLD_LABEL, NEW_LABEL, 1)
        logs.append("patched (context_menu_label from stock)")
    elif old_count == 0 and legacy_count >= 1 and previous_new_count == 0 and new_count == 0:
        data = data.replace(LEGACY_PATCHED_LABEL, NEW_LABEL, 1)
        logs.append("patched (context_menu_label migrated from legacy padded label)")
    elif old_count == 0 and legacy_count == 0 and previous_new_count >= 1 and new_count == 0:
        data = data.replace(PREVIOUS_NEW_LABEL, NEW_LABEL, 1)
        logs.append("patched (context_menu_label migrated from previous patched label)")
    elif old_count == 0 and legacy_count == 0 and previous_new_count == 0 and new_count >= 1:
        logs.append("already patched (context_menu_label)")
    else:
        raise ValueError(
            "Unexpected pattern count for context_menu_label: "
            f"old={old_count}, legacy={legacy_count}, previous={previous_new_count}, new={new_count}"
        )

    data, ask_with_arg_msg = patch_multi(
        data,
        ASK_ALICE_LABEL_WITH_ARG,
        ASK_CHATGPT_LABEL_WITH_ARG,
        "ask_ai_button_label_with_arg",
    )
    logs.append(ask_with_arg_msg)

    data, ask_with_arg_guillemets_msg = patch_multi(
        data,
        ASK_ALICE_LABEL_WITH_ARG_GUILLEMETS,
        ASK_CHATGPT_LABEL_WITH_ARG_GUILLEMETS,
        "ask_ai_button_label_with_arg_guillemets",
    )
    logs.append(ask_with_arg_guillemets_msg)

    data, ask_msg = patch_multi(
        data,
        ASK_ALICE_LABEL,
        ASK_CHATGPT_LABEL,
        "ask_ai_button_label",
    )
    logs.append(ask_msg)

    path.write_bytes(data)
    return logs


def patch_icon_paks_context_only(app_root: Path) -> list[str]:
    logs: list[str] = []
    for file_name in ICON_PACK_FILES:
        pak_path = app_root / file_name
        logs.append(f"{file_name}: {patch_copysearch_icon_pack(pak_path)}")
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

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    try:
        backups = [
            make_backup(browser_dll, stamp, args.no_backup),
            make_backup(ru_pak, stamp, args.no_backup),
            *(make_backup(path, stamp, args.no_backup) for path in icon_paks),
            make_backup(local_state, stamp, args.no_backup),
        ]

        dll_logs = patch_browser_dll_context_only(browser_dll)
        ru_logs = patch_ru_pak_context_only(ru_pak)
        icon_logs = patch_icon_paks_context_only(app_root)
        state_log = ensure_instaserp(local_state)

        print("[OK] Context-safe patch finished")
        print(f"  App version: {app_version}")
        print(f"  browser.dll: {browser_dll}")
        for line in dll_logs:
            print(f"    - {line}")
        print("  ru.pak:")
        for line in ru_logs:
            print(f"    - {line}")
        print("  icon packs:")
        for line in icon_logs:
            print(f"    - {line}")
        print(f"  Local State: {state_log}")

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
