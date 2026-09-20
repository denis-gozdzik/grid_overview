from __future__ import annotations

from typing import Any

from .client import InfobloxClient, WapiError


class UnsupportedObjectError(WapiError):
    """Root discovery explicitly reports that the object is unavailable."""


def index_fields(schema: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Index WAPI's list of field dictionaries without modifying the schema.

    Missing or malformed metadata is a schema error, not evidence that a field
    is absent. An explicitly empty fields list is valid.
    """
    if not isinstance(schema, dict) or not isinstance(schema.get("fields"), list):
        raise WapiError("Object schema is missing a valid fields list")
    indexed: dict[str, dict[str, Any]] = {}
    for field in schema["fields"]:
        if not isinstance(field, dict) or not isinstance(field.get("name"), str) or not field["name"]:
            raise WapiError("Object schema contains invalid field metadata")
        if field["name"] in indexed:
            raise WapiError("Object schema contains duplicate field names")
        if "supports" in field and not isinstance(field["supports"], str):
            raise WapiError("Object schema contains invalid field capabilities")
        if "overridden_by" in field and (not isinstance(field["overridden_by"], str) or not field["overridden_by"]):
            raise WapiError("Object schema contains invalid override metadata")
        indexed[field["name"]] = field
    return indexed


def override_relationships(schema: dict[str, Any]) -> dict[str, str]:
    """Discover only override relationships declared by WAPI's overridden_by."""
    return {name: field["overridden_by"] for name, field in index_fields(schema).items()
            if "overridden_by" in field}


class SchemaCache:
    """Schema discovery scoped to one client and its selected WAPI version."""

    def __init__(self, client: InfobloxClient):
        self.client = client
        self._root: dict[str, Any] | None = None
        self._objects: dict[str, dict[str, Any]] = {}
        self._errors: dict[str | None, WapiError] = {}
        self._version = client.wapi_version

    def _check_version(self) -> None:
        if self._version != self.client.wapi_version:
            self._root = None
            self._objects.clear()
            self._errors.clear()
            self._version = self.client.wapi_version

    def root(self) -> dict[str, Any]:
        self._check_version()
        if None in self._errors:
            raise self._errors[None]
        if self._root is None:
            try:
                root = self.client.schema()
                if not isinstance(root, dict) or "Error" in root:
                    raise WapiError("Root schema must be a JSON object without an error envelope")
                supported = root.get("supported_objects")
                if "supported_objects" in root and (not isinstance(supported, list)
                        or not all(isinstance(name, str) and name for name in supported)):
                    raise WapiError("Root schema contains invalid supported_objects")
                self._root = root
            except WapiError as exc:
                self._errors[None] = exc
                raise
        return self._root

    @property
    def supported_objects(self) -> set[str] | None:
        """None means discovery did not declare the list, not zero support."""
        root = self.root()
        return set(root["supported_objects"]) if "supported_objects" in root else None

    def object_schema(self, object_type: str) -> dict[str, Any]:
        self._check_version()
        if object_type in self._errors:
            raise self._errors[object_type]
        if object_type not in self._objects:
            try:
                supported = self.supported_objects
                if supported is not None and object_type not in supported:
                    raise UnsupportedObjectError(f"Object {object_type} is absent from WAPI root schema")
                schema = self.client.schema(object_type)
                index_fields(schema)
                self._objects[object_type] = schema
            except WapiError as exc:
                self._errors[object_type] = exc
                raise
        return self._objects[object_type]


def supported_fields(client: InfobloxClient, object_type: str,
                     requested: list[str]) -> tuple[list[str], str | None]:
    """Select readable fields; never attempt broad fields after schema failure."""
    fields = index_fields(SchemaCache(client).object_schema(object_type))
    available = [name for name in dict.fromkeys(requested)
                 if name in fields and "r" in fields[name].get("supports", "r")]
    missing = [name for name in dict.fromkeys(requested) if name not in available]
    return available, ("Unsupported or unreadable fields: " + ", ".join(missing)) if missing else None


def collect_supported(client: InfobloxClient, object_type: str,
                      fields: list[str]) -> tuple[list[dict[str, Any]], str | None]:
    selected, note = supported_fields(client, object_type, fields)
    # _ref is intrinsic to WAPI results and avoids silently querying basic fields
    # when every requested assessment field is unavailable.
    return client.get_all_objects(object_type, selected or ["_ref"]), note
