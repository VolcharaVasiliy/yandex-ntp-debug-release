#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ctypes
import time
from ctypes import wintypes
from pathlib import Path

from screenshot_hotkey_patchlib import (
    PATCHED_HOTKEY_AREA,
    PATCHED_HOTKEY_SCREEN,
    default_yandex_root,
    get_remap_processes,
    load_json,
    local_state_path,
    startup_vbs_contains_remap,
    startup_vbs_path,
    verify_screenshot_ui_files,
)

user32 = ctypes.WinDLL("user32", use_last_error=True)

WH_KEYBOARD_LL = 13
HC_ACTION = 0
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105
PM_REMOVE = 0x0001
VK_SCROLL = 0x91
VK_SNAPSHOT = 0x2C
KEYEVENTF_KEYUP = 0x0002
VERIFY_SCROLLLOCK_EXTRAINFO = 0x53434C4B
VERIFY_PRINTSCREEN_EXTRAINFO = 0x50525453

ULONG_PTR = wintypes.WPARAM
LRESULT = wintypes.LPARAM


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", wintypes.DWORD),
        ("scanCode", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


LowLevelKeyboardProc = ctypes.WINFUNCTYPE(
    LRESULT,
    ctypes.c_int,
    wintypes.WPARAM,
    wintypes.LPARAM,
)

user32.SetWindowsHookExW.argtypes = [
    ctypes.c_int,
    LowLevelKeyboardProc,
    wintypes.HINSTANCE,
    wintypes.DWORD,
]
user32.SetWindowsHookExW.restype = wintypes.HHOOK
user32.CallNextHookEx.argtypes = [
    wintypes.HHOOK,
    ctypes.c_int,
    wintypes.WPARAM,
    wintypes.LPARAM,
]
user32.CallNextHookEx.restype = LRESULT
user32.UnhookWindowsHookEx.argtypes = [wintypes.HHOOK]
user32.UnhookWindowsHookEx.restype = wintypes.BOOL
user32.keybd_event.argtypes = [
    wintypes.BYTE,
    wintypes.BYTE,
    wintypes.DWORD,
    ULONG_PTR,
]
user32.keybd_event.restype = None
user32.PeekMessageW.argtypes = [
    ctypes.POINTER(wintypes.MSG),
    wintypes.HWND,
    wintypes.UINT,
    wintypes.UINT,
    wintypes.UINT,
]
user32.PeekMessageW.restype = wintypes.BOOL

HOOK_HANDLE = None
HOOK_PROC = None
SEEN_DOWN = False
SEEN_UP = False


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify ScrollLock screenshot hotkey patch and remap."
    )
    parser.add_argument(
        "--yandex-root",
        default=default_yandex_root(),
        help="Path to YandexBrowser root folder.",
    )
    parser.add_argument(
        "--skip-physical",
        action="store_true",
        help="Skip the low-level keyboard remap verification.",
    )
    return parser.parse_args()


def send_scrolllock(key_up: bool) -> None:
    user32.keybd_event(
        VK_SCROLL,
        0,
        KEYEVENTF_KEYUP if key_up else 0,
        VERIFY_SCROLLLOCK_EXTRAINFO,
    )


