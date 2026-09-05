#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import os
import re
import shutil
import struct
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

ZERO_WIDTH_SPACE = b"\xE2\x80\x8B"
SOFT_HYPHEN = b"\xC2\xAD"


def pad_invisible_label(visible_text: str, target_length: int) -> bytes:
    visible_bytes = visible_text.encode("utf-8")
    if len(visible_bytes) > target_length:
        raise RuntimeError(
            f"Visible label is too long: {visible_text!r} ({len(visible_bytes)} > {target_length})"
        )

    remainder = target_length - len(visible_bytes)
    filler = bytearray()
    while remainder >= len(ZERO_WIDTH_SPACE):
        filler.extend(ZERO_WIDTH_SPACE)
        remainder -= len(ZERO_WIDTH_SPACE)
    if remainder == len(SOFT_HYPHEN):
        filler.extend(SOFT_HYPHEN)
        remainder = 0
    if remainder != 0:
        raise RuntimeError(
            f"Could not build invisible filler for label {visible_text!r}: remainder={remainder}"
        )
    return visible_bytes + bytes(filler)


SEARCH_REPLACEMENTS = [
    (
        b"{yandex:baseURL}search/?text={searchTerms}",
        b"https://google.com/search?q={searchTerms}&",
        "web_search_base",
    ),
    (
        b"{yandex:baseURL}search/pad/?text={searchTerms}",
        b"https://google.com/search?q={searchTerms}&pd=1",
        "web_search_pad",
    ),
    (
        b"{yandex:baseURL}search/touch/?text={searchTerms}",
        b"https://google.com/search?q={searchTerms}&src=yb",
        "web_search_touch",
    ),
    (
        b"{yandex:baseURL}yandsearch?text={searchTerms}",
        b"https://google.com/search?q={searchTerms}&p=1",
        "web_search_yandsearch",
    ),
    (
        b"{yandex:baseURL}{yandex:searchPath}?text={searchTerms}&",
        b"{google:baseURL}search?q={searchTerms}&sourceid=chrome&",
        "web_search_macro_main",
    ),
    (
        b"https://ya.ru/{yandex:searchPath}?text={searchTerms}&",
        b"https://google.ru/search?q={searchTerms}&sourceid=yb&",
        "web_search_macro_ya_fallback",
    ),
    (
        b'https://alice.yandex.ru/?utm_campaign={context}&utm_source=desktop_browser&alice_deeplink={"text":"{query}"}',
        b"https://chatgpt.com/?q={query}&utm_campaign={context}&utm_source=desktop_browser&source=yabrowser&&&&&&&&&&&",
        "instaserp_ask_ai_button_url",
    ),
    (
        # Since 26.8 the NTP default URL is assembled from separate NUL-padded
        # strings: base URL, campaigns ("ntp", "ntp_new_chat_btn") and param
        # names. Only the base URL needs to move to keep the same length.
        b"https://alice.yandex.ru/\x00ntp\x00\x00\x00\x00ntp_new_chat_btn\x00",
        b"https://chatgpt.com/////\x00ntp\x00\x00\x00\x00ntp_new_chat_btn\x00",
        "ntp_topbar_chatgpt_default_url_cluster",
    ),
]

OLD_LABEL = "Найти в Яндексе".encode("utf-8")
LEGACY_PATCHED_LABEL = "Найти в Google        ".encode("utf-8")
PREVIOUS_NEW_LABEL = pad_invisible_label("Найти Google", len(OLD_LABEL))
NEW_LABEL = pad_invisible_label("Найти в Google", len(OLD_LABEL))
INSTASERP_FLAG = "enable-instaserp@5"

ASK_ALICE_LABEL = (
    "\u0421\u043f\u0440\u043e\u0441\u0438\u0442\u044c "
    "\u0410\u043b\u0438\u0441\u0443 AI"
).encode("utf-8")
ASK_ARG_SUFFIX_SPACE = b" $1"
ASK_ARG_SUFFIX_GUILLEMETS = b" \xC2\xAB$1\xC2\xBB"
ASK_ALICE_LABEL_WITH_ARG = ASK_ALICE_LABEL + ASK_ARG_SUFFIX_SPACE
ASK_ALICE_LABEL_WITH_ARG_GUILLEMETS = ASK_ALICE_LABEL + ASK_ARG_SUFFIX_GUILLEMETS
ASK_CHATGPT_VISIBLE_LABEL = (
    "\u0421\u043f\u0440\u043e\u0441\u0438\u0442\u044c ChatGPT"
).encode("utf-8")
ASK_CHATGPT_VISIBLE_LABEL_WITH_ARG = ASK_CHATGPT_VISIBLE_LABEL + ASK_ARG_SUFFIX_SPACE
ASK_CHATGPT_VISIBLE_LABEL_WITH_ARG_GUILLEMETS = (
    ASK_CHATGPT_VISIBLE_LABEL + ASK_ARG_SUFFIX_GUILLEMETS
)
ASK_CHATGPT_FILLER = b"\xE2\x80\x8B" * 2
ASK_CHATGPT_LABEL = ASK_CHATGPT_VISIBLE_LABEL + ASK_CHATGPT_FILLER
ASK_CHATGPT_LABEL_WITH_ARG = ASK_CHATGPT_VISIBLE_LABEL_WITH_ARG + ASK_CHATGPT_FILLER
ASK_CHATGPT_LABEL_WITH_ARG_GUILLEMETS = (
    ASK_CHATGPT_VISIBLE_LABEL_WITH_ARG_GUILLEMETS + ASK_CHATGPT_FILLER
)

# Since 26.8 ru.pak contains the smartbox placeholder "Найти в Яндексе или
# спросить Алису", which also matches OLD_LABEL as a substring. In the
# selection context-menu resource the "Найти в Яндексе" label sits directly
# before "Спросить Алису AI", so the adjacent pair is the only unambiguous
# anchor for the context-menu label.
CONTEXT_JOINT_STOCK = OLD_LABEL + ASK_ALICE_LABEL
CONTEXT_JOINT_PATCHED_LABEL_ONLY = NEW_LABEL + ASK_ALICE_LABEL
CONTEXT_JOINT_PATCHED = NEW_LABEL + ASK_CHATGPT_LABEL

NTP_CACHE_SUBDIR = Path("ntp") / "NativeCacheStorage" / "web_ntp_cache"
NTP_BUNDLE_SIGNATURES = (
    b"WEB_NTP_NEUROTOOLS_ALICE_NEW_CHAT_TITLE:",
    b"WEB_NTP_ALICE_CHATS_SIDEBAR_BUTTON_DESCRIPTION:",
    b"const kl=bn([e=>e.browser.features.ntpNeurotoolsAliceUrl]",
    b"function nn(",
)
NTP_CHATGPT_ORIGIN = "https://chatgpt.com"
NTP_TOPBAR_TITLE_OLD = (
    'WEB_NTP_NEUROTOOLS_ALICE_NEW_CHAT_TITLE:"Чат с Алисой AI"'.encode("utf-8")
)
NTP_TOPBAR_TITLE_NEW = (
    'WEB_NTP_NEUROTOOLS_ALICE_NEW_CHAT_TITLE:"Чат с ChatGPT"'.encode("utf-8")
)
NTP_TOPBAR_DESC_OLD = (
    'WEB_NTP_NEUROTOOLS_ALICE_NEW_CHAT_DESCRIPTION:'
    '"Отвечает на простые и сложные вопросы, рисует картинки"'
).encode("utf-8")
NTP_TOPBAR_DESC_NEW = (
    'WEB_NTP_NEUROTOOLS_ALICE_NEW_CHAT_DESCRIPTION:'
    '"Открывает ChatGPT в новой вкладке"'
).encode("utf-8")
NTP_FALLBACK_TITLE_OLD = (
    'WEB_NTP_NEUROTOOLS_ALICE_TITLE:"Чат с Алисой"'.encode("utf-8")
)
NTP_FALLBACK_TITLE_NEW = (
    'WEB_NTP_NEUROTOOLS_ALICE_TITLE:"Чат с ChatGPT"'.encode("utf-8")
)
NTP_FALLBACK_DESC_OLD = (
    'WEB_NTP_NEUROTOOLS_ALICE_DESCRIPTION:'
    '"Отвечает на простые и\u00a0сложные вопросы, рисует картинки"'
).encode("utf-8")
NTP_FALLBACK_DESC_NEW = (
    'WEB_NTP_NEUROTOOLS_ALICE_DESCRIPTION:'
    '"Открывает ChatGPT в новой вкладке"'
).encode("utf-8")
NTP_ALICE_URL_CONST_OLD = b'const Vs="https://alice.yandex.ru/",zs='
NTP_ALICE_URL_CONST_NEW = b'const Vs="https://chatgpt.com/",zs='
NTP_KL_SELECTOR_OLD = (
    b"const kl=bn([e=>e.browser.features.ntpNeurotoolsAliceUrl],"
    b"(e=>{if(!e)return Vs;return new URL(e).origin}))"
)
NTP_KL_SELECTOR_NEW = (
    b'const kl=bn([e=>e.browser.features.ntpNeurotoolsAliceUrl],'
    b'(e=>"https://chatgpt.com"))'
)
NTP_NEW_CHAT_URL_OLD = (
    b"function nn(e){return`${e}/?utm_campaign=ntp_new_chat_btn&utm_source=desktop_browser`}"
)
NTP_NEW_CHAT_URL_NEW = (
    b'function nn(e){return"https://chatgpt.com/'
    b'?utm_campaign=ntp_new_chat_btn&utm_source=desktop_browser"}'
)
NTP_FALLBACK_HREF_OLD = b"href:a||Vs"
NTP_FALLBACK_HREF_NEW = b"href:Vs"
NTP_TEXT_REPLACEMENTS = (
    (NTP_TOPBAR_TITLE_OLD, NTP_TOPBAR_TITLE_NEW, "ntp_topbar_chatgpt_title"),
    (
        NTP_TOPBAR_DESC_OLD,
        NTP_TOPBAR_DESC_NEW,
        "ntp_topbar_chatgpt_description",
    ),
    (
        NTP_FALLBACK_TITLE_OLD,
        NTP_FALLBACK_TITLE_NEW,
        "ntp_fallback_chatgpt_title",
    ),
    (
        NTP_FALLBACK_DESC_OLD,
        NTP_FALLBACK_DESC_NEW,
        "ntp_fallback_chatgpt_description",
    ),
)
NTP_ROUTE_REPLACEMENTS = (
    (
        NTP_ALICE_URL_CONST_OLD,
        NTP_ALICE_URL_CONST_NEW,
        "ntp_alice_url_fallback",
    ),
    (NTP_KL_SELECTOR_OLD, NTP_KL_SELECTOR_NEW, "ntp_alice_origin_selector"),
    (NTP_NEW_CHAT_URL_OLD, NTP_NEW_CHAT_URL_NEW, "ntp_new_chat_url_builder"),
    (NTP_FALLBACK_HREF_OLD, NTP_FALLBACK_HREF_NEW, "ntp_fallback_href"),
)
NTP_LOCALE_MARKERS = (
    NTP_TOPBAR_TITLE_OLD,
    NTP_TOPBAR_TITLE_NEW,
    NTP_FALLBACK_TITLE_OLD,
    NTP_FALLBACK_TITLE_NEW,
)

