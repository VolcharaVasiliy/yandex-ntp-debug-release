#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

PATCHED_HOTKEY_AREA = "ScrollLock"
PATCHED_HOTKEY_SCREEN = "Alt+ScrollLock"
DEFAULT_HOTKEY_AREA = "PrtScr"
DEFAULT_HOTKEY_SCREEN = "Alt+PrtScr"
SCROLLLOCK_REMAP_ARG = "--scrolllock-remap-daemon"
LEGACY_SCROLLLOCK_SCRIPT_MARKER = "scrolllock_screenshot_remap.py"
STARTUP_VBS_NAME = "scrolllock_screenshot_remap.vbs"
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
DETACHED_PROCESS = getattr(subprocess, "DETACHED_PROCESS", 0)
CREATE_NEW_PROCESS_GROUP = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)

BROWSER_DLL_REPLACEMENTS = (
    (
        b"Ctrl+Shift+PrtScr",
        b"Ctrl+Shift+ScrLck",
        "browser.dll Ctrl+Shift+PrtScr",
    ),
    (
        b"Ctrl+Alt+PrtScr",
        b"Ctrl+Alt+ScrLck",
        "browser.dll Ctrl+Alt+PrtScr",
    ),
    (b"Shift+PrtScr", b"Shift+ScrLck", "browser.dll Shift+PrtScr"),
    (b"Ctrl+PrtScr", b"Ctrl+ScrLck", "browser.dll Ctrl+PrtScr"),
    (b"Alt+PrtScr", b"Alt+ScrLck", "browser.dll Alt+PrtScr"),
    (b"PrtScr", b"ScrLck", "browser.dll PrtScr"),
)
RU_PAK_REPLACEMENTS = (
    (b"Print Screen", b"Scroll Lock ", "ru.pak Print Screen"),
)


@dataclass(frozen=True)
class FilePatchResult:
    path: Path
    backup: Path | None
    logs: tuple[str, ...]


@dataclass(frozen=True)
class FileVerifyResult:
    path: Path
    logs: tuple[str, ...]
    failed: bool


def default_yandex_root() -> str:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return str(Path(local_app_data) / "Yandex" / "YandexBrowser")
    return str(Path.home() / "AppData" / "Local" / "Yandex" / "YandexBrowser")


def local_state_path(yandex_root: Path) -> Path:
    return yandex_root / "User Data" / "Local State"


def resolve_application_dir(yandex_root: Path) -> Path:
    if (yandex_root / "browser.dll").exists():
        return yandex_root

    application_root = yandex_root / "Application"
    if not application_root.exists():
        raise RuntimeError(f"Missing Application directory: {application_root}")

    candidates = [
        item
        for item in application_root.iterdir()
        if item.is_dir() and (item / "browser.dll").exists()
    ]
    if not candidates:
        raise RuntimeError(f"Could not find browser.dll under: {application_root}")

    def version_key(path: Path) -> tuple[int, ...]:
        parts: list[int] = []
        for token in path.name.split("."):
            if token.isdigit():
                parts.append(int(token))
            else:
                parts.append(-1)
        return tuple(parts)

    return max(candidates, key=version_key)


def browser_dll_path(yandex_root: Path) -> Path:
    return resolve_application_dir(yandex_root) / "browser.dll"


def ru_pak_path(yandex_root: Path) -> Path:
    return resolve_application_dir(yandex_root) / "Locales" / "ru.pak"


def startup_vbs_path() -> Path:
    app_data = os.environ.get("APPDATA")
    if not app_data:
        raise RuntimeError("APPDATA is not set.")
    return (
        Path(app_data)
        / "Microsoft"
        / "Windows"
        / "Start Menu"
        / "Programs"
        / "Startup"
        / STARTUP_VBS_NAME
    )


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON root is not an object: {path}")
    return payload


def save_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )


def make_backup(path: Path, *, disabled: bool = False) -> Path | None:
    if disabled:
        return None
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = path.with_name(f"{path.name}.bak_patchkit_screenshot_hotkey_{stamp}")
    index = 1
    while backup.exists():
        backup = path.with_name(
            f"{path.name}.bak_patchkit_screenshot_hotkey_{stamp}_{index}"
        )
        index += 1
    shutil.copy2(path, backup)
    return backup


def latest_backup(path: Path) -> Path | None:
    backups = sorted(
        path.parent.glob(f"{path.name}.bak_patchkit_screenshot_hotkey_*"),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )
    return backups[0] if backups else None


def ensure_object(payload: dict[str, Any], key: str) -> dict[str, Any]:
    value = payload.get(key)
    if not isinstance(value, dict):
        value = {}
        payload[key] = value
    return value


def ensure_screenshoter_config(payload: dict[str, Any]) -> dict[str, Any]:
    return ensure_object(payload, "screenshoter")


