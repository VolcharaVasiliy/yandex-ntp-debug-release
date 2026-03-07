from __future__ import annotations

import argparse
import contextlib
import ctypes
import io
import json
import os
import queue
import runpy
import signal
import subprocess
import sys
import threading
import time
import traceback
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import tkinter as tk
from tkinter import messagebox, ttk
from tkinter.scrolledtext import ScrolledText


WINDOW_TITLE = "Yandex PatchKit Launcher"
POWERSHELL_EXE = (
    Path(os.environ.get("SystemRoot", r"C:\Windows"))
    / "System32"
    / "WindowsPowerShell"
    / "v1.0"
    / "powershell.exe"
)
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
YANDEX_LOCAL_ROOT = (
    Path(os.environ.get("LOCALAPPDATA", ""))
    / "Yandex"
    / "YandexBrowser"
).resolve()
user32 = ctypes.WinDLL("user32", use_last_error=True)

WH_KEYBOARD_LL = 13
HC_ACTION = 0
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105
VK_SCROLL = 0x91
VK_SNAPSHOT = 0x2C
KEYEVENTF_KEYUP = 0x0002
LLKHF_INJECTED = 0x0010
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
user32.GetMessageW.argtypes = [
    ctypes.POINTER(wintypes.MSG),
    wintypes.HWND,
    wintypes.UINT,
    wintypes.UINT,
]
user32.GetMessageW.restype = wintypes.BOOL

SCROLLLOCK_HOOK_HANDLE = None
SCROLLLOCK_HOOK_PROC = None


@dataclass(frozen=True)
class ScriptRun:
    file_name: str
    args: tuple[str, ...] = ()


@dataclass(frozen=True)
class Action:
    number: int
    title: str
    description: str
    kind: str
    scripts: tuple[ScriptRun, ...] = ()
    requires_browser_closed: bool = False


class QueueWriter(io.TextIOBase):
    def __init__(self, output_queue: queue.Queue[tuple[str, Any]]) -> None:
        super().__init__()
        self.output_queue = output_queue

    def write(self, text: str) -> int:
        if text:
            self.output_queue.put(("log", text))
        return len(text)

    def flush(self) -> None:
        return None


def normalize_exit_code(code: object) -> int:
    if code is None:
        return 0
    if isinstance(code, int):
        return code
    if isinstance(code, bool):
        return int(code)
    return 1


def resolve_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def resolve_bundle_dir() -> Path:
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass).resolve()
    return resolve_base_dir()


def resolve_scripts_dir() -> Path:
    bundled = resolve_bundle_dir() / "scripts"
    if bundled.exists():
        return bundled
    return resolve_base_dir() / "scripts"


def send_print_screen(key_up: bool, extra_info: int) -> None:
    user32.keybd_event(
        VK_SNAPSHOT,
        0,
        KEYEVENTF_KEYUP if key_up else 0,
        extra_info,
    )


def request_remap_stop(*_args) -> None:
    user32.PostQuitMessage(0)


@LowLevelKeyboardProc
def scrolllock_keyboard_proc(n_code: int, w_param: int, l_param: int) -> int:
    if n_code == HC_ACTION:
        keyboard = ctypes.cast(l_param, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
        is_injected = bool(keyboard.flags & LLKHF_INJECTED)
        is_verify_scrolllock = keyboard.dwExtraInfo == VERIFY_SCROLLLOCK_EXTRAINFO
        if keyboard.vkCode == VK_SCROLL and (not is_injected or is_verify_scrolllock):
            printscreen_extra = (
                VERIFY_PRINTSCREEN_EXTRAINFO if is_verify_scrolllock else 0
            )
            if w_param in (WM_KEYDOWN, WM_SYSKEYDOWN):
                send_print_screen(key_up=False, extra_info=printscreen_extra)
                return 1
            if w_param in (WM_KEYUP, WM_SYSKEYUP):
                send_print_screen(key_up=True, extra_info=printscreen_extra)
                return 1
    return user32.CallNextHookEx(SCROLLLOCK_HOOK_HANDLE, n_code, w_param, l_param)


def run_scrolllock_remap_daemon() -> int:
    global SCROLLLOCK_HOOK_HANDLE
    global SCROLLLOCK_HOOK_PROC

    signal.signal(signal.SIGINT, request_remap_stop)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, request_remap_stop)

    SCROLLLOCK_HOOK_PROC = scrolllock_keyboard_proc
    SCROLLLOCK_HOOK_HANDLE = user32.SetWindowsHookExW(
        WH_KEYBOARD_LL,
        SCROLLLOCK_HOOK_PROC,
        None,
        0,
    )
    if not SCROLLLOCK_HOOK_HANDLE:
        raise ctypes.WinError(ctypes.get_last_error())

    message = wintypes.MSG()
    while user32.GetMessageW(ctypes.byref(message), None, 0, 0) != 0:
        user32.TranslateMessage(ctypes.byref(message))
        user32.DispatchMessageW(ctypes.byref(message))

    if SCROLLLOCK_HOOK_HANDLE:
        user32.UnhookWindowsHookEx(SCROLLLOCK_HOOK_HANDLE)
        SCROLLLOCK_HOOK_HANDLE = None
    return 0