ICON_PACK_FILES = ("browser_100_percent.pak", "browser_200_percent.pak")
ICON_RESOURCE_ID = 175
# Since 26.8 the copysearch button icons carry an embedded SVG source instead
# of vector paint commands: entry field 8 wraps {scale, svg_text}.
ICON_SVG_WRAPPER_FIELD = 8
ICON_SVG_DATA_FIELD = 2
ICON_SVG_SCALE_VALUE = 200
ICON_ENTRY_GOOGLE_SOURCE = "search_engine_dialog_google"
ICON_SEARCH_TARGET_ENTRY = "copysearch_search_button_small"
ICON_ASK_TARGET_ENTRY = "copysearch_alice_button_small"
ICON_CLOSE_CMD = 5
ICON_CUBIC_TO_CMD = 6
ICON_LINE_TO_CMD = 8
ICON_MOVE_TO_CMD = 9
ICON_NEW_PATH_CMD = 10
ICON_PATH_COLOR_ARGB_CMD = 26
ICON_CMD_ARG_COUNT = {
    ICON_CLOSE_CMD: 0,
    ICON_CUBIC_TO_CMD: 6,
    ICON_LINE_TO_CMD: 2,
    ICON_MOVE_TO_CMD: 2,
    ICON_NEW_PATH_CMD: 0,
    ICON_PATH_COLOR_ARGB_CMD: 0,
}
ICON_TARGET_INNER_SIZE = 32
ICON_G_MARGIN = 2.0
ICON_LOGO_MARGIN = 2.0
ICON_GEOMETRY_COMMANDS = {
    ICON_CLOSE_CMD,
    ICON_CUBIC_TO_CMD,
    ICON_LINE_TO_CMD,
    ICON_MOVE_TO_CMD,
    ICON_NEW_PATH_CMD,
}
# Derived from https://uxwing.com/openai-icon/ on 2026-03-06.
OPENAI_UXWING_SVG_PATH = (
    "M474.123 209.81c11.525-34.577 7.569-72.423-10.838-103.904-27.696-48.168-"
    "83.433-72.94-137.794-61.414a127.14 127.14 0 00-95.475-42.49c-55.564 "
    "0-104.936 35.781-122.139 88.593-35.781 7.397-66.574 29.76-84.637 61.414-"
    "27.868 48.167-21.503 108.72 15.826 150.007-11.525 34.578-7.569 72.424 "
    "10.838 103.733 27.696 48.34 83.433 73.111 137.966 61.585 24.084 27.18 "
    "58.833 42.835 95.303 42.663 55.564 0 104.936-35.782 122.139-88.594 "
    "35.782-7.397 66.574-29.76 84.465-61.413 28.04-48.168 21.676-108.722-"
    "15.654-150.008v-.172zm-39.567-87.218c11.01 19.267 15.139 41.803 11.354 "
    "63.65-.688-.516-2.064-1.204-2.924-1.72l-101.152-58.49a16.965 16.965 0 "
    "00-16.687 0L206.621 194.5v-50.232l97.883-56.597c45.587-26.32 103.732-"
    "10.666 130.052 34.921zm-227.935 104.42l49.888-28.9 49.887 28.9v57.63"
    "l-49.887 28.9-49.888-28.9v-57.63zm23.223-191.81c22.364 0 43.867 7.742 "
    "61.07 22.02-.688.344-2.064 1.204-3.097 1.72L186.666 117.26c-5.161 "
    "2.925-8.258 8.43-8.258 14.45v136.934l-43.523-25.116V130.333c0-52.64 "
    "42.491-95.13 95.131-95.302l-.172.172zM52.14 168.697c11.182-19.268 "
    "28.557-34.062 49.544-41.803V247.14c0 6.02 3.097 11.354 8.258 14.45"
    "l118.354 68.295-43.695 25.288-97.711-56.425c-45.415-26.32-61.07-84.465-"
    "34.75-130.052zm26.665 220.71c-11.182-19.095-15.139-41.802-11.354-63.65"
    ".688.516 2.064 1.204 2.924 1.72l101.152 58.49a16.965 16.965 0 0016.687 "
    "0l118.354-68.467v50.232l-97.883 56.425c-45.587 26.148-103.732 10.665-"
    "130.052-34.75h.172zm204.54 87.39c-22.192 0-43.867-7.741-60.898-22.02"
    "a62.439 62.439 0 003.097-1.72l101.152-58.317c5.16-2.924 8.429-8.43 "
    "8.257-14.45V243.527l43.523 25.116v113.022c0 52.64-42.663 95.303-95.131 "
    "95.303v-.172zM461.22 343.303c-11.182 19.267-28.729 34.061-49.544 "
    "41.63V264.687c0-6.021-3.097-11.526-8.257-14.45L284.893 181.77l43.523-"
    "25.116 97.883 56.424c45.587 26.32 61.07 84.466 34.75 130.053l.172.172z"
)

NTP_CHAT_WITH_ALICE_AI_LABEL = "Чат с Алисой AI".encode("utf-8")
NTP_CHAT_WITH_CHATGPT_LABEL = "Чат с ChatGPT".encode("utf-8")
NTP_CHAT_WITH_ALICE_AI_LABEL_WITH_ARG = "Чат с Алисой AI $1".encode("utf-8")
NTP_CHAT_WITH_CHATGPT_LABEL_WITH_ARG = "Чат с ChatGPT $1".encode("utf-8")
NTP_CHAT_WITH_ALICE_AI_LABEL_GUILLEMETS = "«Чат с Алисой AI»".encode("utf-8")
NTP_CHAT_WITH_CHATGPT_LABEL_GUILLEMETS = "«Чат с ChatGPT»".encode("utf-8")
NTP_CHAT_WITH_ALICE_LABEL = "Чат с Алисой".encode("utf-8")
NTP_CHAT_WITH_CHATGPT_PLAIN_LABEL = "Чат с ChatGPT".encode("utf-8")
NTP_RU_EXACT_PAYLOAD_REPLACEMENTS = (
    (
        NTP_CHAT_WITH_ALICE_AI_LABEL,
        NTP_CHAT_WITH_CHATGPT_LABEL,
        "ntp_ru_chat_title_ai",
    ),
    (
        NTP_CHAT_WITH_ALICE_AI_LABEL_WITH_ARG,
        NTP_CHAT_WITH_CHATGPT_LABEL_WITH_ARG,
        "ntp_ru_chat_title_ai_with_arg",
    ),
    (
        NTP_CHAT_WITH_ALICE_AI_LABEL_GUILLEMETS,
        NTP_CHAT_WITH_CHATGPT_LABEL_GUILLEMETS,
        "ntp_ru_chat_title_ai_guillemets",
    ),
    (
        NTP_CHAT_WITH_ALICE_LABEL,
        NTP_CHAT_WITH_CHATGPT_PLAIN_LABEL,
        "ntp_ru_chat_title_plain",
    ),
)

