#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from shared_patchlib import (
    NTP_RU_EXACT_PAYLOAD_REPLACEMENTS,
    SEARCH_REPLACEMENTS,
    WEB_APP_CONFIG_FILES,
    WEB_APP_CONFIG_SUBDIR,
    default_yandex_root,
    find_ntp_bundle_path,
    find_ntp_locale_chunk_paths,
    resolve_app_version,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Restore only new-tab related patch changes from latest backups."
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


def restore_file_from_backup(path: Path, dry_run: bool) -> tuple[bool, str]:
    backup = latest_backup(path)
    if backup is None:
        return False, f"backup missing: {path}"
    if dry_run:
        return True, f"would restore {backup} -> {path}"
    shutil.copy2(backup, path)
    return True, f"restored {backup.name} -> {path.name}"


def restore_replacements_from_backup(
    path: Path,
    replacements: list[tuple[bytes, bytes, str]],
    dry_run: bool,
) -> tuple[bool, list[str]]:
    backup = latest_backup(path)
    if backup is None:
        return False, [f"backup missing: {path}"]

    current = path.read_bytes()
    backup_bytes = backup.read_bytes()
    updated = current
    logs: list[str] = []
    failed: list[str] = []

    for old, new, name in replacements:
        backup_old = backup_bytes.count(old)
        current_old = updated.count(old)
        current_new = updated.count(new)

        if current_new > 0:
            if backup_old == 0:
                failed.append(f"{name}: old pattern not found in backup")
                continue
            updated = updated.replace(new, old)
            logs.append(f"restored {name}")
            continue

        if current_old > 0:
            logs.append(f"already stock {name}")
            continue

        failed.append(f"{name}: neither stock nor patched pattern found")

    if failed:
        logs.extend(failed)
        return False, logs

    if dry_run:
        return True, [f"would update {path.name}: {', '.join(logs)}"]

    if updated != current:
        path.write_bytes(updated)
    return True, [f"{path.name}: {', '.join(logs)}"]


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
    resources_pak = app_root / "resources.pak"
    web_app_component_dir = app_root / WEB_APP_CONFIG_SUBDIR
    web_app_configs = [web_app_component_dir / name for name in WEB_APP_CONFIG_FILES]
    user_data = yandex_root / "User Data"
    preferences = user_data / args.profile / "Preferences"
    local_state = user_data / "Local State"

    try:
        ntp_bundle = find_ntp_bundle_path(app_root)
        ntp_locale_chunks = find_ntp_locale_chunk_paths(app_root)
    except Exception as exc:
        print(f"[ERROR] {exc}")
        return 1

    ntp_dll_replacements = [
        item for item in SEARCH_REPLACEMENTS if item[2] == "ntp_topbar_chatgpt_default_url_cluster"
    ]

    required = [
        browser_dll,
        ru_pak,
        resources_pak,
        *web_app_configs,
        ntp_bundle,
        *ntp_locale_chunks,
    ]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        print("[ERROR] Missing required target files:")
        for item in missing:
            print(f"  - {item}")
        return 1

    print(f"[info] App version: {app_version}")

    ok, dll_logs = restore_replacements_from_backup(
        browser_dll,
        ntp_dll_replacements,
        args.dry_run,
    )
    if not ok:
        print("[ERROR] browser.dll restore failed:")
        for line in dll_logs:
            print(f"  - {line}")
        return 2
    print("[browser.dll]")
    for line in dll_logs:
        print(f"  - {line}")

    ok, ru_logs = restore_replacements_from_backup(
        ru_pak,
        list(NTP_RU_EXACT_PAYLOAD_REPLACEMENTS),
        args.dry_run,
    )
    if not ok:
        print("[ERROR] ru.pak restore failed:")
        for line in ru_logs:
            print(f"  - {line}")
        return 2
    print("[ru.pak]")
    for line in ru_logs:
        print(f"  - {line}")

    whole_restore_targets = [
        resources_pak,
        *web_app_configs,
        ntp_bundle,
        *ntp_locale_chunks,
    ]

    print("[new tab resources]")
    for target in whole_restore_targets:
        ok, message = restore_file_from_backup(target, args.dry_run)
        prefix = "[WARN]" if not ok else "[OK]"
        print(f"  - {prefix} {message}")

    optional_profile_targets = [preferences, local_state]
    print("[profile new tab state]")
    restored_any_profile_target = False
    for target in optional_profile_targets:
        if not target.exists():
            print(f"  - [WARN] target missing: {target}")
            continue
        ok, message = restore_file_from_backup(target, args.dry_run)
        if ok:
            restored_any_profile_target = True
            print(f"  - [OK] {message}")
        else:
            print(f"  - [WARN] {message}")

    if not restored_any_profile_target:
        print("  - [INFO] no profile-level NTP backup was available")

    if args.dry_run:
        print("[RESULT] DRY-RUN finished")
        return 0

    print("[RESULT] OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
