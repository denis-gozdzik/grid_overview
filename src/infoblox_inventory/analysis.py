from collections import Counter, defaultdict
import json
import re
from typing import Any


def compare_options(option_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, ...], dict[str, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    for row in option_rows:
        if row.get("status") != "COMPLETE" or row.get("multisource") is True:
            continue
        object_type = str(row.get("object_type", ""))
        context = "Grid DHCP properties" if object_type == "grid:dhcpproperties" else str(
            row.get("object_name") or row.get("parent_network") or row.get("object_ref", ""))
        key = (object_type, str(row.get("network_view", "")), str(row.get("parameter", "")),
               str(row.get("vendor_class", "")), str(row.get("option_number", "")), context)
        groups[key][row.get("grid", "")].append(row)
    output: list[dict[str, Any]] = []
    for (object_type, view, parameter, vendor, number, context), by_grid in sorted(groups.items()):
        values_by_grid = {grid: sorted({json.dumps(item.get("effective_value"), sort_keys=True) for item in items})
                          for grid, items in by_grid.items()}
        counts = Counter(value for values in values_by_grid.values() for value in values)
        highest_count = max(counts.values())
        most_common = sorted(value for value, count in counts.items() if count == highest_count)
        common = json.loads(most_common[0]) if len(most_common) == 1 else None
        values_differ = len({tuple(values) for values in values_by_grid.values()}) > 1
        sources_differ = len({tuple(sorted({str(item.get("source_level", "")) for item in items}))
                              for items in by_grid.values()}) > 1
        for grid, items in sorted(by_grid.items()):
            observed = [json.loads(value) for value in values_by_grid[grid]]
            classification = ("SINGLE_GRID" if len(by_grid) == 1 else "DIFFERENT" if values_differ
                              else "SOURCE_DIFFERENCE" if sources_differ else "SAME")
            output.append({"category": "DHCP option", "object/context": context,
                           "object_type": object_type, "network_view": view,
                           "vendor_class": vendor, "option_number": number,
                           "parameter": parameter, "grid": grid, "observed_value": observed,
                           "common_observed_value": common,
                           "occurrence_count": highest_count if common is not None else None,
                           "source_levels": sorted({str(item.get("source_level", "")) for item in items}),
                           "comparison_group": f"{object_type}:{view}:{vendor}:{number}:{parameter}",
                           "classification": classification,
                           "notes": "Common observed value is descriptive, not an approved standard."
                           + (" No unique most common value." if len(most_common) > 1 else "")})
    return output


def naming_analysis(records: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    names = [str(row.get("name")) for rows in records.values() for row in rows if row.get("name")]
    prefixes = Counter(re.match(r"^[A-Za-z]+", name).group(0) for name in names if re.match(r"^[A-Za-z]+", name))
    return [{"observed_pattern": f"prefix:{prefix}", "count": count,
             "examples": ", ".join(name for name in names if name.startswith(prefix))[:500],
             "confidence": "INFERRED"} for prefix, count in prefixes.most_common()]