NTP_ALICE_LOGO_COMMON_PATH = b"static/media/common/images/alice_logo.svg"
NTP_ALICE_NEW_CHAT_TOOL_PATH = b"static/media/common/images/alice_chats_tool_new_chat.svg"
NTP_TOP_BAR_ALICE_OKNYX_PATH = (
    b"static/media/components/ntp_top_bar/images/alice_oknyx.svg"
)
NTP_TOP_BAR_ALICE_MASK_PATH = b"static/media/components/ntp_top_bar/images/alice.svg"


def build_svg_data_url(path_data: str, fill: str = "#10A37F") -> bytes:
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">'
        f'<path fill="{fill}" d="{path_data}"/>'
        "</svg>"
    )
    return ("data:image/svg+xml," + quote(svg, safe="")).encode("utf-8")


OPENAI_UXWING_SVG_DATA_URL = build_svg_data_url(OPENAI_UXWING_SVG_PATH)
NTP_RESOURCE_ICON_REPLACEMENTS = (
    (
        NTP_ALICE_LOGO_COMMON_PATH,
        OPENAI_UXWING_SVG_DATA_URL,
        "ntp_topbar_alice_logo_mask",
    ),
    (
        NTP_ALICE_NEW_CHAT_TOOL_PATH,
        OPENAI_UXWING_SVG_DATA_URL,
        "ntp_topbar_new_chat_icon",
    ),
    (
        NTP_TOP_BAR_ALICE_OKNYX_PATH,
        OPENAI_UXWING_SVG_DATA_URL,
        "ntp_topbar_alice_oknyx_icon",
    ),
    (
        NTP_TOP_BAR_ALICE_MASK_PATH,
        OPENAI_UXWING_SVG_DATA_URL,
        "ntp_topbar_alice_mask_icon",
    ),
)
WEB_APP_CONFIG_SUBDIR = Path("web_app_config") / "component"
WEB_APP_CONFIG_FILES = ("apps.json", "apps_corp360.json")
WEB_APP_ALICE_ENTRY_KEY = "https://alice.yandex.ru/"
WEB_APP_CHATGPT_ENTRY_KEY = "https://chatgpt.com/"
WEB_APP_CHATGPT_NAME = "Чат с ChatGPT"
WEB_APP_CHATGPT_SCOPE = "https://chatgpt.com/"
WEB_APP_CHATGPT_START_URL = "https://chatgpt.com/?utm_source=yandex_browser_webapp"
WEB_APP_CHATGPT_LAUNCH_URL = (
    "https://chatgpt.com/?from=webapp&utm_source=desktop_browser"
    "&utm_campaign=widget&utm_to=website"
)
WEB_APP_CHATGPT_ALLOWED_SCOPES = ["https://chatgpt.com*"]
WEB_APP_OPENAI_ICON_DATA_URL = OPENAI_UXWING_SVG_DATA_URL.decode("utf-8")

SVG_PATH_TOKEN_RE = re.compile(
    r"[MmLlHhVvCcAaZz]|[-+]?(?:\d*\.\d+|\d+)(?:[eE][-+]?\d+)?"
)


for old, new, name in SEARCH_REPLACEMENTS:
    if len(old) != len(new):
        raise RuntimeError(f"Length mismatch for {name}: {len(old)} != {len(new)}")

if len(OLD_LABEL) != len(NEW_LABEL):
    raise RuntimeError("Length mismatch for label replacement")
if len(LEGACY_PATCHED_LABEL) != len(NEW_LABEL):
    raise RuntimeError("Length mismatch for legacy label replacement")
if len(ASK_ALICE_LABEL) != len(ASK_CHATGPT_LABEL):
    raise RuntimeError("Length mismatch for ask_ai label replacement")
if len(ASK_ALICE_LABEL_WITH_ARG) != len(ASK_CHATGPT_LABEL_WITH_ARG):
    raise RuntimeError("Length mismatch for ask_ai label with arg replacement")
if len(ASK_ALICE_LABEL_WITH_ARG_GUILLEMETS) != len(ASK_CHATGPT_LABEL_WITH_ARG_GUILLEMETS):
    raise RuntimeError("Length mismatch for ask_ai label with guillemets replacement")


def default_yandex_root() -> str:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return str(Path(local_app_data) / "Yandex" / "YandexBrowser")
    return str(Path.home() / "AppData" / "Local" / "Yandex" / "YandexBrowser")


def parse_version_tuple(name: str) -> tuple[int, ...] | None:
    if not re.fullmatch(r"\d+(?:\.\d+)+", name):
        return None
    return tuple(int(part) for part in name.split("."))


