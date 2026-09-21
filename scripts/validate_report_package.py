"""Rebuild selected RAW archives offline and verify the serialized report package."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import socket
from unittest.mock import patch

from openpyxl import load_workbook
import requests

from infoblox_inventory.cli import main
from infoblox_inventory.xlsx_validation import validate_xlsx


def _hashes(roots):
    return {str(path.resolve()): hashlib.sha256(path.read_bytes()).hexdigest()
            for root in roots for path in sorted(root.rglob('*')) if path.is_file()}


def _matrix(path):
    workbook = load_workbook(path)
    try:
        return {sheet.title: list(sheet.values) for sheet in workbook}
    finally:
        workbook.close()


def _no_network(*args, **kwargs):
    raise AssertionError('Network calls are forbidden during offline report validation')


def validate(raw_dirs, output):
    roots = [(path / 'raw' if (path / 'raw').is_dir() else path).resolve()
             for path in map(Path, raw_dirs)]
    output = Path(output).resolve()
    if output.exists():
        raise ValueError('Validation output already exists; choose a fresh directory')
    if any(output.is_relative_to(root) for root in roots):
        raise ValueError('Validation output must be outside the input RAW archive')
    before = _hashes(roots)
    arguments = [argument for root in roots for argument in ('--offline', str(root))]
    codes = []
    with patch.object(requests.Session, 'request', _no_network), \
         patch.object(socket, 'create_connection', _no_network), \
         patch.object(socket.socket, 'connect', _no_network):
        for destination in (output, output / 'rebuild'):
            codes.append(main([*arguments, '--output-dir', str(destination)]))
    first = output / 'current_state_inventory.xlsx'
    second = output / 'rebuild/current_state_inventory.xlsx'
    result = validate_xlsx(first)
    validate_xlsx(second)
    if codes[0] != codes[1] or _matrix(first) != _matrix(second):
        raise AssertionError('Offline rebuild differs from the first report')
    for filename in ('current_state_summary.md', 'manual_review.md'):
        if (output / filename).read_bytes() != (output / 'rebuild' / filename).read_bytes():
            raise AssertionError(f'Offline rebuild differs: {filename}')
    if _hashes(roots) != before:
        raise AssertionError('RAW evidence changed during report generation')
    result.update(network_blocked=True, offline_reports_identical=True,
                  raw_files_unchanged=len(before), cli_exit_codes=codes)
    (output / 'validation.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('raw_dirs', nargs='+')
    parser.add_argument('--output-dir', required=True)
    args = parser.parse_args()
    print(json.dumps(validate(args.raw_dirs, args.output_dir), indent=2))
