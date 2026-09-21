from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class CollectionResult:
    grid: str
    records: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    coverage: list[dict[str, Any]] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)
    effective_records: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    schemas: dict[str, dict[str, Any]] = field(default_factory=dict)
    grid_url: str = ""
    wapi_version: str = ""
    collected_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    collection_sources: list[dict[str, Any]] = field(default_factory=list)

    def add(self, area: str, object_type: str, rows: list[dict[str, Any]], note: str = "") -> None:
        self.records[object_type] = rows
        self.coverage.append({"Grid": self.grid, "Area": area,
                              "Collection Status": "PARTIAL" if note else ("COMPLETE" if rows else "EMPTY"),
                              "Objects Found": len(rows), "Notes": note})

    def fail(self, area: str, object_type: str, error: Exception) -> None:
        self.coverage.append({"Grid": self.grid, "Area": area, "Collection Status": "ERROR",
                              "Objects Found": "", "Notes": str(error)})
        self.errors.append({"grid": self.grid, "area": area, "object_type": object_type,
                            "error": str(error)})


ASSESSMENT_AREAS = [
    "Network Views", "DHCP failover associations and/or Grid Members", "Existing network templates",
    "Existing range templates", "DHCP option spaces", "DHCP options and inheritance", "Lease times",
    "DNS servers", "Domain name and search domains", "Default gateway conventions", "NTP servers",
    "PXE and boot options", "DHCP filters and MAC filters", "Fixed addresses and reservations",
    "DDNS settings", "Extensible Attributes", "Naming conventions", "Approval process",
    "Documentation requirements", "Local exceptions",
]