def resolve_app_version(application_root: Path, requested: str | None) -> str:
    if requested:
        return requested

    if not application_root.exists():
        raise FileNotFoundError(f"Application folder not found: {application_root}")

    candidates: list[tuple[tuple[int, ...], str]] = []
    for item in application_root.iterdir():
        if not item.is_dir():
            continue
        parsed = parse_version_tuple(item.name)
        if parsed is None:
            continue
        candidates.append((parsed, item.name))

    if not candidates:
        raise FileNotFoundError(
            f"No version folders found in application root: {application_root}"
        )

    candidates.sort(key=lambda x: x[0])
    return candidates[-1][1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Patch Yandex Browser selected-text context action to Google."
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


def patch_unique(data: bytes, old: bytes, new: bytes, key: str) -> tuple[bytes, str]:
    old_count = data.count(old)
    new_count = data.count(new)

    if old_count == 1:
        return data.replace(old, new, 1), f"patched ({key})"
    if old_count == 0 and new_count >= 1:
        return data, f"already patched ({key})"

    raise ValueError(
        f"Unexpected pattern count for {key}: old={old_count}, new={new_count}"
    )


def patch_multi(data: bytes, old: bytes, new: bytes, key: str) -> tuple[bytes, str]:
    old_count = data.count(old)
    new_count = data.count(new)

    if old_count > 0:
        return data.replace(old, new), f"patched ({key}, replaced={old_count})"
    if old_count == 0 and new_count > 0:
        return data, f"already patched ({key})"

    raise ValueError(
        f"Unexpected pattern count for {key}: old={old_count}, new={new_count}"
    )


def find_ntp_bundle_path(app_root: Path) -> Path:
    cache_root = app_root / NTP_CACHE_SUBDIR
    if not cache_root.exists():
        raise FileNotFoundError(f"NTP cache folder not found: {cache_root}")

    matches: list[Path] = []
    for path in cache_root.glob("*_0"):
        try:
            data = path.read_bytes()
        except OSError:
            continue
        if all(signature in data for signature in NTP_BUNDLE_SIGNATURES):
            matches.append(path)

    if not matches:
        raise FileNotFoundError(
            "Could not locate NTP bundle with Alice neurotools signatures"
        )
    if len(matches) > 1:
        raise RuntimeError(
            "Multiple NTP bundles matched Alice neurotools signatures: "
            + ", ".join(str(path) for path in matches)
        )
    return matches[0]


def find_ntp_locale_chunk_paths(app_root: Path) -> list[Path]:
    cache_root = app_root / NTP_CACHE_SUBDIR
    if not cache_root.exists():
        raise FileNotFoundError(f"NTP cache folder not found: {cache_root}")

    matches: list[Path] = []
    for path in cache_root.glob("*_0"):
        try:
            data = path.read_bytes()
        except OSError:
            continue
        if all(signature in data for signature in NTP_BUNDLE_SIGNATURES):
            continue
        if any(marker in data for marker in NTP_LOCALE_MARKERS):
            matches.append(path)

    if not matches:
        raise FileNotFoundError(
            "Could not locate NTP locale chunks with Russian Alice neurotools labels"
        )
    return sorted(matches)


def patch_ntp_bundle(path: Path) -> list[str]:
    data = path.read_bytes()
    logs: list[str] = []

    for old, new, key in (*NTP_TEXT_REPLACEMENTS, *NTP_ROUTE_REPLACEMENTS):
        data, message = patch_unique(data, old, new, key)
        logs.append(message)

    path.write_bytes(data)
    return logs


def patch_ntp_locale_chunk(path: Path) -> list[str]:
    data = path.read_bytes()
    logs: list[str] = []

    for old, new, key in NTP_TEXT_REPLACEMENTS:
        data, message = patch_unique(data, old, new, key)
        logs.append(message)

    path.write_bytes(data)
    return logs


def patch_browser_dll(path: Path) -> list[str]:
    data = path.read_bytes()
    logs: list[str] = []
    for old, new, key in SEARCH_REPLACEMENTS:
        data, msg = patch_unique(data, old, new, key)
        logs.append(msg)
    path.write_bytes(data)
    return logs


def patch_context_menu_label(data: bytes) -> tuple[bytes, str]:
    old_count = data.count(OLD_LABEL)
    legacy_count = data.count(LEGACY_PATCHED_LABEL)
    previous_new_count = data.count(PREVIOUS_NEW_LABEL)
    new_count = data.count(NEW_LABEL)
    joint_stock = data.count(CONTEXT_JOINT_STOCK)
    joint_patched = (
        data.count(CONTEXT_JOINT_PATCHED_LABEL_ONLY) + data.count(CONTEXT_JOINT_PATCHED)
    )

    if joint_stock == 1 and legacy_count == 0 and previous_new_count == 0 and new_count == 0:
        return (
            data.replace(CONTEXT_JOINT_STOCK, CONTEXT_JOINT_PATCHED_LABEL_ONLY, 1),
            "patched (context_menu_label from stock)",
        )
    if (
        joint_stock == 0
        and legacy_count == 0
        and previous_new_count == 0
        and joint_patched >= 1
        and new_count >= 1
    ):
        return data, "already patched (context_menu_label)"
    if old_count == 1 and legacy_count == 0 and previous_new_count == 0 and new_count == 0 and joint_stock == 0:
        return data.replace(OLD_LABEL, NEW_LABEL, 1), "patched (context_menu_label from stock, unique label)"
    if old_count == 0 and legacy_count >= 1 and previous_new_count == 0 and new_count == 0:
        return data.replace(LEGACY_PATCHED_LABEL, NEW_LABEL, 1), "patched (context_menu_label migrated from legacy padded label)"
    if old_count == 0 and legacy_count == 0 and previous_new_count >= 1 and new_count == 0:
        return data.replace(PREVIOUS_NEW_LABEL, NEW_LABEL, 1), "patched (context_menu_label migrated from previous patched label)"

    raise ValueError(
        "Unexpected pattern counts for context_menu_label: "
        f"old={old_count}, legacy={legacy_count}, previous={previous_new_count}, "
        f"new={new_count}, joint_stock={joint_stock}, joint_patched={joint_patched}"
    )


def patch_ru_pak(path: Path) -> list[str]:
    data = path.read_bytes()
    logs: list[str] = []

    label_data, label_msg = patch_context_menu_label(data)
    data = label_data
    logs.append(label_msg)

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
    logs.extend(patch_datapack_exact_payloads(path, NTP_RU_EXACT_PAYLOAD_REPLACEMENTS))
    return logs


def ensure_instaserp(local_state_path: Path) -> str:
    payload = json.loads(local_state_path.read_text(encoding="utf-8"))
    browser = payload.setdefault("browser", {})
    enabled = browser.get("enabled_labs_experiments")

    if not isinstance(enabled, list):
        enabled = []

    if INSTASERP_FLAG not in enabled:
        enabled.append(INSTASERP_FLAG)
        status = "patched (instaserp flag added)"
    else:
        status = "already patched (instaserp flag already present)"

    browser["enabled_labs_experiments"] = enabled
    local_state_path.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    return status


def build_web_app_openai_icons() -> list[dict[str, str]]:
    icons: list[dict[str, str]] = []
    for size in ("256x256", "32x32", "48x48"):
        icons.append(
            {
                "sizes": size,
                "src": WEB_APP_OPENAI_ICON_DATA_URL,
                "type": "image/svg+xml",
            }
        )
    return icons


def normalize_web_app_entry_key(apps_list: dict[str, object]) -> tuple[dict[str, object], bool]:
    chatgpt_entry = apps_list.get(WEB_APP_CHATGPT_ENTRY_KEY)
    if isinstance(chatgpt_entry, dict):
        if WEB_APP_ALICE_ENTRY_KEY in apps_list:
            del apps_list[WEB_APP_ALICE_ENTRY_KEY]
            return chatgpt_entry, True
        return chatgpt_entry, False

    alice_entry = apps_list.get(WEB_APP_ALICE_ENTRY_KEY)
    if not isinstance(alice_entry, dict):
        raise ValueError("Alice/ChatGPT web app entry not found")

    reordered: dict[str, object] = {}
    for key, value in list(apps_list.items()):
        if key == WEB_APP_ALICE_ENTRY_KEY:
            reordered[WEB_APP_CHATGPT_ENTRY_KEY] = value
        else:
            reordered[key] = value

    apps_list.clear()
    apps_list.update(reordered)

    chatgpt_entry = apps_list.get(WEB_APP_CHATGPT_ENTRY_KEY)
    if not isinstance(chatgpt_entry, dict):
        raise ValueError("Failed to normalize ChatGPT web app entry key")
    return chatgpt_entry, True


def patch_web_app_config(path: Path) -> str:
    payload = json.loads(path.read_text(encoding="utf-8"))
    apps_list = payload.get("apps_list")
    if not isinstance(apps_list, dict):
        raise ValueError(f"apps_list not found in {path}")

    updated: list[str] = []
    web_app_entry, key_updated = normalize_web_app_entry_key(apps_list)
    if key_updated:
        updated.append("entry_key")

    manifest = web_app_entry.get("manifest")
    if not isinstance(manifest, dict):
        raise ValueError(f"manifest not found for ChatGPT web app in {path}")

    if manifest.get("name") != WEB_APP_CHATGPT_NAME:
        manifest["name"] = WEB_APP_CHATGPT_NAME
        updated.append("name")

    expected_icons = build_web_app_openai_icons()
    if manifest.get("icons") != expected_icons:
        manifest["icons"] = expected_icons
        updated.append("icons")

    if manifest.get("scope") != WEB_APP_CHATGPT_SCOPE:
        manifest["scope"] = WEB_APP_CHATGPT_SCOPE
        updated.append("scope")

    if manifest.get("start_url") != WEB_APP_CHATGPT_START_URL:
        manifest["start_url"] = WEB_APP_CHATGPT_START_URL
        updated.append("start_url")

    if web_app_entry.get("yandex.launch_url") != WEB_APP_CHATGPT_LAUNCH_URL:
        web_app_entry["yandex.launch_url"] = WEB_APP_CHATGPT_LAUNCH_URL
        updated.append("launch_url")

    if web_app_entry.get("allowed_scopes") != WEB_APP_CHATGPT_ALLOWED_SCOPES:
        web_app_entry["allowed_scopes"] = list(WEB_APP_CHATGPT_ALLOWED_SCOPES)
        updated.append("allowed_scopes")

    if not updated:
        return "already patched (web_app_config ChatGPT entry + OpenAI icon)"

    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return "patched (web_app_config ChatGPT entry -> " + ", ".join(updated) + ")"


def patch_web_app_configs(app_root: Path) -> list[str]:
    logs: list[str] = []
    component_dir = app_root / WEB_APP_CONFIG_SUBDIR
    for file_name in WEB_APP_CONFIG_FILES:
        config_path = component_dir / file_name
        logs.append(f"{file_name}: {patch_web_app_config(config_path)}")
    return logs


def read_varint(data: bytes, pos: int) -> tuple[int, int]:
    value = 0
    shift = 0
    while True:
        if pos >= len(data):
            raise ValueError("Unexpected end of buffer while reading varint")
        byte = data[pos]
        pos += 1
        value |= (byte & 0x7F) << shift
        if not (byte & 0x80):
            return value, pos
        shift += 7
        if shift > 63:
            raise ValueError("Varint is too long")


def write_varint(value: int) -> bytes:
    if value < 0:
        raise ValueError("Negative varint values are not supported")
    out = bytearray()
    while True:
        chunk = value & 0x7F
        value >>= 7
        if value:
            out.append(chunk | 0x80)
        else:
            out.append(chunk)
            return bytes(out)


def parse_proto_fields(data: bytes) -> list[list[object]]:
    pos = 0
    fields: list[list[object]] = []
    while pos < len(data):
        tag, pos = read_varint(data, pos)
        field_number = tag >> 3
        wire_type = tag & 0x07

        if wire_type == 0:
            value, pos = read_varint(data, pos)
            fields.append([field_number, wire_type, value])
        elif wire_type == 1:
            if pos + 8 > len(data):
                raise ValueError("Unexpected end for fixed64 field")
            value = data[pos : pos + 8]
            pos += 8
            fields.append([field_number, wire_type, value])
        elif wire_type == 2:
            length, pos = read_varint(data, pos)
            if pos + length > len(data):
                raise ValueError("Unexpected end for length-delimited field")
            value = data[pos : pos + length]
            pos += length
            fields.append([field_number, wire_type, value])
        elif wire_type == 5:
            if pos + 4 > len(data):
                raise ValueError("Unexpected end for fixed32 field")
            value = data[pos : pos + 4]
            pos += 4
            fields.append([field_number, wire_type, value])
        else:
            raise ValueError(f"Unsupported protobuf wire type: {wire_type}")
    return fields


def encode_proto_fields(fields: list[list[object]]) -> bytes:
    out = bytearray()
    for field_number, wire_type, value in fields:
        out.extend(write_varint((int(field_number) << 3) | int(wire_type)))
        if wire_type == 0:
            out.extend(write_varint(int(value)))
        elif wire_type == 1:
            value_bytes = bytes(value)
            if len(value_bytes) != 8:
                raise ValueError("fixed64 field must be exactly 8 bytes")
            out.extend(value_bytes)
        elif wire_type == 2:
            value_bytes = bytes(value)
            out.extend(write_varint(len(value_bytes)))
            out.extend(value_bytes)
        elif wire_type == 5:
            value_bytes = bytes(value)
            if len(value_bytes) != 4:
                raise ValueError("fixed32 field must be exactly 4 bytes")
            out.extend(value_bytes)
        else:
            raise ValueError(f"Unsupported protobuf wire type: {wire_type}")
    return bytes(out)


def parse_datapack(path: Path) -> tuple[int, int, list[tuple[int, int]], list[list[object]]]:
    data = path.read_bytes()
    version = struct.unpack_from("<I", data, 0)[0]
    encoding = data[4]
    resource_count, alias_count = struct.unpack_from("<HH", data, 8)

    pos = 12
    entries: list[tuple[int, int]] = []
    for _ in range(resource_count + 1):
        resource_id, offset = struct.unpack_from("<HI", data, pos)
        entries.append((resource_id, offset))
        pos += 6

    aliases: list[tuple[int, int]] = []
    for _ in range(alias_count):
        resource_id, index = struct.unpack_from("<HH", data, pos)
        aliases.append((resource_id, index))
        pos += 4

    resources: list[list[object]] = []
    for idx in range(resource_count):
        resource_id, start = entries[idx]
        end = entries[idx + 1][1]
        if not (0 <= start <= end <= len(data)):
            raise ValueError(f"Invalid resource range in DataPack: id={resource_id}")
        resources.append([resource_id, data[start:end]])

    return version, encoding, aliases, resources


def build_datapack(
    version: int,
    encoding: int,
    aliases: list[tuple[int, int]],
    resources: list[list[object]],
) -> bytes:
    resource_count = len(resources)
    alias_count = len(aliases)

    header = bytearray()
    header.extend(struct.pack("<I", version))
    header.extend(bytes([encoding, 0, 0, 0]))
    header.extend(struct.pack("<HH", resource_count, alias_count))

    data_start = 12 + (resource_count + 1) * 6 + alias_count * 4

    entries_bytes = bytearray()
    payload_bytes = bytearray()
    offset = data_start

    for resource_id, payload in resources:
        payload_data = bytes(payload)
        entries_bytes.extend(struct.pack("<HI", int(resource_id), offset))
        offset += len(payload_data)
        payload_bytes.extend(payload_data)

    entries_bytes.extend(struct.pack("<HI", 0, offset))

    alias_bytes = bytearray()
    for resource_id, index in aliases:
        alias_bytes.extend(struct.pack("<HH", resource_id, index))

    return bytes(header + entries_bytes + alias_bytes + payload_bytes)


def patch_datapack_exact_payloads(
    path: Path,
    replacements: tuple[tuple[bytes, bytes, str], ...],
) -> list[str]:
    version, encoding, aliases, resources = parse_datapack(path)
    logs: list[str] = []
    changed = False

    for old_payload, new_payload, key in replacements:
        old_indexes: list[int] = []
        new_count = 0

        for index, (_resource_id, payload) in enumerate(resources):
            payload_bytes = bytes(payload)
            if payload_bytes == old_payload:
                old_indexes.append(index)
            elif payload_bytes == new_payload:
                new_count += 1

        if old_indexes:
            for index in old_indexes:
                resources[index][1] = new_payload
            changed = True
            logs.append(f"patched ({key}, replaced={len(old_indexes)})")
            continue

        if new_count > 0:
            logs.append(f"already patched ({key})")
            continue

        raise ValueError(f"Could not find payload for {key} in {path}")

    if changed:
        path.write_bytes(build_datapack(version, encoding, aliases, resources))

    return logs


def patch_datapack_substrings(
    path: Path,
    replacements: tuple[tuple[bytes, bytes, str], ...],
) -> list[str]:
    version, encoding, aliases, resources = parse_datapack(path)
    logs: list[str] = []
    changed = False

    for old, new, key in replacements:
        old_count = 0
        new_count = 0

        for _resource_id, payload in resources:
            payload_bytes = bytes(payload)
            old_count += payload_bytes.count(old)
            new_count += payload_bytes.count(new)

        if old_count > 0:
            for resource in resources:
                payload_bytes = bytes(resource[1])
                if old in payload_bytes:
                    resource[1] = payload_bytes.replace(old, new)
            changed = True
            logs.append(f"patched ({key}, replaced={old_count})")
            continue

        if new_count > 0:
            logs.append(f"already patched ({key})")
            continue

        raise ValueError(f"Could not find pattern for {key} in {path}")

    if changed:
        path.write_bytes(build_datapack(version, encoding, aliases, resources))

    return logs


def get_icon_entry_details(payload: bytes) -> tuple[str | None, list[list[object]], int | None]:
    fields = parse_proto_fields(payload)
    name: str | None = None
    path_field_index: int | None = None

    for index, (field_number, wire_type, value) in enumerate(fields):
        if field_number == 1 and wire_type == 2:
            try:
                name = bytes(value).decode("utf-8")
            except UnicodeDecodeError:
                name = None
        elif field_number == 5 and wire_type == 2 and path_field_index is None:
            path_field_index = index

    return name, fields, path_field_index


def unpack_float32_array(data: bytes) -> list[float]:
    if len(data) % 4 != 0:
        raise ValueError("Icon float argument buffer is not 4-byte aligned")
    count = len(data) // 4
    if count == 0:
        return []
    return list(struct.unpack(f"<{count}f", data))


def pack_float32_array(values: list[float]) -> bytes:
    if not values:
        return b""
    return struct.pack(f"<{len(values)}f", *values)


def extract_icon_payload_indexes(
    payload_fields: list[list[object]],
) -> tuple[int, int, int, int]:
    width_index: int | None = None
    height_index: int | None = None
    style_index: int | None = None
    args_index: int | None = None

    for index, (field_number, wire_type, _value) in enumerate(payload_fields):
        if field_number == 2 and wire_type == 0 and width_index is None:
            width_index = index
        elif field_number == 3 and wire_type == 0 and height_index is None:
            height_index = index
        elif field_number == 5 and wire_type == 2 and style_index is None:
            style_index = index
        elif field_number == 6 and wire_type == 2 and args_index is None:
            args_index = index

    if (
        width_index is None
        or height_index is None
        or style_index is None
        or args_index is None
    ):
        raise ValueError("Could not parse icon payload structure")

    return width_index, height_index, style_index, args_index


def extract_icon_paint_commands(style_commands: list[int]) -> list[int]:
    paint_commands: list[int] = []
    for command in style_commands:
        if command in ICON_GEOMETRY_COMMANDS:
            break
        if command not in ICON_CMD_ARG_COUNT:
            raise ValueError(f"Unsupported paint command in icon payload: {command}")
        paint_commands.append(command)

    if not paint_commands:
        raise ValueError("Could not extract icon paint commands from template payload")

    return paint_commands


def vector_angle(ux: float, uy: float, vx: float, vy: float) -> float:
    return math.atan2((ux * vy) - (uy * vx), (ux * vx) + (uy * vy))


def transform_arc_point(
    cx: float,
    cy: float,
    rx: float,
    ry: float,
    cos_phi: float,
    sin_phi: float,
    x: float,
    y: float,
) -> tuple[float, float]:
    return (
        cx + (rx * cos_phi * x) - (ry * sin_phi * y),
        cy + (rx * sin_phi * x) + (ry * cos_phi * y),
    )


def consume_svg_arc_parameters(
    tokens: list[str],
    pos: int,
) -> tuple[float, float, float, int, int, float, float, int]:
    if pos + 3 >= len(tokens):
        raise ValueError("SVG arc command is missing flag parameters")

    rx = float(tokens[pos])
    ry = float(tokens[pos + 1])
    rotation = float(tokens[pos + 2])
    cursor = pos + 3

    large_arc_token = tokens[cursor]
    if large_arc_token[0] not in {"0", "1"}:
        raise ValueError(f"Invalid SVG large-arc flag token: {large_arc_token}")

    if large_arc_token in {"0", "1"}:
        large_arc_flag = int(large_arc_token)
        cursor += 1
        if cursor >= len(tokens):
            raise ValueError("SVG arc command is missing sweep flag")
        sweep_token = tokens[cursor]
        if sweep_token[0] not in {"0", "1"}:
            raise ValueError(f"Invalid SVG sweep flag token: {sweep_token}")

        if sweep_token in {"0", "1"}:
            sweep_flag = int(sweep_token)
            cursor += 1
            if cursor + 1 >= len(tokens):
                raise ValueError("SVG arc command is missing destination coordinates")
            x = float(tokens[cursor])
            y = float(tokens[cursor + 1])
            cursor += 2
            return rx, ry, rotation, large_arc_flag, sweep_flag, x, y, cursor

        sweep_flag = int(sweep_token[0])
        x = float(sweep_token[1:])
        if cursor + 1 >= len(tokens):
            raise ValueError("SVG arc command is missing destination Y coordinate")
        y = float(tokens[cursor + 1])
        cursor += 2
        return rx, ry, rotation, large_arc_flag, sweep_flag, x, y, cursor

    large_arc_flag = int(large_arc_token[0])
    sweep_flag = int(large_arc_token[1])
    remainder = large_arc_token[2:]
    cursor += 1
    if remainder:
        if cursor >= len(tokens):
            raise ValueError("SVG arc command is missing destination Y coordinate")
        x = float(remainder)
        y = float(tokens[cursor])
        cursor += 1
        return rx, ry, rotation, large_arc_flag, sweep_flag, x, y, cursor

    if cursor + 1 >= len(tokens):
        raise ValueError("SVG arc command is missing destination coordinates")
    x = float(tokens[cursor])
    y = float(tokens[cursor + 1])
    cursor += 2
    return rx, ry, rotation, large_arc_flag, sweep_flag, x, y, cursor


def arc_to_cubic_segments(
    x1: float,
    y1: float,
    rx: float,
    ry: float,
    rotation_degrees: float,
    large_arc_flag: int,
    sweep_flag: int,
    x2: float,
    y2: float,
) -> list[tuple[float, float, float, float, float, float]]:
    rx = abs(rx)
    ry = abs(ry)
    if rx == 0.0 or ry == 0.0 or (x1 == x2 and y1 == y2):
        return []

    phi = math.radians(rotation_degrees % 360.0)
    cos_phi = math.cos(phi)
    sin_phi = math.sin(phi)

    dx2 = (x1 - x2) / 2.0
    dy2 = (y1 - y2) / 2.0
    x1p = (cos_phi * dx2) + (sin_phi * dy2)
    y1p = (-sin_phi * dx2) + (cos_phi * dy2)

    rx_sq = rx * rx
    ry_sq = ry * ry
    x1p_sq = x1p * x1p
    y1p_sq = y1p * y1p

    radii_scale = (x1p_sq / rx_sq) + (y1p_sq / ry_sq)
    if radii_scale > 1.0:
        scale = math.sqrt(radii_scale)
        rx *= scale
        ry *= scale
        rx_sq = rx * rx
        ry_sq = ry * ry

    denominator = (rx_sq * y1p_sq) + (ry_sq * x1p_sq)
    if denominator == 0.0:
        return []

    sign = -1.0 if large_arc_flag == sweep_flag else 1.0
    center_scale = max(
        0.0,
        ((rx_sq * ry_sq) - (rx_sq * y1p_sq) - (ry_sq * x1p_sq)) / denominator,
    )
    coef = sign * math.sqrt(center_scale)
    cxp = coef * ((rx * y1p) / ry)
    cyp = coef * (-(ry * x1p) / rx)

    cx = (cos_phi * cxp) - (sin_phi * cyp) + ((x1 + x2) / 2.0)
    cy = (sin_phi * cxp) + (cos_phi * cyp) + ((y1 + y2) / 2.0)

    ux = (x1p - cxp) / rx
    uy = (y1p - cyp) / ry
    vx = (-x1p - cxp) / rx
    vy = (-y1p - cyp) / ry

    theta1 = vector_angle(1.0, 0.0, ux, uy)
    delta_theta = vector_angle(ux, uy, vx, vy)
    if sweep_flag == 0 and delta_theta > 0.0:
        delta_theta -= 2.0 * math.pi
    elif sweep_flag == 1 and delta_theta < 0.0:
        delta_theta += 2.0 * math.pi

    segment_count = max(1, int(math.ceil(abs(delta_theta) / (math.pi / 2.0))))
    segment_theta = delta_theta / float(segment_count)

    curves: list[tuple[float, float, float, float, float, float]] = []
    for segment_index in range(segment_count):
        start_theta = theta1 + (segment_index * segment_theta)
        end_theta = start_theta + segment_theta
        alpha = (4.0 / 3.0) * math.tan((end_theta - start_theta) / 4.0)

        cos_start = math.cos(start_theta)
        sin_start = math.sin(start_theta)
        cos_end = math.cos(end_theta)
        sin_end = math.sin(end_theta)

        cp1 = (
            cos_start - (alpha * sin_start),
            sin_start + (alpha * cos_start),
        )
        cp2 = (
            cos_end + (alpha * sin_end),
            sin_end - (alpha * cos_end),
        )
        end = (cos_end, sin_end)

        cp1x, cp1y = transform_arc_point(
            cx, cy, rx, ry, cos_phi, sin_phi, cp1[0], cp1[1]
        )
        cp2x, cp2y = transform_arc_point(
            cx, cy, rx, ry, cos_phi, sin_phi, cp2[0], cp2[1]
        )
        endx, endy = transform_arc_point(
            cx, cy, rx, ry, cos_phi, sin_phi, end[0], end[1]
        )
        curves.append((cp1x, cp1y, cp2x, cp2y, endx, endy))

    return curves


def parse_svg_path_subpaths(path_data: str) -> list[tuple[list[int], list[float]]]:
    tokens = SVG_PATH_TOKEN_RE.findall(path_data)
    if not tokens:
        raise ValueError("SVG path data is empty")

    subpaths: list[tuple[list[int], list[float]]] = []
    pos = 0
    current_command: str | None = None
    current_x = 0.0
    current_y = 0.0
    start_x = 0.0
    start_y = 0.0
    active_commands: list[int] | None = None
    active_args: list[float] | None = None

    def is_command(token: str) -> bool:
        return len(token) == 1 and token.isalpha()

    def ensure_subpath() -> tuple[list[int], list[float]]:
        if active_commands is None or active_args is None:
            raise ValueError("SVG path starts drawing before first move command")
        return active_commands, active_args

    def begin_subpath(x: float, y: float) -> None:
        nonlocal active_commands, active_args, current_x, current_y, start_x, start_y
        active_commands = [ICON_MOVE_TO_CMD]
        active_args = [x, y]
        subpaths.append((active_commands, active_args))
        current_x = x
        current_y = y
        start_x = x
        start_y = y

    while pos < len(tokens):
        token = tokens[pos]
        if is_command(token):
            current_command = token
            pos += 1
        elif current_command is None:
            raise ValueError(f"Unexpected SVG path token without command: {token}")

        if current_command is None:
            continue

        absolute = current_command.isupper()
        command_key = current_command.upper()

        if command_key == "M":
            if pos + 1 >= len(tokens):
                raise ValueError("SVG move command is missing coordinates")
            x = float(tokens[pos])
            y = float(tokens[pos + 1])
            pos += 2
            if not absolute:
                x += current_x
                y += current_y
            begin_subpath(x, y)
            line_absolute = absolute
            while pos < len(tokens) and not is_command(tokens[pos]):
                if pos + 1 >= len(tokens):
                    raise ValueError("SVG move command has incomplete trailing pair")
                x = float(tokens[pos])
                y = float(tokens[pos + 1])
                pos += 2
                if not line_absolute:
                    x += current_x
                    y += current_y
                commands, args = ensure_subpath()
                commands.append(ICON_LINE_TO_CMD)
                args.extend([x, y])
                current_x = x
                current_y = y
            current_command = "L" if absolute else "l"
            continue

        if command_key == "L":
            commands, args = ensure_subpath()
            while pos < len(tokens) and not is_command(tokens[pos]):
                if pos + 1 >= len(tokens):
                    raise ValueError("SVG line command is missing coordinates")
                x = float(tokens[pos])
                y = float(tokens[pos + 1])
                pos += 2
                if not absolute:
                    x += current_x
                    y += current_y
                commands.append(ICON_LINE_TO_CMD)
                args.extend([x, y])
                current_x = x
                current_y = y
            continue

        if command_key == "H":
            commands, args = ensure_subpath()
            while pos < len(tokens) and not is_command(tokens[pos]):
                x = float(tokens[pos])
                pos += 1
                if not absolute:
                    x += current_x
                commands.append(ICON_LINE_TO_CMD)
                args.extend([x, current_y])
                current_x = x
            continue

        if command_key == "V":
            commands, args = ensure_subpath()
            while pos < len(tokens) and not is_command(tokens[pos]):
                y = float(tokens[pos])
                pos += 1
                if not absolute:
                    y += current_y
                commands.append(ICON_LINE_TO_CMD)
                args.extend([current_x, y])
                current_y = y
            continue

        if command_key == "C":
            commands, args = ensure_subpath()
            while pos < len(tokens) and not is_command(tokens[pos]):
                if pos + 5 >= len(tokens):
                    raise ValueError("SVG cubic command is missing coordinates")
                x1 = float(tokens[pos])
                y1 = float(tokens[pos + 1])
                x2 = float(tokens[pos + 2])
                y2 = float(tokens[pos + 3])
                x = float(tokens[pos + 4])
                y = float(tokens[pos + 5])
                pos += 6
                if not absolute:
                    x1 += current_x
                    y1 += current_y
                    x2 += current_x
                    y2 += current_y
                    x += current_x
                    y += current_y
                commands.append(ICON_CUBIC_TO_CMD)
                args.extend([x1, y1, x2, y2, x, y])
                current_x = x
                current_y = y
            continue

        if command_key == "A":
            commands, args = ensure_subpath()
            while pos < len(tokens) and not is_command(tokens[pos]):
                (
                    rx,
                    ry,
                    rotation,
                    large_arc_flag,
                    sweep_flag,
                    x,
                    y,
                    pos,
                ) = consume_svg_arc_parameters(tokens, pos)
                if not absolute:
                    x += current_x
                    y += current_y

                if rx == 0.0 or ry == 0.0:
                    commands.append(ICON_LINE_TO_CMD)
                    args.extend([x, y])
                    current_x = x
                    current_y = y
                    continue

                curves = arc_to_cubic_segments(
                    current_x,
                    current_y,
                    rx,
                    ry,
                    rotation,
                    large_arc_flag,
                    sweep_flag,
                    x,
                    y,
                )
                if not curves:
                    current_x = x
                    current_y = y
                    continue

                for cp1x, cp1y, cp2x, cp2y, endx, endy in curves:
                    commands.append(ICON_CUBIC_TO_CMD)
                    args.extend([cp1x, cp1y, cp2x, cp2y, endx, endy])
                    current_x = endx
                    current_y = endy
            continue

        if command_key == "Z":
            commands, _args = ensure_subpath()
            if not commands or commands[-1] != ICON_CLOSE_CMD:
                commands.append(ICON_CLOSE_CMD)
            current_x = start_x
            current_y = start_y
            current_command = None
            continue

        raise ValueError(f"Unsupported SVG path command: {current_command}")

    return subpaths


def normalize_icon_subpaths(
    subpaths: list[tuple[list[int], list[float]]],
) -> list[tuple[list[int], list[float]]]:
    all_args = [value for _commands, args in subpaths for value in args]
    if len(all_args) < 2:
        raise ValueError("Icon geometry does not contain enough coordinates")

    xs = all_args[0::2]
    ys = all_args[1::2]
    min_x = min(xs)
    max_x = max(xs)
    min_y = min(ys)
    max_y = max(ys)
    span_x = max(max_x - min_x, 1e-6)
    span_y = max(max_y - min_y, 1e-6)

    drawable_size = float(ICON_TARGET_INNER_SIZE) - (ICON_LOGO_MARGIN * 2.0)
    if drawable_size <= 0.0:
        raise ValueError("Invalid icon target size/margin configuration")

    scale = min(drawable_size / span_x, drawable_size / span_y)
    offset_x = ICON_LOGO_MARGIN + ((drawable_size - (span_x * scale)) / 2.0)
    offset_y = ICON_LOGO_MARGIN + ((drawable_size - (span_y * scale)) / 2.0)

    normalized: list[tuple[list[int], list[float]]] = []
    for commands, args in subpaths:
        transformed_args: list[float] = []
        for index, value in enumerate(args):
            if index % 2 == 0:
                transformed_args.append((value - min_x) * scale + offset_x)
            else:
                transformed_args.append((value - min_y) * scale + offset_y)
        normalized.append((list(commands), transformed_args))

    return normalized


def google_g_transformed_commands(source_payload: bytes) -> tuple[list[int], list[float]]:
    source_fields = parse_proto_fields(source_payload)
    _width_index, _height_index, style_index, args_index = extract_icon_payload_indexes(
        source_fields
    )

    source_commands = list(bytes(source_fields[style_index][2]))
    if not source_commands:
        raise ValueError("Source Google icon has empty command stream")

    if ICON_NEW_PATH_CMD in source_commands:
        first_path_commands = source_commands[: source_commands.index(ICON_NEW_PATH_CMD)]
    else:
        first_path_commands = source_commands

    if not first_path_commands:
        raise ValueError("Could not isolate first Google path command stream")

    required_float_count = 0
    for command in first_path_commands:
        arg_count = ICON_CMD_ARG_COUNT.get(command)
        if arg_count is None:
            raise ValueError(f"Unsupported icon command in source payload: {command}")
        required_float_count += arg_count

    source_args = unpack_float32_array(bytes(source_fields[args_index][2]))
    if len(source_args) < required_float_count:
        raise ValueError(
            "Source Google icon argument stream is shorter than command requirements"
        )
    if required_float_count % 2 != 0:
        raise ValueError("Source Google icon command stream has odd float requirement")

    selected_args = source_args[:required_float_count]
    xs = selected_args[0::2]
    ys = selected_args[1::2]
    if not xs or not ys:
        raise ValueError("Source Google icon does not contain coordinate pairs")

    min_x = min(xs)
    max_x = max(xs)
    min_y = min(ys)
    max_y = max(ys)
    span_x = max(max_x - min_x, 1e-6)
    span_y = max(max_y - min_y, 1e-6)

    drawable_size = float(ICON_TARGET_INNER_SIZE) - (ICON_G_MARGIN * 2.0)
    if drawable_size <= 0.0:
        raise ValueError("Invalid icon target size/margin configuration")
    scale = min(drawable_size / span_x, drawable_size / span_y)

    transformed_args: list[float] = []
    for idx, value in enumerate(selected_args):
        if idx % 2 == 0:
            transformed_args.append((value - min_x) * scale + ICON_G_MARGIN)
        else:
            transformed_args.append((value - min_y) * scale + ICON_G_MARGIN)

    return first_path_commands, transformed_args


def build_google_g_icon_payload(source_payload: bytes) -> bytes:
    source_fields = parse_proto_fields(source_payload)
    width_index, height_index, style_index, args_index = extract_icon_payload_indexes(
        source_fields
    )
    commands, transformed_args = google_g_transformed_commands(source_payload)

    source_fields[width_index][2] = ICON_TARGET_INNER_SIZE
    source_fields[height_index][2] = ICON_TARGET_INNER_SIZE
    source_fields[style_index][2] = bytes(commands)
    source_fields[args_index][2] = pack_float32_array(transformed_args)
    return encode_proto_fields(source_fields)


def icon_commands_to_svg_path_data(commands: list[int], args: list[float]) -> str:
    def fmt(value: float) -> str:
        text = f"{value:.3f}".rstrip("0").rstrip(".")
        return text if text else "0"

    parts: list[str] = []
    arg_pos = 0
    for command in commands:
        arg_count = ICON_CMD_ARG_COUNT.get(command)
        if arg_count is None:
            raise ValueError(f"Unsupported icon command in SVG export: {command}")
        if command not in ICON_GEOMETRY_COMMANDS:
            # Leading paint commands (e.g. PATH_COLOR_ARGB) have no SVG
            # equivalent; the target entries use currentColor anyway.
            if arg_count == 0:
                continue
            raise ValueError(f"Unsupported paint command in SVG export: {command}")
        command_args = args[arg_pos : arg_pos + arg_count]
        arg_pos += arg_count
        if command == ICON_CLOSE_CMD:
            parts.append("Z")
        elif command == ICON_MOVE_TO_CMD:
            parts.append(f"M {fmt(command_args[0])} {fmt(command_args[1])}")
        elif command == ICON_LINE_TO_CMD:
            parts.append(f"L {fmt(command_args[0])} {fmt(command_args[1])}")
        elif command == ICON_CUBIC_TO_CMD:
            parts.append("C " + " ".join(fmt(value) for value in command_args))
        else:
            raise ValueError(f"Unsupported icon command in SVG export: {command}")
    return " ".join(parts)


def build_google_g_svg_text(source_payload: bytes) -> bytes:
    commands, args = google_g_transformed_commands(source_payload)
    path_data = icon_commands_to_svg_path_data(commands, args)
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32">'
        f'<path fill="currentColor" d="{path_data}"/></svg>'
    )
    return svg.encode("utf-8")