def ensure_ya_screenshoter_config(payload: dict[str, Any]) -> dict[str, Any]:
    ya = ensure_object(payload, "ya")
    return ensure_object(ya, "screenshoter")


def _set_value(mapping: dict[str, Any], key: str, value: Any, label: str) -> str:
    before = mapping.get(key)
    if before == value:
        return f"already patched ({label})"
    mapping[key] = value
    return f"patched ({label}: {before!r} -> {value!r})"


def _patch_hotkey_mapping(mapping: dict[str, Any], prefix: str, *, patched: bool) -> list[str]:
    target_area = PATCHED_HOTKEY_AREA if patched else DEFAULT_HOTKEY_AREA
    target_screen = PATCHED_HOTKEY_SCREEN if patched else DEFAULT_HOTKEY_SCREEN
    return [
        _set_value(mapping, "enabled", True, f"{prefix}.enabled"),
        _set_value(
            mapping,
            "alternative_hotkeys",
            True,
            f"{prefix}.alternative_hotkeys",
        ),
        _set_value(mapping, "hotkey_area", target_area, f"{prefix}.hotkey_area"),
        _set_value(mapping, "hotkey_screen", target_screen, f"{prefix}.hotkey_screen"),
    ]


def patch_screenshot_hotkeys(payload: dict[str, Any]) -> list[str]:
    logs: list[str] = []
    logs.extend(
        _patch_hotkey_mapping(
            ensure_screenshoter_config(payload),
            "screenshoter",
            patched=True,
        )
    )
    logs.extend(
        _patch_hotkey_mapping(
            ensure_ya_screenshoter_config(payload),
            "ya.screenshoter",
            patched=True,
        )
    )
    return logs


def restore_default_screenshot_hotkeys(payload: dict[str, Any]) -> list[str]:
    logs: list[str] = []
    logs.extend(
        _patch_hotkey_mapping(
            ensure_screenshoter_config(payload),
            "screenshoter",
            patched=False,
        )
    )
    logs.extend(
        _patch_hotkey_mapping(
            ensure_ya_screenshoter_config(payload),
            "ya.screenshoter",
            patched=False,
        )
    )
    return logs


def launcher_command_parts() -> list[str]:
    if getattr(sys, "frozen", False):
        return [str(Path(sys.executable).resolve()), SCROLLLOCK_REMAP_ARG]

    launcher_script = Path(__file__).resolve().parent.parent / "patchkit_launcher.py"
    python_executable = Path(sys.executable).resolve()
    pythonw_executable = python_executable.with_name("pythonw.exe")
    runner = pythonw_executable if pythonw_executable.exists() else python_executable
    return [str(runner), str(launcher_script), SCROLLLOCK_REMAP_ARG]


def launcher_workdir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def format_command(parts: list[str]) -> str:
    return subprocess.list2cmdline(parts)


