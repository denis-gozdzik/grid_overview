from copy import deepcopy

import pytest
import responses

from infoblox_inventory.client import InfobloxClient, WapiError
from infoblox_inventory.config import GridConfig
from infoblox_inventory.schema import (
    SchemaCache, UnsupportedObjectError, collect_supported, index_fields,
    override_relationships, supported_fields,
)

BASE = "https://grid.example/wapi/v2.13.7"
SCHEMA = {"fields": [
    {"name": "network", "supports": "rwu"},
    {"name": "nextserver", "supports": "rwu", "overridden_by": "use_nextserver"},
    {"name": "use_nextserver", "supports": "rwu"},
    {"name": "search_only", "supports": "s"},
    {"name": "without_override", "supports": "r"},
]}


def client():
    return InfobloxClient(GridConfig("test", "https://grid.example", "2.13.7"), "user", "secret")


def root_schema(objects=None):
    responses.add(responses.GET, BASE + "/", json={"supported_objects": objects if objects is not None else ["network"]})


def test_indexes_field_dictionaries_and_only_declared_overrides():
    original = deepcopy(SCHEMA)
    fields = index_fields(SCHEMA)
    assert fields["nextserver"]["overridden_by"] == "use_nextserver"
    assert override_relationships(SCHEMA) == {"nextserver": "use_nextserver"}
    assert SCHEMA == original


@pytest.mark.parametrize("schema", [
    {}, {"fields": {}}, {"fields": ["nextserver"]}, {"fields": [None]},
    {"fields": [{}]}, {"fields": [{"name": ""}]},
    {"fields": [{"name": "a"}, {"name": "a"}]},
    {"fields": [{"name": "a", "supports": []}]},
    {"fields": [{"name": "a", "overridden_by": None}]},
])
def test_invalid_field_schema_is_error_not_unsupported(schema):
    with pytest.raises(WapiError):
        index_fields(schema)


@responses.activate
def test_root_and_object_schemas_are_cached_and_raw_is_unchanged():
    root_schema()
    responses.add(responses.GET, BASE + "/network", json=SCHEMA)
    cache = SchemaCache(client())
    assert cache.supported_objects == {"network"}
    assert cache.object_schema("network") == SCHEMA
    assert cache.object_schema("network") == SCHEMA
    assert cache.root() == {"supported_objects": ["network"]}
    assert len(responses.calls) == 2


@responses.activate
def test_object_absent_from_root_is_distinguished_without_probe():
    root_schema(["network"])
    cache = SchemaCache(client())
    with pytest.raises(UnsupportedObjectError, match="absent"):
        cache.object_schema("range")
    assert len(responses.calls) == 1


@responses.activate
def test_empty_supported_objects_list_means_no_objects():
    root_schema([])
    cache = SchemaCache(client())
    assert cache.supported_objects == set()
    with pytest.raises(UnsupportedObjectError):
        cache.object_schema("network")
    assert len(responses.calls) == 1


@responses.activate
def test_missing_supported_objects_list_is_unknown_not_absence():
    responses.add(responses.GET, BASE + "/", json={"supported_versions": ["2.13.7"]})
    responses.add(responses.GET, BASE + "/network", json=SCHEMA)
    cache = SchemaCache(client())
    assert cache.supported_objects is None
    assert cache.object_schema("network") == SCHEMA


@responses.activate
@pytest.mark.parametrize("objects", [None, {}, "network", [None], [""]])
def test_malformed_root_object_list_is_schema_error(objects):
    responses.add(responses.GET, BASE + "/", json={"supported_objects": objects})
    with pytest.raises(WapiError) as error:
        SchemaCache(client()).object_schema("network")
    assert not isinstance(error.value, UnsupportedObjectError)
    assert len(responses.calls) == 1


@responses.activate
def test_root_discovery_permission_error_does_not_probe_object():
    responses.add(responses.GET, BASE + "/", status=403)
    with pytest.raises(WapiError, match="HTTP 403") as error:
        collect_supported(client(), "network", ["network", "nextserver"])
    assert not isinstance(error.value, UnsupportedObjectError)
    assert len(responses.calls) == 1


@responses.activate
def test_object_schema_permission_error_does_not_trigger_broad_collection():
    root_schema()
    responses.add(responses.GET, BASE + "/network", status=403)
    with pytest.raises(WapiError, match="HTTP 403") as error:
        collect_supported(client(), "network", ["network", "nextserver"])
    assert not isinstance(error.value, UnsupportedObjectError)
    assert len(responses.calls) == 2


@responses.activate
def test_malformed_object_schema_does_not_trigger_broad_collection():
    root_schema()
    responses.add(responses.GET, BASE + "/network", json={})
    with pytest.raises(WapiError, match="fields list"):
        collect_supported(client(), "network", ["network", "nextserver"])
    assert len(responses.calls) == 2


@responses.activate
def test_supported_fields_filters_absent_and_unreadable_fields_in_requested_order():
    root_schema()
    responses.add(responses.GET, BASE + "/network", json=SCHEMA)
    selected, note = supported_fields(client(), "network",
                                     ["nextserver", "network", "missing", "search_only", "nextserver"])
    assert selected == ["nextserver", "network"]
    assert "missing" in note and "search_only" in note


@responses.activate
def test_schema_cache_is_invalidated_when_explicit_version_changes():
    root_schema()
    api = client()
    cache = SchemaCache(api)
    assert cache.supported_objects == {"network"}
    api.wapi_version = "2.13.6"
    responses.add(responses.GET, "https://grid.example/wapi/v2.13.6/", json={"supported_objects": ["range"]})
    assert cache.supported_objects == {"range"}


@responses.activate
def test_no_supported_fields_uses_only_reference_and_reports_gaps():
    root_schema()
    responses.add(responses.GET, BASE + "/network", json={"fields": []})
    responses.add(responses.GET, BASE + "/network", json={"result": [{"_ref": "network/a"}]})
    rows, note = collect_supported(client(), "network", ["nextserver"])
    assert rows == [{"_ref": "network/a"}]
    assert "nextserver" in note
    assert "_return_fields=_ref" in responses.calls[-1].request.url


@responses.activate
def test_root_failure_is_cached_for_entire_collection():
    responses.add(responses.GET, BASE + "/", status=403)
    cache = SchemaCache(client())
    for object_type in [None, "network", "range", "member"]:
        with pytest.raises(WapiError, match="HTTP 403"):
            cache.object_schema(object_type) if object_type else cache.root()
    assert len(responses.calls) == 1


@responses.activate
def test_object_schema_failure_is_cached():
    root_schema()
    responses.add(responses.GET, BASE + "/network", status=403)
    cache = SchemaCache(client())
    for _ in range(2):
        with pytest.raises(WapiError, match="HTTP 403"):
            cache.object_schema("network")
    assert len(responses.calls) == 2