def build_openai_svg_text() -> bytes:
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" '
        'viewBox="0 0 512 512">'
        f'<path fill="currentColor" d="{OPENAI_UXWING_SVG_PATH}"/></svg>'
    )
    return svg.encode("utf-8")


def get_icon_entry_svg(entry_fields: list[list[object]]) -> bytes | None:
    for field_number, wire_type, value in entry_fields:
        if field_number != ICON_SVG_WRAPPER_FIELD or wire_type != 2:
            continue
        for inner_number, inner_wire_type, inner_value in parse_proto_fields(bytes(value)):
            if inner_number == ICON_SVG_DATA_FIELD and inner_wire_type == 2:
                return bytes(inner_value)
    return None


def set_icon_entry_svg(
    entry_fields: list[list[object]],
    svg_text: bytes,
) -> list[list[object]]:
    result: list[list[object]] = []
    replaced = False
    for field in entry_fields:
        field_number, wire_type, value = int(field[0]), int(field[1]), field[2]
        if (
            field_number == ICON_SVG_WRAPPER_FIELD
            and wire_type == 2
            and not replaced
        ):
            new_inner: list[list[object]] = []
            for inner_number, inner_wire_type, inner_value in parse_proto_fields(
                bytes(value)
            ):
                if inner_number == ICON_SVG_DATA_FIELD and inner_wire_type == 2:
                    new_inner.append([inner_number, inner_wire_type, svg_text])
                    replaced = True
                else:
                    new_inner.append([inner_number, inner_wire_type, inner_value])
            if replaced:
                result.append([field_number, wire_type, encode_proto_fields(new_inner)])
                continue
        result.append([field_number, wire_type, value])
    if not replaced:
        raise ValueError("Icon entry has no embedded SVG wrapper field")
    return result