def build_actions() -> list[Action]:
    return [
        Action(
            1,
            "Применить все",
            "Запускает все безопасные слои подряд: context-safe, NTP link-only и banner-off.",
            "sequence",
            (
                ScriptRun("apply_context_safe.py"),
                ScriptRun("apply_ntp_link_only.py"),
                ScriptRun("disable_ntp_banner.py"),
            ),
            True,
        ),
        Action(
            2,
            "Проверить все",
            "Проверяет все safe-слои подряд без изменения файлов браузера.",
            "sequence",
            (
                ScriptRun("verify_context_safe.py"),
                ScriptRun("verify_ntp_link_only.py"),
                ScriptRun("verify_ntp_banner_disabled.py"),
            ),
            False,
        ),
        Action(
            3,
            "Закрыть Yandex Browser",
            "Аккуратно завершает процессы Yandex Browser перед apply или restore.",
            "internal",
            (),
            False,
        ),
        Action(
            4,
            "Применить Context Safe",
            "Включает Google для выделенного текста, Ask ChatGPT и рабочие popup-иконки.",
            "sequence",
            (ScriptRun("apply_context_safe.py"),),
            True,
        ),
        Action(
            5,
            "Применить NTP Link Only",
            "Меняет только ссылку верхней Alice-кнопки на новой вкладке без правки текста и иконок.",
            "sequence",
            (ScriptRun("apply_ntp_link_only.py"),),
            True,
        ),
        Action(
            6,
            "Отключить NTP Banner",
            "Отдельно отключает рекламный баннер и виджеты новой вкладки.",
            "sequence",
            (ScriptRun("disable_ntp_banner.py"),),
            True,
        ),
        Action(
            7,
            "Проверить Context Safe",
            "Проверяет патч Google и popup-слой без изменений файлов.",
            "sequence",
            (ScriptRun("verify_context_safe.py"),),
            False,
        ),
        Action(
            8,
            "Проверить NTP Link Only",
            "Проверяет, что link-only слой новой вкладки применен корректно.",
            "sequence",
            (ScriptRun("verify_ntp_link_only.py"),),
            False,
        ),
        Action(
            9,
            "Проверить NTP Banner",
            "Только проверяет флаги отключения banner-off и ничего не меняет в профиле.",
            "sequence",
            (ScriptRun("verify_ntp_banner_disabled.py"),),
            False,
        ),
        Action(
            10,
            "Откатить New Tab Backup",
            "Возвращает сохраненный backup новой вкладки и связанных NTP-файлов.",
            "sequence",
            (ScriptRun("restore_newtab_backup.py"),),
            True,
        ),
        Action(
            11,
            "Откатить Banner Backup",
            "Возвращает backup настроек banner-off в профиле браузера.",
            "sequence",
            (ScriptRun("restore_ntp_banner_backup.py"),),
            True,
        ),
        Action(
            12,
            "Откатить все",
            "Запускает общий restore: new tab backup и banner backup подряд.",
            "sequence",
            (
                ScriptRun("restore_newtab_backup.py"),
                ScriptRun("restore_ntp_banner_backup.py"),
            ),
            True,
        ),
        Action(
            13,
            "Применить Screenshot ScrollLock",
            "Меняет screenshoter и ya.screenshoter на ScrollLock, обновляет подписи PrtScr в настройках/панели и включает физический remap ScrollLock -> PrintScreen.",
            "sequence",
            (ScriptRun("apply_screenshot_hotkey_scrolllock.py"),),
            True,
        ),
        Action(
            14,
            "Проверить Screenshot ScrollLock",
            "Проверяет Local State, ya.screenshoter, UI-подписи в browser.dll/ru.pak, автозапуск remap и физическую работу ScrollLock -> PrintScreen.",
            "sequence",
            (ScriptRun("verify_screenshot_hotkey_scrolllock.py"),),
            False,
        ),
        Action(
            15,
            "Откатить Screenshot ScrollLock",
            "Восстанавливает hotkey скриншотера и подписи UI из backup или в дефолт и отключает remap ScrollLock.",
            "sequence",
            (ScriptRun("restore_screenshot_hotkey_scrolllock.py"),),
            True,
        ),
    ]


