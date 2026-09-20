"""Normalize stored WAPI evidence without resolving inheritance ourselves."""

from __future__ import annotations

from copy import deepcopy
from ipaddress import ip_address
import json
from typing import Any, Iterator
from urllib.parse import unquote


ROOT_DHCP_OBJECT = "grid:dhcpproperties"
_IDENTITY_FIELDS = {"_ref", "name", "grid", "host_name", "network", "network_view", "comment"}
_SOURCE_LEVELS = {
    ROOT_DHCP_OBJECT: "Grid", "grid": "Grid", "member:dhcpproperties": "Member",
    "member": "Member", "network": "Network", "range": "Range", "fixedaddress": "Fixed Address",
    "networktemplate": "Network Template", "rangetemplate": "Range Template",
    "fixedaddresstemplate": "Fixed Address Template", "record:host": "Host",
}


def parse_source_ref(source_ref: Any) -> dict[str, Any]:
    """Keep the original ref; decode only the human-readable suffix when present."""
    source = {"source_ref": deepcopy(source_ref), "source_level": "UNKNOWN",
              "source_object": "", "source_network_view": ""}
    if source_ref == "NOT_DEFINED":
        source["source_level"] = "NOT_DEFINED"
        return source
    if not isinstance(source_ref, str) or not source_ref:
        return source
    object_type, separator, remainder = source_ref.partition("/")
    source["source_level"] = _SOURCE_LEVELS.get(object_type, object_type)
    # The colon in member:dhcpproperties is part of the type, not the suffix separator.
    suffix = unquote(remainder.partition(":")[2]) if separator else ""
    if not suffix:
        return source
    if object_type in {"network", "range", "fixedaddress"} and "/" in suffix:
        suffix, source["source_network_view"] = suffix.rsplit("/", 1)
    if object_type == "range" and suffix.count("/") == 1:
        start, end = suffix.split("/")
        try:
            ip_address(start)
            ip_address(end)
        except ValueError:
            pass  # Preserve unfamiliar ref suffixes without guessing their meaning.
        else:
            suffix = f"{start}-{end}"
    source["source_object"] = suffix
    return source


def _identity(record: dict[str, Any]) -> str:
    return str(record.get("_ref") or json.dumps(
        [record.get(key) for key in ("name", "host_name", "network_view", "network", "start_addr", "end_addr", "ipv4addr")],
        sort_keys=True, default=str,
    ))


def _paired_records(
    records: dict[str, list[dict[str, Any]]],
    effective_records: dict[str, list[dict[str, Any]]],
) -> Iterator[tuple[str, dict[str, Any], dict[str, Any]]]:
    for object_type in sorted(set(records) | set(effective_records)):
        raw = {_identity(row): row for row in records.get(object_type, [])}
        effective = {_identity(row): row for row in effective_records.get(object_type, [])}
        for identity in sorted(set(raw) | set(effective)):
            yield object_type, raw.get(identity, {}), effective.get(identity, {})


def _base_row(grid: str, grid_url: str, wapi_version: str, object_type: str,
              raw: dict[str, Any], effective: dict[str, Any]) -> dict[str, Any]:
    context = {**raw, **effective}
    source = parse_source_ref(context.get("_ref", ""))
    name = context.get("name") or context.get("host_name") or ""
    if object_type == "network":
        name = context.get("network") or name
    elif object_type == "range" and context.get("start_addr") and context.get("end_addr"):
        name = f"{context['start_addr']}-{context['end_addr']}"
    elif object_type == "fixedaddress":
        name = context.get("ipv4addr") or name
    return {
        "grid": grid, "grid_url": grid_url, "wapi_version": wapi_version,
        "object_type": object_type, "object_ref": context.get("_ref", ""),
        "object_name": name or source["source_object"],
        "network_view": context.get("network_view") or source["source_network_view"],
        "parent_network": context.get("network", ""),
        "comment": context.get("comment", ""),
        "extensible_attributes": deepcopy(context.get("extattrs", {})),
    }


def _overrides(schema: dict[str, Any]) -> dict[str, str]:
    fields = schema.get("fields", [])
    if not isinstance(fields, list):
        return {}
    return {field["name"]: field["overridden_by"] for field in fields
            if isinstance(field, dict) and isinstance(field.get("name"), str)
            and isinstance(field.get("overridden_by"), str)}


def _is_wrapper(value: Any) -> bool:
    return isinstance(value, dict) and ("inherited" in value or "multisource" in value)


def _state(base: dict[str, Any], wrapper: dict[str, Any] | None, *, root: bool = False,
           value: Any = None, has_value: bool = False) -> dict[str, Any]:
    state = {
        "effective_value": None, "configured_here": None, "inherited": None, "multisource": None,
        "source_ref": "", "source_level": "UNKNOWN", "source_object": "", "source_network_view": "",
        "status": "PARTIAL", "inheritance_details": deepcopy(wrapper),
    }
    if wrapper is None and not root:
        return state
    wrapper = wrapper if wrapper is not None else {"inherited": False, "source": "", "multisource": False}
    inherited = wrapper.get("inherited")
    multisource = wrapper.get("multisource", False)
    source_ref = wrapper.get("source", "")
    state.update(inherited=inherited, multisource=multisource, source_ref=deepcopy(source_ref))
    if inherited is False and source_ref != "":
        return state
    if source_ref == "NOT_DEFINED":
        state.update(parse_source_ref(source_ref))
        state.update(status="NOT_CONFIGURED", configured_here=False)
        return state
    if multisource is True:
        # Shapes vary by WAPI field. Preserve all relationships, including unknown shapes.
        state.update(source_ref=deepcopy(source_ref), source_level="MULTISOURCE",
                     effective_value=deepcopy(value) if has_value else None,
                     status="COMPLETE" if has_value else "PARTIAL")
        return state
    if inherited is False and source_ref == "":
        source_ref = base["object_ref"]
        state["configured_here"] = True
    elif inherited is True and isinstance(source_ref, str) and source_ref:
        state["configured_here"] = False
    else:
        return state
    state.update(parse_source_ref(source_ref))
    if inherited is False:
        state["source_object"] = base["object_name"] or state["source_object"]
        state["source_network_view"] = base["network_view"] or state["source_network_view"]
    state["effective_value"] = deepcopy(value) if has_value else None
    state["status"] = "COMPLETE" if has_value else "PARTIAL"
    return state