def build_custom_svg_icon_payload(template_payload: bytes, svg_path_data: str) -> bytes:
    payload_fields = parse_proto_fields(template_payload)
    width_index, height_index, style_index, args_index = extract_icon_payload_indexes(
        payload_fields
    )
    paint_commands = extract_icon_paint_commands(list(bytes(payload_fields[style_index][2])))
    normalized_subpaths = normalize_icon_subpaths(parse_svg_path_subpaths(svg_path_data))

    # Keep all contours inside one path so the OpenAI mark retains its inner cutouts.
    style_commands: list[int] = list(paint_commands)
    style_args: list[float] = []
    for commands, args in normalized_subpaths:
        style_commands.extend(commands)
        style_args.extend(args)

    payload_fields[width_index][2] = ICON_TARGET_INNER_SIZE
    payload_fields[height_index][2] = ICON_TARGET_INNER_SIZE
    payload_fields[style_index][2] = bytes(style_commands)
    payload_fields[args_index][2] = pack_float32_array(style_args)
    return encode_proto_fields(payload_fields)


def patch_copysearch_icon_blob(blob: bytes) -> tuple[bytes, str]:
    top_fields = parse_proto_fields(blob)

    source_index: int | None = None
    source_fields: list[list[object]] | None = None
    source_path_index: int | None = None

    search_target_index: int | None = None
    search_target_fields: list[list[object]] | None = None

    ask_target_index: int | None = None
    ask_target_fields: list[list[object]] | None = None

    for top_idx, (field_number, wire_type, value) in enumerate(top_fields):
        if field_number != 2 or wire_type != 2:
            continue
        name, entry_fields, path_field_index = get_icon_entry_details(bytes(value))
        if name == ICON_ENTRY_GOOGLE_SOURCE and path_field_index is not None:
            source_index = top_idx
            source_fields = entry_fields
            source_path_index = path_field_index
        elif name == ICON_SEARCH_TARGET_ENTRY and search_target_fields is None:
            search_target_index = top_idx
            search_target_fields = entry_fields
        elif name == ICON_ASK_TARGET_ENTRY and ask_target_fields is None:
            ask_target_index = top_idx
            ask_target_fields = entry_fields

    if source_index is None or source_fields is None or source_path_index is None:
        raise ValueError(
            "Could not locate required icon entries "
            f"(source={ICON_ENTRY_GOOGLE_SOURCE})"
        )
    if search_target_index is None or search_target_fields is None:
        raise ValueError(
            "Could not locate required icon entries "
            f"(target={ICON_SEARCH_TARGET_ENTRY})"
        )
    if ask_target_index is None or ask_target_fields is None:
        raise ValueError(
            "Could not locate required icon entries "
            f"(target={ICON_ASK_TARGET_ENTRY})"
        )

    source_path = bytes(source_fields[source_path_index][2])
    current_search_svg = get_icon_entry_svg(search_target_fields)
    current_ask_svg = get_icon_entry_svg(ask_target_fields)
    if current_search_svg is None:
        raise ValueError(
            f"Icon entry {ICON_SEARCH_TARGET_ENTRY} has no embedded SVG "
            "(unexpected icon pack layout)"
        )
    if current_ask_svg is None:
        raise ValueError(
            f"Icon entry {ICON_ASK_TARGET_ENTRY} has no embedded SVG "
            "(unexpected icon pack layout)"
        )

    desired_search_svg = build_google_g_svg_text(source_path)
    desired_ask_svg = build_openai_svg_text()

    updates: list[str] = []
    if current_search_svg != desired_search_svg:
        search_target_fields = set_icon_entry_svg(search_target_fields, desired_search_svg)
        top_fields[search_target_index][2] = encode_proto_fields(search_target_fields)
        updates.append("copysearch search icon -> Google G SVG")
    if current_ask_svg != desired_ask_svg:
        ask_target_fields = set_icon_entry_svg(ask_target_fields, desired_ask_svg)
        top_fields[ask_target_index][2] = encode_proto_fields(ask_target_fields)
        updates.append("copysearch ask-ai icon -> UXWing OpenAI SVG")

    if not updates:
        return (
            blob,
            "already patched (search icon is Google G and ask-ai icon is UXWing OpenAI)",
        )

    new_blob = encode_proto_fields(top_fields)
    return (new_blob, f"patched ({'; '.join(updates)})")


