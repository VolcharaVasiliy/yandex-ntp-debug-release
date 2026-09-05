#!/usr/bin/env python3
from __future__ import annotations

from shared_patchlib import (
    ICON_ASK_TARGET_ENTRY,
    ICON_ENTRY_GOOGLE_SOURCE,
    ICON_RESOURCE_ID,
    ICON_SEARCH_TARGET_ENTRY,
    build_google_g_svg_text,
    build_openai_svg_text,
    get_icon_entry_svg,
    get_icon_entry_details,
    parse_datapack,
    parse_proto_fields,
)


def get_icon_source_path(icon_blob: bytes, entry_name: str) -> bytes | None:
    for field_number, wire_type, value in parse_proto_fields(icon_blob):
        if field_number != 2 or wire_type != 2:
            continue
        name, entry_fields, path_field_index = get_icon_entry_details(bytes(value))
        if name == entry_name and path_field_index is not None:
            return bytes(entry_fields[path_field_index][2])
    return None


def get_icon_entry_svg_by_name(icon_blob: bytes, entry_name: str) -> bytes | None:
    for field_number, wire_type, value in parse_proto_fields(icon_blob):
        if field_number != 2 or wire_type != 2:
            continue
        name, entry_fields, _path_field_index = get_icon_entry_details(bytes(value))
        if name == entry_name:
            return get_icon_entry_svg(entry_fields)
    return None


def verify_copysearch_icon_pack(path) -> tuple[bool, str]:
    _version, _encoding, _aliases, resources = parse_datapack(path)
    icon_blob: bytes | None = None
    for resource_id, payload in resources:
        if int(resource_id) == ICON_RESOURCE_ID:
            icon_blob = bytes(payload)
            break

    if icon_blob is None:
        return False, f"{path.name}: resource id {ICON_RESOURCE_ID} not found"

    source_path = get_icon_source_path(icon_blob, ICON_ENTRY_GOOGLE_SOURCE)
    if source_path is None:
        return False, f"{path.name}: source icon entry not found ({ICON_ENTRY_GOOGLE_SOURCE})"

    search_svg = get_icon_entry_svg_by_name(icon_blob, ICON_SEARCH_TARGET_ENTRY)
    if search_svg is None:
        return False, f"{path.name}: target icon entry not found ({ICON_SEARCH_TARGET_ENTRY})"

    ask_svg = get_icon_entry_svg_by_name(icon_blob, ICON_ASK_TARGET_ENTRY)
    if ask_svg is None:
        return False, f"{path.name}: target icon entry not found ({ICON_ASK_TARGET_ENTRY})"

    expected_search_svg = build_google_g_svg_text(source_path)
    expected_ask_svg = build_openai_svg_text()

    if search_svg != expected_search_svg:
        return False, f"{path.name}: search icon SVG does not match generated Google G"
    if ask_svg != expected_ask_svg:
        return False, f"{path.name}: ask-ai icon SVG does not match UXWing OpenAI"

    return (
        True,
        f"{path.name}: search icon=Google G SVG (len={len(search_svg)}); "
        f"ask-ai icon=UXWing OpenAI SVG (len={len(ask_svg)})",
    )