def _run_powershell(script: str, *, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        [
            str(
                Path(os.environ.get("SystemRoot", r"C:\Windows"))
                / "System32"
                / "WindowsPowerShell"
                / "v1.0"
                / "powershell.exe"
            ),
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            script,
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=CREATE_NO_WINDOW,
    )
    if check and result.returncode != 0:
        stderr = (result.stderr or "").strip()
        stdout = (result.stdout or "").strip()
        raise RuntimeError(stderr or stdout or "PowerShell command failed")
    return result


def _binary_patch_file(
    path: Path,
    replacements: tuple[tuple[bytes, bytes, str], ...],
    *,
    no_backup: bool = False,
) -> FilePatchResult:
    if not path.exists():
        raise RuntimeError(f"Missing file: {path}")

    original = path.read_bytes()
    patched = original
    logs: list[str] = []

    for old, new, label in replacements:
        if len(old) != len(new):
            raise RuntimeError(
                f"Replacement length mismatch for {label}: {len(old)} != {len(new)}"
            )
        old_count = patched.count(old)
        if old_count:
            patched = patched.replace(old, new)
            logs.append(f"patched ({label}: replacements={old_count})")
            continue

        new_count = patched.count(new)
        if new_count:
            logs.append(f"already patched ({label}: replacements={new_count})")
            continue

        raise RuntimeError(f"Could not find marker for {label} in {path}")

    backup = None
    if patched != original:
        backup = make_backup(path, disabled=no_backup)
        path.write_bytes(patched)

    return FilePatchResult(path=path, backup=backup, logs=tuple(logs))


def _binary_restore_file(
    path: Path,
    replacements: tuple[tuple[bytes, bytes, str], ...],
) -> FilePatchResult:
    if not path.exists():
        raise RuntimeError(f"Missing file: {path}")

    backup = latest_backup(path)
    if backup:
        shutil.copy2(backup, path)
        return FilePatchResult(
            path=path,
            backup=backup,
            logs=(f"restored from backup ({backup.name})",),
        )

    reverse_replacements = tuple((new, old, label) for old, new, label in replacements)
    return _binary_patch_file(path, reverse_replacements, no_backup=True)


def _binary_verify_file(
    path: Path,
    replacements: tuple[tuple[bytes, bytes, str], ...],
) -> FileVerifyResult:
    if not path.exists():
        return FileVerifyResult(
            path=path,
            logs=(f"FAIL missing file: {path}",),
            failed=True,
        )

    payload = path.read_bytes()
    logs: list[str] = []
    failed = False
    for old, new, label in replacements:
        old_count = payload.count(old)
        new_count = payload.count(new)
        ok = old_count == 0 and new_count > 0
        logs.append(
            f"{'OK' if ok else 'FAIL'} {label}: old={old_count}, new={new_count}"
        )
        failed = failed or (not ok)
    return FileVerifyResult(path=path, logs=tuple(logs), failed=failed)


def patch_screenshot_ui_files(
    yandex_root: Path,
    *,
    no_backup: bool = False,
) -> list[FilePatchResult]:
    return [
        _binary_patch_file(browser_dll_path(yandex_root), BROWSER_DLL_REPLACEMENTS, no_backup=no_backup),
        _binary_patch_file(ru_pak_path(yandex_root), RU_PAK_REPLACEMENTS, no_backup=no_backup),
    ]


def restore_screenshot_ui_files(yandex_root: Path) -> list[FilePatchResult]:
    return [
        _binary_restore_file(browser_dll_path(yandex_root), BROWSER_DLL_REPLACEMENTS),
        _binary_restore_file(ru_pak_path(yandex_root), RU_PAK_REPLACEMENTS),
    ]


def verify_screenshot_ui_files(yandex_root: Path) -> list[FileVerifyResult]:
    return [
        _binary_verify_file(browser_dll_path(yandex_root), BROWSER_DLL_REPLACEMENTS),
        _binary_verify_file(ru_pak_path(yandex_root), RU_PAK_REPLACEMENTS),
    ]


def get_remap_processes() -> list[dict[str, Any]]:
    script = rf"""
$procs = Get-CimInstance Win32_Process | Where-Object {{
    $_.CommandLine -and (
        $_.Name -eq 'python.exe' -or
        $_.Name -eq 'pythonw.exe' -or
        $_.Name -eq 'PatchKit Launcher.exe'
    ) -and (
        $_.CommandLine -like '*{SCROLLLOCK_REMAP_ARG}*' -or
        $_.CommandLine -like '*{LEGACY_SCROLLLOCK_SCRIPT_MARKER}*'
    )
}} | Sort-Object ProcessId | Select-Object `
    @{{Name='Id';Expression={{$_.ProcessId}}}},
    @{{Name='Name';Expression={{$_.Name}}}},
    @{{Name='CommandLine';Expression={{$_.CommandLine}}}}
if ($procs) {{
    $procs | ConvertTo-Json -Compress
}} else {{
    '[]'
}}
"""
    result = _run_powershell(script, check=True)
    payload = (result.stdout or "").strip()
    if not payload:
        return []
    parsed = json.loads(payload)
    if isinstance(parsed, dict):
        return [parsed]
    return parsed


def stop_remap_processes() -> int:
    processes = get_remap_processes()
    if not processes:
        return 0
    ids = ",".join(str(proc["Id"]) for proc in processes)
    _run_powershell(
        f"$ids=@({ids}); Get-Process -Id $ids -ErrorAction SilentlyContinue | "
        "Stop-Process -Force -ErrorAction SilentlyContinue",
        check=False,
    )
    time.sleep(0.8)
    return len(processes)


def install_startup_vbs() -> Path:
    command_line = format_command(launcher_command_parts())
    vbs_path = startup_vbs_path()
    vbs_path.parent.mkdir(parents=True, exist_ok=True)
    escaped = command_line.replace('"', '""')
    lines = [
        'Set WshShell = CreateObject("WScript.Shell")',
        f'WshShell.Run "{escaped}", 0',
        "Set WshShell = Nothing",
    ]
    vbs_path.write_text("\r\n".join(lines) + "\r\n", encoding="ascii")
    return vbs_path


def remove_startup_vbs() -> bool:
    vbs_path = startup_vbs_path()
    if not vbs_path.exists():
        return False
    vbs_path.unlink()
    return True


def startup_vbs_contains_remap() -> bool:
    vbs_path = startup_vbs_path()
    if not vbs_path.exists():
        return False
    text = vbs_path.read_text(encoding="ascii", errors="replace")
    return SCROLLLOCK_REMAP_ARG in text


def start_remap_process() -> None:
    command = launcher_command_parts()
    subprocess.Popen(
        command,
        cwd=str(launcher_workdir()),
        creationflags=CREATE_NO_WINDOW | DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP,
        close_fds=True,
    )
    time.sleep(1.0)
    if not get_remap_processes():
        raise RuntimeError("Scroll Lock remap daemon did not start.")
