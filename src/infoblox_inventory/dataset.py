"""Combine explicitly selected archives without joining unrelated WAPI snapshots."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json

from .models import CollectionResult


def _signature(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


def _unique(rows):
    seen = set()
    result = []
    for row in rows:
        key = _signature(row)
        if key not in seen:
            seen.add(key)
            result.append(deepcopy(row))
    return sorted(result, key=_signature)


def collection_time_utc(value):
    """Parse an explicit timezone without assigning one to ambiguous timestamps."""
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        return None
    return parsed.astimezone(timezone.utc) if parsed.tzinfo is not None else None


def _archive_id(source):
    timestamp = collection_time_utc(source.collected_at)
    identity = {'grid': source.grid, 'url': source.grid_url.rstrip('/'),
                'version': source.wapi_version.removeprefix('v'),
                'collected_at': timestamp.isoformat() if timestamp else source.collected_at,
                'raw': source.records, 'effective': source.effective_records,
                'schemas': source.schemas, 'coverage': _unique(source.coverage),
                'errors': _unique(source.errors)}
    return hashlib.sha256(_signature(identity).encode('utf-8')).hexdigest()


def combine_collections(results: list[CollectionResult]) -> list[CollectionResult]:
    """Merge disjoint object inventories per Grid; reject conflicting snapshots.

    RAW, effective and schema evidence for one object form an indivisible bundle.
    Identical bundles can be deduplicated, but a later empty or failed collection
    never silently replaces earlier data. Source timestamps remain explicit.
    """
    grouped: dict[str, list[CollectionResult]] = {}
    for result in results:
        grouped.setdefault(result.grid, []).append(result)
    combined = []
    for grid, sources in sorted(grouped.items()):
        urls = {source.grid_url.rstrip('/') for source in sources if source.grid_url}
        versions = {source.wapi_version.removeprefix('v') for source in sources if source.wapi_version}
        if len(urls) > 1 or len(versions) > 1:
            raise ValueError(f"Conflicting Grid origin or WAPI version for {grid}; select matching archives")
        result = CollectionResult(grid, grid_url=next(iter(urls), ''),
                                  wapi_version=next(iter(versions), ''), collected_at='')
        bundles = {}
        for source in sources:
            object_types = sorted(set(source.records) | set(source.effective_records) | set(source.schemas))
            source_objects = sorted(set(object_types) | {
                value for value in [*(row.get('Object') for row in source.coverage),
                                    *(row.get('object_type') for row in source.errors)]
                if isinstance(value, str) and value
            })
            for object_type in object_types:
                bundle = {name: mapping[object_type] for name, mapping in (
                    ('raw', source.records), ('effective', source.effective_records), ('schema', source.schemas))
                    if object_type in mapping}
                signature = _signature(bundle)
                if object_type in bundles and bundles[object_type] != signature:
                    raise ValueError(f"Conflicting snapshots for {grid}/{object_type}; "
                                     "select one complete source for this object")
                bundles[object_type] = signature
                for original, target in ((source.records, result.records),
                                         (source.effective_records, result.effective_records),
                                         (source.schemas, result.schemas)):
                    if object_type in original:
                        target[object_type] = deepcopy(original[object_type])
            result.coverage.extend(deepcopy(source.coverage))
            result.errors.extend(deepcopy(source.errors))
            # Existing rows may describe multiple original archives. Keep their
            # identities (or their explicitly unknown legacy identities) intact.
            archive_id = _archive_id(source) if not source.collection_sources else None
            result.collection_sources.extend(deepcopy(source.collection_sources) or [
                {'Grid': grid, 'Object': object_type, 'Collected At': source.collected_at, 'Archive ID': archive_id,
                 'WAPI Version': source.wapi_version,
                 'Raw Count': len(source.records[object_type]) if object_type in source.records else None,
                 'Effective Count': (len(source.effective_records[object_type])
                                     if object_type in source.effective_records else None)}
                for object_type in source_objects or ['']])
        result.collection_sources = _unique(result.collection_sources)
        result.collected_at = '; '.join(sorted({row['Collected At'] for row in result.collection_sources}))
        covered_areas = {row.get('Area') for row in result.coverage if row.get('Object')}
        result.coverage = _unique([row for row in result.coverage if not (
            row.get('Notes') == 'Assessment area is not fully covered by this increment'
            and row.get('Area') in covered_areas)])
        result.errors = _unique(result.errors)
        combined.append(result)
    return combined
