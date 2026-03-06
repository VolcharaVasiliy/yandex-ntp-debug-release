#!/usr/bin/env python3
from __future__ import annotations

from shared_patchlib import (
    ICON_ASK_TARGET_ENTRY,
    ICON_ENTRY_GOOGLE_SOURCE,
    ICON_RESOURCE_ID,
    ICON_SEARCH_TARGET_ENTRY,
    ICON_TARGET_INNER_SIZE,
    OPENAI_UXWING_SVG_PATH,
    build_custom_svg_icon_payload,
    build_google_g_icon_payload,
    parse_datapack,
    parse_proto_fields,
)


def get_icon_entry_data(icon_blob: bytes, entry_name: str) -> tuple[bytes, int, int] | None:
    top_fields = parse_proto_fields(icon_blob)
    for field_number, wire_type, value in top_fields:
        if field_number != 2 or wire_type != 2:
            continue

        entry_fields = parse_proto_fields(bytes(value))
        name: str | None = None
        path_data: bytes | None = None
        width = 0
        height = 0
        for sub_field_number, sub_wire_type, sub_value in entry_fields:
            if sub_field_number == 1 and sub_wire_type == 2:
                try:
                    name = bytes(sub_value).decode("utf-8")
                except UnicodeDecodeError:
                    name = None
            elif sub_field_number == 5 and sub_wire_type == 2 and path_data is None:
                path_data = bytes(sub_value)
            elif sub_field_number == 3 and sub_wire_type == 0:
                width = int(sub_value)
            elif sub_field_number == 4 and sub_wire_type == 0:
                height = int(sub_value)

        if name == entry_name:
            if path_data is None:
                return None
            return path_data, width, height
    return None


def parse_icon_payload_shape(icon_payload: bytes) -> tuple[int | None, int | None, int, int]:
    fields = parse_proto_fields(icon_payload)
    width: int | None = None
    height: int | None = None
    style_len = 0
    args_len = 0
    for field_number, wire_type, value in fields:
        if field_number == 2 and wire_type == 0 and width is None:
            width = int(value)
        elif field_number == 3 and wire_type == 0 and height is None:
            height = int(value)
        elif field_number == 5 and wire_type == 2 and style_len == 0:
            style_len = len(bytes(value))
        elif field_number == 6 and wire_type == 2 and args_len == 0:
            args_len = len(bytes(value))
    return width, height, style_len, args_len


def verify_copysearch_icon_pack(path) -> tuple[bool, str]:
    _version, _encoding, _aliases, resources = parse_datapack(path)
    icon_blob: bytes | None = None
    for resource_id, payload in resources:
        if int(resource_id) == ICON_RESOURCE_ID:
            icon_blob = bytes(payload)
            break

    if icon_blob is None:
        return False, f"{path.name}: resource id {ICON_RESOURCE_ID} not found"

    source_entry = get_icon_entry_data(icon_blob, ICON_ENTRY_GOOGLE_SOURCE)
    if source_entry is None:
        return False, f"{path.name}: source icon entry not found ({ICON_ENTRY_GOOGLE_SOURCE})"
    source_path, _source_width, _source_height = source_entry

    search_entry = get_icon_entry_data(icon_blob, ICON_SEARCH_TARGET_ENTRY)
    if search_entry is None:
        return False, f"{path.name}: target icon entry not found ({ICON_SEARCH_TARGET_ENTRY})"
    search_path, search_width, search_height = search_entry

    ask_entry = get_icon_entry_data(icon_blob, ICON_ASK_TARGET_ENTRY)
    if ask_entry is None:
        return False, f"{path.name}: target icon entry not found ({ICON_ASK_TARGET_ENTRY})"
    ask_path, ask_width, ask_height = ask_entry

    expected_search_path = build_google_g_icon_payload(source_path)
    expected_ask_path = build_custom_svg_icon_payload(ask_path, OPENAI_UXWING_SVG_PATH)

    if search_path != expected_search_path:
        return False, f"{path.name}: search icon path does not match generated Google G payload"
    if ask_path != expected_ask_path:
        return False, f"{path.name}: ask-ai icon path does not match generated UXWing OpenAI payload"
    if search_width != 32 or search_height != 32:
        return False, f"{path.name}: unexpected search icon size: {search_width}x{search_height}"
    if ask_width != 32 or ask_height != 32:
        return False, f"{path.name}: unexpected ask-ai icon size: {ask_width}x{ask_height}"

    search_inner_width, search_inner_height, search_style_len, search_args_len = parse_icon_payload_shape(search_path)
    ask_inner_width, ask_inner_height, ask_style_len, ask_args_len = parse_icon_payload_shape(ask_path)

    if search_inner_width != ICON_TARGET_INNER_SIZE or search_inner_height != ICON_TARGET_INNER_SIZE:
        return False, f"{path.name}: unexpected search inner icon size: {search_inner_width}x{search_inner_height}"
    if ask_inner_width != ICON_TARGET_INNER_SIZE or ask_inner_height != ICON_TARGET_INNER_SIZE:
        return False, f"{path.name}: unexpected ask-ai inner icon size: {ask_inner_width}x{ask_inner_height}"

    return (
        True,
        f"{path.name}: search icon=Google G "
        f"(len={len(search_path)}, style={search_style_len}, args={search_args_len}, size=32x32); "
        f"ask-ai icon=UXWing OpenAI "
        f"(len={len(ask_path)}, style={ask_style_len}, args={ask_args_len}, size=32x32)",
    )
