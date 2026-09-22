"""GET-only probe for WAPI inheritance paging shape.

This script never prints object values, names, addresses, refs or continuation
tokens.  It compares inheritance wrapper counts on page 1 and page 2.

Default mode follows the documented continuation request (page_id only).
With --compare-reassert-inheritance it performs a second independent initial
GET and probes page 2 with inheritance=True reasserted, for diagnostics only.

No appliance state is modified.
"""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import replace
import getpass
from typing import Any

from infoblox_inventory.client import InfobloxClient, WapiError
from infoblox_inventory.config import credentials_from_environment, load_config


DEFAULT_FIELDS = ("options", "nextserver", "enable_ddns")


def _is_wrapper(value: Any) -> bool:
    return isinstance(value, dict) and ("inherited" in value or "multisource" in value)


def _shape(value_present: bool, value: Any) -> str:
    if not value_present:
        return "absent"
    if _is_wrapper(value):
        return "wrapper"
    if isinstance(value, list):
        if value and all(isinstance(item, dict) and _is_wrapper(item) for item in value):
            return "wrapper"
        return "plain"
    if isinstance(value, (str, int, float, bool)) or value is None:
        return "plain"
    return "other"


def _records(payload: Any) -> tuple[list[dict[str, Any]], str | None]:
    if not isinstance(payload, dict) or not isinstance(payload.get("result"), list):
        raise ValueError("Unexpected paging response shape")
    rows = payload["result"]
    if any(not isinstance(row, dict) for row in rows):
        raise ValueError("Unexpected object shape")
    token = payload.get("next_page_id")
    return rows, token if isinstance(token, str) and token else None


def _summary(label: str, rows: list[dict[str, Any]], fields: tuple[str, ...]) -> None:
    print(f"{label}: records={len(rows)}")
    for field in fields:
        counts = Counter(_shape(field in row, row.get(field)) for row in rows)
        print(
            f"  {field}: wrapper={counts['wrapper']} plain={counts['plain']} "
            f"absent={counts['absent']} other={counts['other']}"
        )


def _initial(client: InfobloxClient, fields: tuple[str, ...]):
    params = {
        "_return_fields": ",".join(fields),
        "_paging": 1,
        "_return_as_object": 1,
        "_max_results": client.grid.page_size,
        "_inheritance": "True",
    }
    return client._get("/network", params, mode="effective", page_number=1,
                       page_size=client.grid.page_size).data


def _continuation(client: InfobloxClient, token: str, *, reassert: bool):
    params: dict[str, Any] = {"_page_id": token}
    if reassert:
        params["_inheritance"] = "True"
    return client._get("/network", params, mode="effective", page_number=2,
                       page_size=client.grid.page_size).data


def main() -> int:
    parser = argparse.ArgumentParser(description="GET-only WAPI inheritance paging diagnostic")
    parser.add_argument("--config", required=True)
    parser.add_argument("--grid", required=True)
    parser.add_argument("--fields", default=",".join(DEFAULT_FIELDS))
    parser.add_argument("--no-verify-tls", action="store_true")
    parser.add_argument("--compare-reassert-inheritance", action="store_true",
                        help="Run a second independent page-1 GET and reassert inheritance=True on page 2")
    args = parser.parse_args()

    fields = tuple(dict.fromkeys(field.strip() for field in args.fields.split(",") if field.strip()))
    if not fields:
        parser.error("At least one field is required")

    grid = load_config(args.config, args.grid)[0]
    if args.no_verify_tls:
        grid = replace(grid, verify_tls=False, ca_bundle=None)
    username, password = credentials_from_environment(grid)
    if not username:
        username = input("Infoblox username: ")
    if not password:
        password = getpass.getpass(f"Infoblox password for {grid.name}: ")

    with InfobloxClient(grid, username, password) as client:
        client.detect_version()
        first = _initial(client, fields)
        first_rows, token = _records(first)
        print(f"Grid={grid.name} object=network page_size={grid.page_size}")
        _summary("documented page 1", first_rows, fields)
        if not token:
            print("No page 2 available; object population fits in one page.")
            return 0
        second = _continuation(client, token, reassert=False)
        second_rows, _ = _records(second)
        _summary("documented page 2 (page_id only)", second_rows, fields)

        if args.compare_reassert_inheritance:
            comparison_first = _initial(client, fields)
            comparison_rows, comparison_token = _records(comparison_first)
            _summary("comparison page 1", comparison_rows, fields)
            if not comparison_token:
                print("No comparison page 2 available.")
                return 0
            try:
                comparison_second = _continuation(client, comparison_token, reassert=True)
            except WapiError as exc:
                print(f"comparison page 2 with inheritance=True: request failed ({exc})")
                return 0
            comparison_second_rows, _ = _records(comparison_second)
            _summary("comparison page 2 (page_id + inheritance=True)", comparison_second_rows, fields)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
