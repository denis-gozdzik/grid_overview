from __future__ import annotations

from dataclasses import dataclass
import logging
import re
from time import monotonic
from typing import Any, Callable, Iterable
from urllib.parse import urlsplit

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .config import GridConfig

LOG = logging.getLogger(__name__)
COMPATIBLE_WAPI_VERSION = "2.13.7"
_OBJECT_TYPE = re.compile(r"[a-z][a-z0-9_]*(?::[a-z][a-z0-9_]*)*\Z")
_FIELD_NAME = re.compile(r"[_a-zA-Z][_a-zA-Z0-9]*(?:\.[_a-zA-Z][_a-zA-Z0-9]*)*\Z")
PageCallback = Callable[[int, Any], None]


class WapiError(RuntimeError):
    """A sanitized HTTP or protocol error while reading WAPI."""

    def __init__(self, message: str, *, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class WapiResponse:
    data: Any
    url: str


def _version(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"v?\d+\.\d+(?:\.\d+)?", value):
        raise WapiError("Invalid WAPI version; use a numeric version such as 2.13.7")
    return value.removeprefix("v")


def _object_path(object_type: str) -> str:
    if not isinstance(object_type, str) or not _OBJECT_TYPE.fullmatch(object_type):
        raise WapiError("Invalid WAPI object type; references, URLs and function paths are forbidden")
    if object_type in {"request", "fileop"}:
        raise WapiError("Operation endpoints are forbidden in the read-only collector")
    return f"/{object_type}"


class InfobloxClient:
    """GET-only WAPI searches, schema discovery and bounded transient retries."""

    def __init__(self, grid: GridConfig, username: str, password: str,
                 session: requests.Session | None = None):
        parsed = urlsplit(grid.url)
        if (parsed.scheme not in {"http", "https"} or not parsed.hostname
                or parsed.username is not None or parsed.password is not None
                or parsed.path not in {"", "/"} or parsed.query or parsed.fragment):
            raise WapiError("Grid URL must be an HTTP(S) origin without credentials or a WAPI path")
        self.grid = grid
        self._auto_version = grid.wapi_version == "auto"
        self.wapi_version = _version(COMPATIBLE_WAPI_VERSION if self._auto_version else grid.wapi_version)
        self._schemas: dict[tuple[str, str | None], dict[str, Any]] = {}
        self.session = session if session is not None else requests.Session()
        self.session.auth = (username, password)
        self.session.verify = grid.ca_bundle or grid.verify_tls
        self.session.headers.update({"Accept": "application/json"})
        retry = Retry(total=3, connect=3, read=3, status=3, backoff_factor=0.5,
                      status_forcelist=(429, 500, 502, 503, 504),
                      allowed_methods=frozenset({"GET"}), raise_on_status=False,
                      respect_retry_after_header=False)
        self.session.mount("https://", HTTPAdapter(max_retries=retry))
        self.session.mount("http://", HTTPAdapter(max_retries=retry))
        self._closed = False
        if self.session.verify is False:
            LOG.warning("grid=%s TLS certificate verification is disabled", grid.name)

    def close(self) -> None:
        if not self._closed:
            self.session.close()
            self._closed = True

    def __enter__(self) -> InfobloxClient:
        return self

    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None:
        self.close()

    def _base_url(self, version: str | None = None) -> str:
        selected = _version(version or self.wapi_version)
        return f"{self.grid.url.rstrip('/')}/wapi/v{selected}"

    def _get(self, path: str, params: dict[str, Any] | None = None) -> WapiResponse:
        if self._closed:
            raise WapiError("WAPI client is closed")
        if path != "/":
            path = _object_path(path.removeprefix("/"))
        if params and any(key in params for key in ("_function", "_method", "_body", "_args")):
            raise WapiError("Function and operation parameters are forbidden")
        url = self._base_url() + path
        started = monotonic()
        LOG.debug("grid=%s method=GET endpoint=%s starting", self.grid.name, path)
        try:
            response = self.session.get(url, params=params, timeout=self.grid.timeout, allow_redirects=False)
        except requests.RequestException as exc:
            # Exceptions can include credentials, query values or proxy URLs.
            kind = type(exc).__name__
            LOG.error("grid=%s endpoint=%s request failed (%s)", self.grid.name, path, kind)
            raise WapiError(f"GET {path} failed ({kind})") from None
        LOG.debug("grid=%s method=GET endpoint=%s status=%d elapsed=%.3fs", self.grid.name, path,
                  response.status_code, monotonic() - started)
        if 300 <= response.status_code < 400:
            raise WapiError(f"Redirect refused for GET {path}: HTTP {response.status_code}",
                            status_code=response.status_code)
        if not 200 <= response.status_code < 300:
            # Server errors can echo authentication or sensitive query values.
            raise WapiError(f"GET {path} failed: HTTP {response.status_code}", status_code=response.status_code)
        try:
            data = response.json()
        except ValueError:
            raise WapiError(f"GET {path} returned invalid JSON") from None
        return WapiResponse(data, url)

    def detect_version(self, candidates: Iterable[str] = (COMPATIBLE_WAPI_VERSION,)) -> str:
        """Verify the baseline using root schema, with explicitly supplied fallbacks.

        An advertised newer release never changes selection. An explicitly
        configured version is authoritative and is verified without fallback.
        """
        selected = self.wapi_version
        choices = ([COMPATIBLE_WAPI_VERSION, *(_version(item) for item in candidates)]
                   if self._auto_version else [selected])
        last_error: WapiError | None = None
        for candidate in dict.fromkeys(choices):
            self.wapi_version = candidate
            try:
                root = self.schema()
                versions = root.get("supported_versions")
                if "supported_versions" in root:
                    if not isinstance(versions, list) or not versions or not all(isinstance(v, str) for v in versions):
                        raise WapiError("Root schema contains invalid supported_versions")
                    if candidate not in {_version(item) for item in versions}:
                        raise WapiError("Requested WAPI version is absent from supported_versions")
                requested = root.get("requested_version")
                if requested is not None and _version(requested) != candidate:
                    raise WapiError("Root schema returned a different WAPI version")
                LOG.info("grid=%s WAPI version=%s", self.grid.name, candidate)
                return candidate
            except WapiError as exc:
                last_error = exc
                if exc.status_code in {401, 403}:
                    break
        self.wapi_version = selected
        raise WapiError(f"Unable to verify a compatible WAPI version: {last_error}",
                        status_code=last_error.status_code if last_error else None) from None

    @staticmethod
    def _search_params(return_fields: Iterable[str] | None, filters: dict[str, Any] | None,
                       max_results: int) -> dict[str, Any]:
        if isinstance(max_results, bool) or not isinstance(max_results, int) or max_results <= 0:
            raise WapiError("Page size must be a positive integer")
        params: dict[str, Any] = {"_max_results": max_results}
        if return_fields is not None:
            if isinstance(return_fields, str):
                raise WapiError("Return fields must be an iterable of field names")
            fields = list(return_fields)
            if not all(isinstance(field, str) and _FIELD_NAME.fullmatch(field) for field in fields):
                raise WapiError("Invalid return field name")
            if fields:
                params["_return_fields"] = ",".join(dict.fromkeys(fields))
        for key, value in (filters or {}).items():
            if not isinstance(key, str) or (key.startswith("_") and key != "_inheritance"):
                raise WapiError("Collection filters cannot override WAPI control parameters")
            if key == "_inheritance" and value not in (True, False, "True", "False"):
                raise WapiError("The inheritance parameter must be True or False")
            params[key] = value
        return params

    @staticmethod
    def _records(data: Any, object_type: str) -> list[dict[str, Any]]:
        if isinstance(data, dict) and "Error" in data:
            raise WapiError(f"GET /{object_type} returned a WAPI error")
        if not isinstance(data, list) or not all(isinstance(item, dict) for item in data):
            raise WapiError(f"Expected a list of objects for {object_type}")
        return data

    def get(self, object_type: str, return_fields: Iterable[str] | None = None,
            filters: dict[str, Any] | None = None, max_results: int = 1000) -> list[dict[str, Any]]:
        """Perform one unpaged GET. Use get_all_objects for inventory collection."""
        path = _object_path(object_type)
        params = self._search_params(return_fields, filters, max_results)
        return self._records(self._get(path, params).data, object_type)

    def get_all_objects(self, object_type: str, return_fields: Iterable[str] | None = None,
                        filters: dict[str, Any] | None = None, max_results: int = 1000,
                        page_callback: PageCallback | None = None) -> list[dict[str, Any]]:
        """Collect WAPI result envelopes and optionally preserve decoded responses.

        Continuation IDs encode the initial query, including inheritance. The
        callback precedes validation so malformed pages remain inspectable.
        Raw dictionaries are never modified by the client.
        """
        path = _object_path(object_type)
        params = self._search_params(return_fields, filters, max_results)
        params.update({"_paging": 1, "_return_as_object": 1})
        objects: list[dict[str, Any]] = []
        seen_pages: set[str] = set()
        page_number = 0
        while True:
            page_number += 1
            started = monotonic()
            data = self._get(path, params).data
            if page_callback is not None:
                page_callback(page_number, data)
            if not isinstance(data, dict) or "result" not in data or "Error" in data:
                raise WapiError(f"Expected a WAPI paging result envelope for {object_type}")
            page = self._records(data["result"], object_type)
            next_page = data.get("next_page_id")
            if "next_page_id" in data and (not isinstance(next_page, str) or not next_page):
                raise WapiError(f"Invalid next_page_id for {object_type}")
            objects.extend(page)
            LOG.info("grid=%s endpoint=%s page=%d records=%d elapsed=%.3fs",
                     self.grid.name, object_type, page_number, len(page), monotonic() - started)
            if next_page is None:
                break
            if next_page in seen_pages:
                raise WapiError(f"Pagination loop detected for {object_type}")
            seen_pages.add(next_page)
            params = {"_page_id": next_page}
        return objects

    def schema(self, object_type: str | None = None) -> dict[str, Any]:
        """Return cached root or object schema for the selected WAPI version."""
        path = _object_path(object_type) if object_type is not None else "/"
        cache_key = (self.wapi_version, object_type)
        if cache_key not in self._schemas:
            params: dict[str, Any] = {"_schema": "1"}
            if object_type is not None:
                params.update({"_schema_version": "2", "_schema_searchable": "1"})
            data = self._get(path, params).data
            if not isinstance(data, dict) or "Error" in data:
                raise WapiError("WAPI schema must be a JSON object without an error envelope")
            self._schemas[cache_key] = data
        return self._schemas[cache_key]
