from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import math
import os
import re
from urllib.parse import urlsplit

import yaml


DEFAULT_PAGE_SIZE = 250
MAX_PAGE_SIZE = 1000


def validate_page_size(value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= MAX_PAGE_SIZE:
        raise ValueError(f"page_size must be an integer between 1 and {MAX_PAGE_SIZE}")


@dataclass(frozen=True)
class GridConfig:
    name: str
    url: str
    wapi_version: str = "2.13.7"
    verify_tls: bool = True
    ca_bundle: str | None = None
    timeout: tuple[float, float] = (10.0, 60.0)
    username: str | None = None
    password_env: str = "INFOBLOX_PASSWORD"
    page_size: int = DEFAULT_PAGE_SIZE

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip() or any(ord(c) < 32 for c in self.name):
            raise ValueError("Grid name must be nonempty text without control characters")
        try:
            parsed = urlsplit(self.url)
            valid_url = (parsed.scheme == "https" and parsed.hostname and not parsed.username
                         and not parsed.password and not parsed.query and not parsed.fragment
                         and parsed.path in {"", "/"} and parsed.port != 0)
        except (ValueError, TypeError):
            valid_url = False
        if not valid_url:
            raise ValueError("Grid URL must be an HTTPS origin without credentials, WAPI path, query, or fragment")
        object.__setattr__(self, "url", self.url.rstrip("/"))
        version = str(self.wapi_version).removeprefix("v")
        if version != "auto" and not re.fullmatch(r"[0-9]+(?:\.[0-9]+){1,2}", version):
            raise ValueError("wapi_version must be numeric, for example 2.13.7")
        object.__setattr__(self, "wapi_version", version)
        if not isinstance(self.verify_tls, bool):
            raise ValueError("verify_tls must be a YAML boolean")
        if self.ca_bundle is not None and (not isinstance(self.ca_bundle, str) or not self.ca_bundle):
            raise ValueError("ca_bundle must be a nonempty filesystem path")
        if not isinstance(self.password_env, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", self.password_env):
            raise ValueError("password_env must name an environment variable")
        if self.username is not None and (not isinstance(self.username, str) or not self.username):
            raise ValueError("username must be nonempty text")
        if (not isinstance(self.timeout, (tuple, list)) or len(self.timeout) != 2
                or any(isinstance(value, bool) or not isinstance(value, (int, float))
                       or (isinstance(value, float) and not math.isfinite(value)) or value <= 0
                       for value in self.timeout)):
            raise ValueError("Connection and read timeouts must be finite positive numbers")
        validate_page_size(self.page_size)


def load_config(path: str | Path, selected_grid: str | None = None) -> list[GridConfig]:
    try:
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        raise ValueError("Invalid configuration YAML") from None
    if not isinstance(data, dict) or not isinstance(data.get("grids"), list):
        raise ValueError("Configuration must contain a grids list")
    allowed = {"name", "url", "wapi_version", "verify_tls", "ca_bundle", "connect_timeout",
               "read_timeout", "username", "password_env", "page_size"}
    grids: list[GridConfig] = []
    names: set[str] = set()
    for item in data["grids"]:
        if not isinstance(item, dict):
            raise ValueError("Each Grid configuration must be a mapping")
        if set(item) - allowed:
            raise ValueError("Unknown Grid configuration key; passwords must use password_env or the secure prompt")
        if "name" not in item or "url" not in item:
            raise ValueError("Each Grid requires name and url")
        grid = GridConfig(
            name=item["name"], url=item["url"], wapi_version=item.get("wapi_version", "2.13.7"),
            verify_tls=item.get("verify_tls", True), ca_bundle=item.get("ca_bundle"),
            timeout=(item.get("connect_timeout", 10.0), item.get("read_timeout", 60.0)),
            username=item.get("username"), password_env=item.get("password_env", "INFOBLOX_PASSWORD"),
            page_size=item.get("page_size", DEFAULT_PAGE_SIZE),
        )
        if grid.name.casefold() in names:
            raise ValueError("Grid names must be unique (case insensitive for portable archives)")
        names.add(grid.name.casefold())
        if selected_grid is None or grid.name == selected_grid:
            grids.append(grid)
    if not grids:
        raise ValueError("No grids matched the configuration")
    return grids


def credentials_from_environment(grid: GridConfig | None = None) -> tuple[str | None, str | None]:
    username = (grid.username if grid else None) or os.getenv("INFOBLOX_USER")
    password = os.getenv(grid.password_env if grid else "INFOBLOX_PASSWORD")
    return username, password