def patch_copysearch_icon_pack(path: Path) -> str:
    version, encoding, aliases, resources = parse_datapack(path)

    resource_index: int | None = None
    for idx, (resource_id, _payload) in enumerate(resources):
        if int(resource_id) == ICON_RESOURCE_ID:
            resource_index = idx
            break

    if resource_index is None:
        raise ValueError(f"Icon resource id {ICON_RESOURCE_ID} not found in {path}")

    current_blob = bytes(resources[resource_index][1])
    patched_blob, message = patch_copysearch_icon_blob(current_blob)

    if patched_blob != current_blob:
        resources[resource_index][1] = patched_blob
        rebuilt = build_datapack(version, encoding, aliases, resources)
        path.write_bytes(rebuilt)

    return message


def patch_icon_paks(app_root: Path) -> list[str]:
    logs: list[str] = []
    for file_name in ICON_PACK_FILES:
        pak_path = app_root / file_name
        msg = patch_copysearch_icon_pack(pak_path)
        logs.append(f"{file_name}: {msg}")
    return logs


def patch_resources_pak(path: Path) -> list[str]:
    return patch_datapack_substrings(path, NTP_RESOURCE_ICON_REPLACEMENTS)


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
    browser_100_pak = app_root / "browser_100_percent.pak"
    browser_200_pak = app_root / "browser_200_percent.pak"
    try:
        ntp_bundle = find_ntp_bundle_path(app_root)
        ntp_locale_chunks = find_ntp_locale_chunk_paths(app_root)
    except Exception as exc:
        print(f"[ERROR] {exc}")
        return 1
    local_state = yandex_root / "User Data" / "Local State"

    required = [
        browser_dll,
        ru_pak,
        resources_pak,
        *web_app_configs,
        browser_100_pak,
        browser_200_pak,
        ntp_bundle,
        *ntp_locale_chunks,
        local_state,
    ]
    missing = [str(p) for p in required if not p.exists()]
    if missing:
        print("[ERROR] Missing required files:")
        for item in missing:
            print(f"  - {item}")
        return 1

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    try:
        backups: list[Path | None] = []
        for target in required:
            backups.append(make_backup(target, stamp, args.no_backup))

        dll_logs = patch_browser_dll(browser_dll)
        pak_logs = patch_ru_pak(ru_pak)
        resources_logs = patch_resources_pak(resources_pak)
        web_app_logs = patch_web_app_configs(app_root)
        icon_logs = patch_icon_paks(app_root)
        ntp_logs = patch_ntp_bundle(ntp_bundle)
        ntp_locale_logs = [
            (chunk_path, patch_ntp_locale_chunk(chunk_path))
            for chunk_path in ntp_locale_chunks
        ]
        state_log = ensure_instaserp(local_state)

        print("[OK] Patch finished")
        print(f"  App version: {app_version}")
        print(f"  browser.dll: {browser_dll}")
        for line in dll_logs:
            print(f"    - {line}")
        print("  ru.pak:")
        for line in pak_logs:
            print(f"    - {line}")
        print(f"  resources.pak: {resources_pak}")
        for line in resources_logs:
            print(f"    - {line}")
        print("  web app config:")
        for line in web_app_logs:
            print(f"    - {line}")
        print("  icon packs:")
        for line in icon_logs:
            print(f"    - {line}")
        print(f"  NTP bundle: {ntp_bundle}")
        for line in ntp_logs:
            print(f"    - {line}")
        for chunk_path, chunk_logs in ntp_locale_logs:
            print(f"  NTP locale chunk: {chunk_path}")
            for line in chunk_logs:
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
    raise SystemExit("Use the safe release runners instead of shared_patchlib.py directly.")