def _option_key(option: dict[str, Any]) -> tuple[str, str]:
    return str(option.get("vendor_class") or "DHCP"), str(option.get("num", option.get("name", "")))


def _plain_options(value: Any) -> list[dict[str, Any]]:
    # Do not invent option semantics for malformed or unrecognized response shapes.
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict) and not _is_wrapper(item)]


def _sort_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(rows, key=lambda row: tuple(str(row.get(key, "")) for key in
                  ("grid", "object_type", "object_ref", "parameter", "vendor_class", "option_number", "source_ref")))


def normalize_options(
    grid: str, grid_url: str, wapi_version: str,
    records: dict[str, list[dict[str, Any]]],
    effective_records: dict[str, list[dict[str, Any]]] | None = None,
    schemas: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Flatten WAPI's effective option groups; never merge parent options locally."""
    rows: list[dict[str, Any]] = []
    for object_type, raw, effective in _paired_records(records, effective_records or {}):
        base = _base_row(grid, grid_url, wapi_version, object_type, raw, effective)
        raw_options = _plain_options(raw.get("options"))
        raw_by_key = {_option_key(option): option for option in raw_options}
        override_field = _overrides((schemas or {}).get(object_type, {})).get("options", "")
        used: set[tuple[str, str]] = set()

        def emit(option: dict[str, Any], wrapper: dict[str, Any] | None, *, root: bool = False) -> None:
            key = _option_key(option)
            stored = raw_by_key.get(key, {})
            used.add(key)
            rows.append({
                **base, "parameter": option.get("name", option.get("num", "options")),
                "option_number": option.get("num"), "vendor_class": option.get("vendor_class", "DHCP"),
                "raw_value": deepcopy(stored.get("value")), "raw_use_option": stored.get("use_option"),
                "raw_use_field": override_field, "raw_use": raw.get(override_field),
                **_state(base, wrapper, root=root, value=option.get("value"), has_value="value" in option),
            })

        def emit_unknown(payload: Any) -> None:
            emit({"name": "options"}, None)
            rows[-1]["inheritance_details"] = deepcopy(payload)

        options = effective.get("options")
        if isinstance(options, list):
            for group in options:
                if not _is_wrapper(group):
                    continue
                values = group.get("values", [])
                if isinstance(values, list):
                    for option in values:
                        if isinstance(option, dict):
                            emit(option, group)
                        else:
                            emit_unknown(group)
                else:
                    emit_unknown(group)
                if group.get("source") == "NOT_DEFINED" and not values:
                    emit({"name": "options"}, group)
                elif not values:
                    emit_unknown(group)
        elif options is not None:
            emit_unknown(options)
        if object_type == ROOT_DHCP_OBJECT:
            # Grid DHCP properties is the root; it has no parent override relationship.
            for option in _plain_options(options if options is not None else raw.get("options")):
                if _option_key(option) not in used:
                    emit(option, None, root=option.get("use_option") is not False)
        for option in raw_options:
            if _option_key(option) not in used:
                emit(option, None)
        # Preserve unwrapped effective output as unresolved evidence when no raw entry exists.
        for option in _plain_options(options):
            if _option_key(option) not in used:
                emit(option, None)
    return _sort_rows(rows)


def normalize_scalars(
    grid: str, grid_url: str, wapi_version: str,
    records: dict[str, list[dict[str, Any]]],
    effective_records: dict[str, list[dict[str, Any]]] | None = None,
    schemas: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Normalize scalar wrappers and schema-established override fields."""
    rows: list[dict[str, Any]] = []
    for object_type, raw, effective in _paired_records(records, effective_records or {}):
        base = _base_row(grid, grid_url, wapi_version, object_type, raw, effective)
        overrides = _overrides((schemas or {}).get(object_type, {}))
        fields = {name for name in overrides if name in raw or name in effective}
        fields.update(name for name, value in effective.items() if _is_wrapper(value))
        if object_type == ROOT_DHCP_OBJECT:
            fields.update(name for name, value in {**raw, **effective}.items()
                          if name not in _IDENTITY_FIELDS and not name.startswith("use_")
                          and not isinstance(value, (dict, list)))
        for name in sorted(fields - {"options"}):
            value = effective.get(name)
            wrapper = value if _is_wrapper(value) else None
            root = object_type == ROOT_DHCP_OBJECT
            candidate = wrapper.get("value") if wrapper is not None else effective.get(name, raw.get(name))
            has_value = "value" in wrapper if wrapper is not None else root and (name in effective or name in raw)
            rows.append({
                **base, "parameter": name, "raw_value": deepcopy(raw.get(name)),
                "raw_use_field": overrides.get(name, ""), "raw_use": raw.get(overrides.get(name, "")),
                **_state(base, wrapper, root=root, value=candidate, has_value=has_value),
            })
    return _sort_rows(rows)