@LowLevelKeyboardProc
def keyboard_proc(n_code: int, w_param: int, l_param: int) -> int:
    global SEEN_DOWN
    global SEEN_UP

    if n_code == HC_ACTION:
        keyboard = ctypes.cast(l_param, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
        if (
            keyboard.vkCode == VK_SNAPSHOT
            and keyboard.dwExtraInfo == VERIFY_PRINTSCREEN_EXTRAINFO
        ):
            if w_param in (WM_KEYDOWN, WM_SYSKEYDOWN):
                SEEN_DOWN = True
            if w_param in (WM_KEYUP, WM_SYSKEYUP):
                SEEN_UP = True
    return user32.CallNextHookEx(HOOK_HANDLE, n_code, w_param, l_param)


def pump_messages(timeout_seconds: float) -> bool:
    deadline = time.monotonic() + timeout_seconds
    message = wintypes.MSG()
    while time.monotonic() < deadline:
        while user32.PeekMessageW(ctypes.byref(message), None, 0, 0, PM_REMOVE):
            user32.TranslateMessage(ctypes.byref(message))
            user32.DispatchMessageW(ctypes.byref(message))
        if SEEN_DOWN and SEEN_UP:
            return True
        time.sleep(0.01)
    return False


def verify_physical_remap() -> bool:
    global HOOK_HANDLE
    global HOOK_PROC
    global SEEN_DOWN
    global SEEN_UP

    SEEN_DOWN = False
    SEEN_UP = False
    HOOK_PROC = keyboard_proc
    HOOK_HANDLE = user32.SetWindowsHookExW(WH_KEYBOARD_LL, HOOK_PROC, None, 0)
    if not HOOK_HANDLE:
        raise ctypes.WinError(ctypes.get_last_error())

    try:
        send_scrolllock(key_up=False)
        send_scrolllock(key_up=True)
        return pump_messages(timeout_seconds=3.0)
    finally:
        if HOOK_HANDLE:
            user32.UnhookWindowsHookEx(HOOK_HANDLE)
            HOOK_HANDLE = None


def main() -> int:
    args = parse_args()
    yandex_root = Path(args.yandex_root)
    local_state = local_state_path(yandex_root)

    if not local_state.exists():
        print(f"[ERROR] Missing Local State: {local_state}")
        return 1

    payload = load_json(local_state)
    screenshoter = payload.get("screenshoter")
    if not isinstance(screenshoter, dict):
        print("[ERROR] Missing screenshoter section in Local State.")
        return 1
    ya = payload.get("ya")
    ya_screenshoter = ya.get("screenshoter") if isinstance(ya, dict) else None
    if not isinstance(ya_screenshoter, dict):
        print("[ERROR] Missing ya.screenshoter section in Local State.")
        return 1

    failed = False

    def check(label: str, actual: object, expected: object) -> None:
        nonlocal failed
        ok = actual == expected
        failed = failed or (not ok)
        print(
            f"  - {'OK' if ok else 'FAIL'} {label}: actual={actual!r}, expected={expected!r}"
        )

    print(f"[info] Local State: {local_state}")
    print("[Browser values]")
    check("screenshoter.enabled", screenshoter.get("enabled"), True)
    check(
        "screenshoter.alternative_hotkeys",
        screenshoter.get("alternative_hotkeys"),
        True,
    )
    check("screenshoter.hotkey_area", screenshoter.get("hotkey_area"), PATCHED_HOTKEY_AREA)
    check(
        "screenshoter.hotkey_screen",
        screenshoter.get("hotkey_screen"),
        PATCHED_HOTKEY_SCREEN,
    )
    check("ya.screenshoter.enabled", ya_screenshoter.get("enabled"), True)
    check(
        "ya.screenshoter.alternative_hotkeys",
        ya_screenshoter.get("alternative_hotkeys"),
        True,
    )
    check(
        "ya.screenshoter.hotkey_area",
        ya_screenshoter.get("hotkey_area"),
        PATCHED_HOTKEY_AREA,
    )
    check(
        "ya.screenshoter.hotkey_screen",
        ya_screenshoter.get("hotkey_screen"),
        PATCHED_HOTKEY_SCREEN,
    )

    print("[UI labels]")
    for result in verify_screenshot_ui_files(yandex_root):
        print(f"  - file: {result.path}")
        for line in result.logs:
            failed = failed or (not line.startswith("OK "))
            print(f"    - {line}")

    print("[Remap state]")
    processes = get_remap_processes()
    remap_running = bool(processes)
    startup_present = startup_vbs_contains_remap()
    check("remap.process_running", remap_running, True)
    check("remap.startup_vbs", startup_present, True)
    print(f"  - info startup path: {startup_vbs_path()}")
    print(f"  - info remap process count: {len(processes)}")

    if args.skip_physical:
        print("[Physical check]")
        print("  - SKIP physical remap verification")
    else:
        print("[Physical check]")
        physical_ok = verify_physical_remap()
        check("ScrollLock -> PrintScreen", physical_ok, True)

    if failed:
        print("[RESULT] FAIL")
        return 2

    print("[RESULT] OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