def build_startupinfo() -> subprocess.STARTUPINFO | None:
    if not hasattr(subprocess, "STARTUPINFO"):
        return None
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = 0
    return startupinfo


def run_hidden_process(
    command: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    capture_output: bool = False,
    check: bool = False,
) -> subprocess.CompletedProcess[str]:
    kwargs: dict[str, Any] = {
        "cwd": str(cwd) if cwd else None,
        "env": env,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
        "creationflags": CREATE_NO_WINDOW,
        "startupinfo": build_startupinfo(),
    }
    if capture_output:
        kwargs["capture_output"] = True
    result = subprocess.run(command, **kwargs)
    if check and result.returncode != 0:
        stdout = (result.stdout or "").strip()
        stderr = (result.stderr or "").strip()
        raise RuntimeError(stderr or stdout or f"Command failed: {' '.join(command)}")
    return result


def run_hidden_powershell(script: str, *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return run_hidden_process(
        [
            str(POWERSHELL_EXE),
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            script,
        ],
        capture_output=True,
        check=check,
    )


def get_yandex_processes() -> list[dict[str, Any]]:
    root_escaped = str(YANDEX_LOCAL_ROOT).replace("'", "''")
    script = f"""
$targetRoot = '{root_escaped}'
$procs = Get-CimInstance Win32_Process |
    Where-Object {{
        ($_.Name -eq 'browser.exe' -or $_.Name -eq 'browser_proxy.exe') -and
        $_.ExecutablePath -and
        $_.ExecutablePath.StartsWith($targetRoot, [System.StringComparison]::OrdinalIgnoreCase)
    }} |
    Sort-Object ProcessId |
    Select-Object @{{Name='Id';Expression={{$_.ProcessId}}}},
                  @{{Name='ProcessName';Expression={{$_.Name}}}},
                  @{{Name='Path';Expression={{$_.ExecutablePath}}}}

if ($procs) {{
    $procs | ConvertTo-Json -Compress
}} else {{
    '[]'
}}
"""
    result = run_hidden_powershell(script, check=True)
    payload = (result.stdout or "").strip()
    if not payload:
        return []
    parsed = json.loads(payload)
    if isinstance(parsed, dict):
        return [parsed]
    return parsed


def close_yandex_browser() -> int:
    processes = get_yandex_processes()
    if not processes:
        return 0
    ids = ",".join(str(proc["Id"]) for proc in processes)
    run_hidden_powershell(f"Stop-Process -Id {ids} -Force -ErrorAction Stop", check=True)
    time.sleep(1.2)
    remaining = get_yandex_processes()
    if remaining:
        raise RuntimeError("Не удалось закрыть все процессы Yandex Browser.")
    return len(processes)


def execute_embedded_script(
    script_path: Path,
    script_args: tuple[str, ...],
    output_queue: queue.Queue[tuple[str, Any]],
) -> int:
    writer = QueueWriter(output_queue)
    original_argv = sys.argv[:]
    original_path = sys.path[:]
    scripts_dir = str(script_path.parent)
    inserted = False

    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
        inserted = True

    try:
        sys.argv = [str(script_path), *script_args]
        with contextlib.redirect_stdout(writer), contextlib.redirect_stderr(writer):
            try:
                runpy.run_path(str(script_path), run_name="__main__")
                return 0
            except SystemExit as exc:
                return normalize_exit_code(exc.code)
            except Exception:
                traceback.print_exc()
                return 1
    finally:
        sys.argv = original_argv
        if inserted:
            sys.path[:] = original_path


def build_self_test(base_dir: Path, actions: list[Action]) -> dict[str, Any]:
    bundle_dir = resolve_bundle_dir()
    scripts_dir = resolve_scripts_dir()
    action_rows = []
    missing_files = []
    for action in actions:
        script_paths = [scripts_dir / script.file_name for script in action.scripts]
        exists = action.kind == "internal" or all(path.exists() for path in script_paths)
        action_rows.append(
            {
                "number": action.number,
                "title": action.title,
                "kind": action.kind,
                "paths": [str(path) for path in script_paths],
                "exists": exists,
                "requires_browser_closed": action.requires_browser_closed,
            }
        )
        if not exists:
            missing_files.extend(str(path) for path in script_paths if not path.exists())
    return {
        "base_dir": str(base_dir),
        "bundle_dir": str(bundle_dir),
        "scripts_dir": str(scripts_dir),
        "frozen": bool(getattr(sys, "frozen", False)),
        "browser_running": bool(get_yandex_processes()),
        "action_count": len(action_rows),
        "actions": action_rows,
        "missing_files": missing_files,
        "standalone_ready": len(missing_files) == 0,
    }


def build_failure_dialog(action: Action, return_code: int) -> tuple[str, str]:
    browser_running = bool(get_yandex_processes())
    browser_hint = ""
    if browser_running:
        browser_hint = (
            "\n\nСейчас Yandex Browser открыт. Пока он запущен, профиль и Local State могут "
            "перезаписываться самим браузером."
        )

    if action.number == 9 and return_code == 2:
        return (
            "warning",
            "Пункт 9 ничего не меняет. Он только проверяет состояние banner-off.\n\n"
            "Сейчас проверка не пройдена. Обычно нужно:\n"
            "1. закрыть Yandex Browser;\n"
            "2. запустить пункт 6 «Отключить NTP Banner»;\n"
            "3. потом снова запустить пункт 9.\n\n"
            "Подробности смотри в журнале справа."
            + browser_hint,
        )

    if action.number == 2 and return_code == 2:
        return (
            "warning",
            "Общая проверка не пройдена: хотя бы один safe-слой сейчас не соответствует "
            "ожидаемому состоянию.\n\nПодробности смотри в журнале справа."
            + browser_hint,
        )

    if action.number in {7, 8} and return_code == 2:
        return (
            "warning",
            f"Проверка не пройдена: {action.title}.\n\n"
            "Этот пункт ничего не меняет, а только проверяет текущее состояние.\n"
            "Подробности смотри в журнале справа."
            + browser_hint,
        )

    if action.number == 14 and return_code == 2:
        return (
            "warning",
            "Проверка screenshot-слоя не пройдена.\n\n"
            "Обычно это значит, что не совпали значения в Local State / ya.screenshoter, "
            "не обновились UI-подписи в browser.dll или ru.pak, не включен автозапуск remap "
            "или не работает физический ScrollLock -> PrintScreen.\n\n"
            "Подробности смотри в журнале справа."
            + browser_hint,
        )

    return (
        "error",
        f"Действие завершилось с кодом {return_code}:\n{action.title}\n\n"
        "Подробности смотри в журнале справа.",
    )


class LauncherApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.base_dir = resolve_base_dir()
        self.bundle_dir = resolve_bundle_dir()
        self.scripts_dir = resolve_scripts_dir()
        self.actions = build_actions()
        self.action_map = {action.number: action for action in self.actions}
        self.output_queue: queue.Queue[tuple[str, Any]] = queue.Queue()
        self.worker: threading.Thread | None = None
        self.running_action: Action | None = None

        self.status_var = tk.StringVar(value="Готово к запуску.")
        self.browser_status_var = tk.StringVar(value="Проверка процессов Yandex Browser...")
        self.browser_hint_var = tk.StringVar(
            value="Перед apply/restore лучше закрыть браузер. Launcher предупредит, если он открыт."
        )
        self.path_hint_var = tk.StringVar(value=f"Целевой браузер: {YANDEX_LOCAL_ROOT}")
        self.number_var = tk.StringVar()

        self.action_buttons: dict[int, ttk.Button] = {}
        self.run_by_number_button: ttk.Button | None = None
        self.close_button: ttk.Button | None = None
        self.exit_button: ttk.Button | None = None
        self.browser_badge: tk.Label | None = None
        self.log_text: ScrolledText | None = None
        self.actions_canvas: tk.Canvas | None = None
        self.actions_inner: ttk.Frame | None = None
        self.actions_window_id: int | None = None

        self._configure_window()
        self._build_ui()
        self.refresh_browser_status()
        self.root.after(150, self._drain_output_queue)
        self.root.after(3000, self._poll_browser_status)

    def _configure_window(self) -> None:
        self.root.title(WINDOW_TITLE)
        self.root.geometry("1180x860")
        self.root.minsize(1020, 760)
        self.root.configure(bg="#f3f4f6")
        self.root.protocol("WM_DELETE_WINDOW", self.on_exit)

        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure("App.TFrame", background="#f3f4f6")
        style.configure("Card.TFrame", background="#ffffff")
        style.configure("Title.TLabel", background="#f3f4f6", font=("Segoe UI Semibold", 18))
        style.configure("Hint.TLabel", background="#f3f4f6", font=("Segoe UI", 10))
        style.configure("CardTitle.TLabel", background="#ffffff", font=("Segoe UI Semibold", 11))
        style.configure("CardText.TLabel", background="#ffffff", font=("Segoe UI", 10))
        style.configure("ActionTitle.TLabel", background="#ffffff", font=("Segoe UI Semibold", 10))
        style.configure("ActionText.TLabel", background="#ffffff", font=("Segoe UI", 9))
        style.configure("Run.TButton", font=("Segoe UI Semibold", 10))

    def _build_ui(self) -> None:
        outer = ttk.Frame(self.root, style="App.TFrame", padding=18)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(2, weight=1)

        header = ttk.Frame(outer, style="App.TFrame")
        header.grid(row=0, column=0, sticky="ew")
        ttk.Label(header, text=WINDOW_TITLE, style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            header,
            text="Действия можно запускать кнопкой или по номеру. Для apply/restore launcher предупреждает, если браузер открыт.",
            style="Hint.TLabel",
        ).pack(anchor="w", pady=(6, 0))
        ttk.Label(header, textvariable=self.path_hint_var, style="Hint.TLabel").pack(anchor="w", pady=(4, 0))

        top = ttk.Frame(outer, style="App.TFrame", padding=(0, 14, 0, 12))
        top.grid(row=1, column=0, sticky="ew")
        top.columnconfigure(0, weight=1)
        top.columnconfigure(1, weight=1)

        browser_card = ttk.Frame(top, style="Card.TFrame", padding=14)
        browser_card.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        ttk.Label(browser_card, text="Статус браузера", style="CardTitle.TLabel").pack(anchor="w")
        self.browser_badge = tk.Label(
            browser_card,
            textvariable=self.browser_status_var,
            font=("Segoe UI Semibold", 10),
            bg="#fef3c7",
            fg="#92400e",
            anchor="w",
            justify="left",
            padx=10,
            pady=8,
        )
        self.browser_badge.pack(fill="x", pady=(10, 8))
        ttk.Label(browser_card, textvariable=self.browser_hint_var, style="CardText.TLabel", wraplength=500).pack(
            anchor="w"
        )

        browser_buttons = ttk.Frame(browser_card, style="Card.TFrame")
        browser_buttons.pack(anchor="w", pady=(12, 0))
        ttk.Button(browser_buttons, text="Обновить статус", command=self.refresh_browser_status).pack(
            side="left", padx=(0, 8)
        )
        self.close_button = ttk.Button(
            browser_buttons,
            text="Закрыть Yandex Browser",
            style="Run.TButton",
            command=lambda: self.run_action_by_number(3),
        )
        self.close_button.pack(side="left")

        launch_card = ttk.Frame(top, style="Card.TFrame", padding=14)
        launch_card.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        ttk.Label(launch_card, text="Запуск по номеру", style="CardTitle.TLabel").pack(anchor="w")
        ttk.Label(
            launch_card,
            text="Введи номер действия, например 1, 6 или 12, затем нажми Enter или кнопку запуска.",
            style="CardText.TLabel",
            wraplength=500,
        ).pack(anchor="w", pady=(8, 12))

        selector = ttk.Frame(launch_card, style="Card.TFrame")
        selector.pack(anchor="w")
        ttk.Label(selector, text="Номер:", style="CardText.TLabel").pack(side="left")
        number_entry = ttk.Entry(selector, textvariable=self.number_var, width=8, font=("Segoe UI", 11))
        number_entry.pack(side="left", padx=(8, 8))
        number_entry.bind("<Return>", self._run_from_entry)
        self.run_by_number_button = ttk.Button(
            selector,
            text="Выполнить",
            style="Run.TButton",
            command=self._run_from_entry,
        )
        self.run_by_number_button.pack(side="left", padx=(0, 8))
        self.exit_button = ttk.Button(selector, text="Выход", command=self.on_exit)
        self.exit_button.pack(side="left")
        number_entry.focus_set()

        content = ttk.Frame(outer, style="App.TFrame")
        content.grid(row=2, column=0, sticky="nsew")
        content.columnconfigure(0, weight=3)
        content.columnconfigure(1, weight=2)
        content.rowconfigure(0, weight=1)

        actions_card = ttk.Frame(content, style="Card.TFrame", padding=14)
        actions_card.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        actions_card.columnconfigure(0, weight=1)
        actions_card.rowconfigure(1, weight=1)
        ttk.Label(actions_card, text="Доступные действия", style="CardTitle.TLabel").grid(
            row=0, column=0, sticky="w"
        )

        canvas_holder = ttk.Frame(actions_card, style="Card.TFrame")
        canvas_holder.grid(row=1, column=0, sticky="nsew", pady=(10, 0))
        canvas_holder.columnconfigure(0, weight=1)
        canvas_holder.rowconfigure(0, weight=1)

        self.actions_canvas = tk.Canvas(
            canvas_holder,
            background="#ffffff",
            highlightthickness=0,
            borderwidth=0,
        )
        self.actions_canvas.grid(row=0, column=0, sticky="nsew")

        actions_scrollbar = ttk.Scrollbar(canvas_holder, orient="vertical", command=self.actions_canvas.yview)
        actions_scrollbar.grid(row=0, column=1, sticky="ns")
        self.actions_canvas.configure(yscrollcommand=actions_scrollbar.set)

        self.actions_inner = ttk.Frame(self.actions_canvas, style="Card.TFrame")
        self.actions_window_id = self.actions_canvas.create_window((0, 0), window=self.actions_inner, anchor="nw")
        self.actions_inner.columnconfigure(1, weight=1)
        self.actions_inner.bind("<Configure>", self._on_actions_inner_configure)
        self.actions_canvas.bind("<Configure>", self._on_actions_canvas_configure)

        self._bind_mousewheel(self.actions_canvas)
        self._bind_mousewheel(self.actions_inner)

        for row_index, action in enumerate(self.actions):
            row = ttk.Frame(self.actions_inner, style="Card.TFrame", padding=(0, 8))
            row.grid(row=row_index, column=0, sticky="ew")
            row.columnconfigure(1, weight=1)
            self._bind_mousewheel(row)

            number_badge = tk.Label(
                row,
                text=str(action.number),
                font=("Segoe UI Semibold", 10),
                bg="#0f172a",
                fg="#f8fafc",
                width=4,
                pady=6,
            )
            number_badge.grid(row=0, column=0, rowspan=2, sticky="nw")
            self._bind_mousewheel(number_badge)

            ttk.Label(row, text=action.title, style="ActionTitle.TLabel").grid(
                row=0, column=1, sticky="w", padx=(12, 12)
            )
            ttk.Label(
                row,
                text=action.description,
                style="ActionText.TLabel",
                wraplength=610,
                justify="left",
            ).grid(row=1, column=1, sticky="w", padx=(12, 12), pady=(4, 0))

            button = ttk.Button(
                row,
                text="Запустить",
                command=lambda number=action.number: self.run_action_by_number(number),
            )
            button.grid(row=0, column=2, rowspan=2, sticky="e")
            if not self.action_exists(action):
                button.state(["disabled"])
            self.action_buttons[action.number] = button

        log_card = ttk.Frame(content, style="Card.TFrame", padding=14)
        log_card.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        log_card.rowconfigure(1, weight=1)
        log_card.columnconfigure(0, weight=1)
        ttk.Label(log_card, text="Журнал выполнения", style="CardTitle.TLabel").grid(
            row=0, column=0, sticky="w"
        )

        self.log_text = ScrolledText(
            log_card,
            height=25,
            wrap="word",
            font=("Consolas", 9),
            bg="#0f172a",
            fg="#e5e7eb",
            insertbackground="#e5e7eb",
            relief="flat",
            borderwidth=0,
            padx=12,
            pady=12,
        )
        self.log_text.grid(row=1, column=0, sticky="nsew", pady=(10, 0))
        self.log_text.configure(state="disabled")

        footer = ttk.Frame(outer, style="App.TFrame", padding=(0, 12, 0, 0))
        footer.grid(row=3, column=0, sticky="ew")
        ttk.Label(footer, textvariable=self.status_var, style="Hint.TLabel").pack(anchor="w")

        self.append_log("Launcher готов. Выбери действие кнопкой или по номеру.\n")
        self.append_log(f"[launcher] scripts dir: {self.scripts_dir}\n")
        if getattr(sys, "frozen", False):
            self.append_log("[launcher] Режим: standalone EXE\n")
        else:
            self.append_log("[launcher] Режим: Python source\n")

    def append_log(self, text: str) -> None:
        if not self.log_text:
            return
        self.log_text.configure(state="normal")
        self.log_text.insert("end", text)
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _bind_mousewheel(self, widget: tk.Misc | None) -> None:
        if widget is None:
            return
        widget.bind("<Enter>", self._activate_mousewheel, add="+")
        widget.bind("<Leave>", self._deactivate_mousewheel, add="+")

    def _activate_mousewheel(self, _event: tk.Event) -> None:
        self.root.bind_all("<MouseWheel>", self._on_mousewheel)

    def _deactivate_mousewheel(self, _event: tk.Event) -> None:
        self.root.unbind_all("<MouseWheel>")

    def _on_mousewheel(self, event: tk.Event) -> None:
        if self.actions_canvas is None:
            return
        delta = getattr(event, "delta", 0)
        if delta == 0:
            return
        self.actions_canvas.yview_scroll(-int(delta / 120), "units")

    def _on_actions_inner_configure(self, _event: tk.Event) -> None:
        if self.actions_canvas is None:
            return
        self.actions_canvas.configure(scrollregion=self.actions_canvas.bbox("all"))

    def _on_actions_canvas_configure(self, event: tk.Event) -> None:
        if self.actions_canvas is None or self.actions_window_id is None:
            return
        self.actions_canvas.itemconfigure(self.actions_window_id, width=event.width)

    def script_path(self, script_name: str) -> Path:
        return self.scripts_dir / script_name

    def action_exists(self, action: Action) -> bool:
        if action.kind == "internal":
            return True
        return all(self.script_path(script.file_name).exists() for script in action.scripts)

    def set_busy(self, busy: bool) -> None:
        for button in self.action_buttons.values():
            if busy:
                button.state(["disabled"])
            else:
                button.state(["!disabled"])

        for action in self.actions:
            if not self.action_exists(action):
                self.action_buttons[action.number].state(["disabled"])

        if self.run_by_number_button is not None:
            if busy:
                self.run_by_number_button.state(["disabled"])
            else:
                self.run_by_number_button.state(["!disabled"])
        if self.close_button is not None:
            if busy:
                self.close_button.state(["disabled"])
            else:
                self.close_button.state(["!disabled"])

    def refresh_browser_status(self) -> None:
        try:
            processes = get_yandex_processes()
            if processes:
                count = len(processes)
                self.browser_status_var.set(f"Yandex Browser открыт. Найдено процессов: {count}.")
                self.browser_hint_var.set(
                    "Перед apply/restore лучше закрыть браузер. Можно нажать кнопку сверху или согласиться на авто-закрытие."
                )
                if self.browser_badge is not None:
                    self.browser_badge.configure(bg="#fee2e2", fg="#991b1b")
            else:
                self.browser_status_var.set("Yandex Browser закрыт. Можно безопасно запускать apply и restore.")
                self.browser_hint_var.set(
                    "Браузер не найден. На чистом ПК достаточно самого EXE и установленного Yandex Browser."
                )
                if self.browser_badge is not None:
                    self.browser_badge.configure(bg="#dcfce7", fg="#166534")
        except Exception as exc:
            self.browser_status_var.set("Не удалось проверить процессы Yandex Browser.")
            self.browser_hint_var.set(str(exc))
            if self.browser_badge is not None:
                self.browser_badge.configure(bg="#fef3c7", fg="#92400e")

    def _poll_browser_status(self) -> None:
        if not self.running_action:
            self.refresh_browser_status()
        self.root.after(3000, self._poll_browser_status)

    def _run_from_entry(self, _event: tk.Event | None = None) -> None:
        raw_value = self.number_var.get().strip()
        if not raw_value:
            messagebox.showwarning(WINDOW_TITLE, "Введи номер действия.")
            return
        try:
            action_number = int(raw_value)
        except ValueError:
            messagebox.showwarning(WINDOW_TITLE, "Номер действия должен состоять только из цифр.")
            return
        self.run_action_by_number(action_number)

    def run_action_by_number(self, action_number: int) -> None:
        action = self.action_map.get(action_number)
        if not action:
            messagebox.showwarning(WINDOW_TITLE, f"Действие {action_number} не найдено.")
            return
        if self.running_action is not None:
            messagebox.showwarning(WINDOW_TITLE, "Сейчас уже выполняется другое действие. Дождись завершения.")
            return
        if not self.action_exists(action):
            missing = [
                str(self.script_path(script.file_name))
                for script in action.scripts
                if not self.script_path(script.file_name).exists()
            ]
            messagebox.showerror(
                WINDOW_TITLE,
                "Не найдены встроенные скрипты:\n\n" + "\n".join(missing),
            )
            return

        if action.requires_browser_closed:
            processes = get_yandex_processes()
            if processes:
                decision = messagebox.askyesno(
                    WINDOW_TITLE,
                    "Yandex Browser сейчас открыт.\n\n"
                    "Для этого действия продолжение без закрытия запрещено, "
                    "иначе браузер может сразу перезаписать Local State и другие файлы.\n\n"
                    "Да  -> закрыть браузер и продолжить\n"
                    "Нет -> отменить запуск действия",
                )
                if not decision:
                    return
                try:
                    closed = close_yandex_browser()
                    self.append_log(
                        f"[launcher] Закрыто процессов Yandex Browser: {closed}\n"
                    )
                    self.refresh_browser_status()
                except Exception as exc:
                    messagebox.showerror(WINDOW_TITLE, f"Не удалось закрыть браузер:\n{exc}")
                    return

        self._start_external_action(action)

    def _run_internal_action(self, action: Action) -> None:
        try:
            closed = close_yandex_browser()
            if closed:
                self.append_log(f"[launcher] Закрыто процессов Yandex Browser: {closed}\n")
            else:
                self.append_log("[launcher] Процессы Yandex Browser не найдены.\n")
            self.status_var.set("Команда закрытия браузера завершена.")
            self.refresh_browser_status()
        except Exception as exc:
            self.append_log(f"[launcher] Ошибка закрытия браузера: {exc}\n")
            messagebox.showerror(WINDOW_TITLE, f"Не удалось закрыть браузер:\n{exc}")

    def _start_external_action(self, action: Action) -> None:
        self.running_action = action
        self.status_var.set(f"Выполняется: {action.number}. {action.title}")
        self.append_log(f"\n=== {action.number}. {action.title} ===\n")
        self.set_busy(True)

        worker = threading.Thread(target=self._run_external_action_worker, args=(action,), daemon=True)
        self.worker = worker
        worker.start()

    def _run_external_action_worker(self, action: Action) -> None:
        try:
            if action.kind == "internal":
                closed = close_yandex_browser()
                self.output_queue.put(("log", f"[launcher] Закрыто процессов Yandex Browser: {closed}\n"))
                self.output_queue.put(("done", action.number, 0))
                return

            return_code = 0
            for script in action.scripts:
                script_path = self.script_path(script.file_name)
                self.output_queue.put(("log", f"[launcher] {script.file_name}\n"))
                return_code = execute_embedded_script(script_path, script.args, self.output_queue)
                if return_code != 0:
                    break

            self.output_queue.put(("done", action.number, return_code))
        except Exception as exc:
            self.output_queue.put(("error", action.number, traceback.format_exc() or str(exc)))

    def _drain_output_queue(self) -> None:
        while True:
            try:
                item = self.output_queue.get_nowait()
            except queue.Empty:
                break

            kind = item[0]
            if kind == "log":
                self.append_log(item[1])
            elif kind == "done":
                action_number = item[1]
                return_code = item[2]
                action = self.action_map[action_number]
                if return_code == 0:
                    self.append_log(f"[launcher] Действие завершено успешно: {action.title}\n")
                    self.status_var.set(f"Готово: {action.number}. {action.title}")
                else:
                    self.append_log(
                        f"[launcher] Действие завершилось с кодом {return_code}: {action.title}\n"
                    )
                    self.status_var.set(
                        f"Ошибка {return_code}: {action.number}. {action.title}"
                    )
                    dialog_kind, dialog_text = build_failure_dialog(action, return_code)
                    if dialog_kind == "warning":
                        messagebox.showwarning(WINDOW_TITLE, dialog_text)
                    else:
                        messagebox.showerror(WINDOW_TITLE, dialog_text)
                self.running_action = None
                self.worker = None
                self.set_busy(False)
                self.refresh_browser_status()
            elif kind == "error":
                action_number = item[1]
                error_text = item[2]
                action = self.action_map[action_number]
                self.append_log(f"[launcher] Ошибка запуска: {error_text}\n")
                self.status_var.set(f"Ошибка запуска: {action.number}. {action.title}")
                self.running_action = None
                self.worker = None
                self.set_busy(False)
                self.refresh_browser_status()
                messagebox.showerror(
                    WINDOW_TITLE,
                    f"Не удалось запустить действие:\n{action.title}\n\n{error_text}",
                )

        self.root.after(150, self._drain_output_queue)

    def on_exit(self) -> None:
        if self.running_action is not None:
            should_exit = messagebox.askyesno(
                WINDOW_TITLE,
                "Сейчас выполняется действие. Закрыть launcher все равно?",
            )
            if not should_exit:
                return
        self.root.destroy()


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=WINDOW_TITLE)
    parser.add_argument(
        "--scrolllock-remap-daemon",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Run a non-GUI launcher self-test and print JSON to stdout.",
    )
    parser.add_argument(
        "--self-test-output",
        type=Path,
        help="Run a non-GUI launcher self-test and write JSON to the provided file.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    base_dir = resolve_base_dir()
    actions = build_actions()

    if args.scrolllock_remap_daemon:
        return run_scrolllock_remap_daemon()

    if args.self_test or args.self_test_output:
        payload = build_self_test(base_dir, actions)
        rendered = json.dumps(payload, ensure_ascii=False, indent=2)
        if args.self_test_output:
            args.self_test_output.parent.mkdir(parents=True, exist_ok=True)
            args.self_test_output.write_text(rendered + "\n", encoding="utf-8")
        else:
            print(rendered)
        return 0

    root = tk.Tk()
    LauncherApp(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
