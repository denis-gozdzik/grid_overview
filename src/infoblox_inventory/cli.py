from __future__ import annotations

import argparse
from dataclasses import replace
import getpass
import logging
from pathlib import Path
import warnings

from .client import InfobloxClient
from .config import credentials_from_environment, load_config
from .collectors.core import COLLECTOR_ALIASES, OBJECTS, collect_grid
from .models import CollectionResult
from .report import write_reports
from .storage import RawStore, load_raw, path_component


LOG = logging.getLogger(__name__)


def _secure_password(prompt: str) -> str:
    try:
        with warnings.catch_warnings():
            # getpass otherwise falls back to input that may echo the password.
            warnings.simplefilter("error", getpass.GetPassWarning)
            return getpass.getpass(prompt)
    except (getpass.GetPassWarning, EOFError, OSError):
        raise ValueError("Secure password prompt unavailable; supply the configured password environment variable") from None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Read-only Infoblox NIOS current-state inventory")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--config", help="Multi-Grid YAML configuration for live collection")
    source.add_argument("--offline", "--fixture", metavar="RAW_DIR", action="append",
                        help="Replay saved RAW without network access; repeat to combine collector archives")
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--grid")
    selection.add_argument("--all", action="store_true", help="Collect every configured Grid (the default)")
    parser.add_argument("--collector", choices=sorted(set(COLLECTOR_ALIASES) | set(OBJECTS)))
    parser.add_argument("--test-connection", action="store_true")
    parser.add_argument("--collect-raw-only", action="store_true", help="Save responses and coverage; skip normalization and reports")
    parser.add_argument("--output-dir", default="output")
    parser.add_argument("--decisions", metavar="YAML", help="Human standardization decisions overlaid on reports")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    tls = parser.add_mutually_exclusive_group()
    tls.add_argument("--verify-tls", dest="verify_tls", action="store_true")
    tls.add_argument("--no-verify-tls", "--insecure", dest="verify_tls", action="store_false", help="Disable certificate verification for lab/testing")
    parser.set_defaults(verify_tls=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(level=getattr(logging, args.log_level), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    # Third-party HTTP debug output can contain query tokens; our logs use object names only.
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    if args.offline:
        if args.test_connection or args.collect_raw_only or args.collector or args.verify_tls is not None:
            parser.error("Offline replay cannot be combined with live collection options")
        try:
            results = [result for source in args.offline for result in load_raw(source, args.grid)]
            write_reports(results, args.output_dir, decisions_path=args.decisions)
        except (OSError, ValueError, KeyError) as exc:
            LOG.error("Offline replay failed: %s", exc)
            return 1
        print(f"Wrote offline reports to {args.output_dir}")
        return 1 if any(result.errors for result in results) else 0
    if args.test_connection and args.collect_raw_only:
        parser.error("Choose connection testing or raw collection")
    if args.collect_raw_only and args.decisions:
        parser.error("--decisions applies to report generation and cannot be combined with --collect-raw-only")
    try:
        grids = load_config(args.config, args.grid)
    except (OSError, ValueError) as exc:
        LOG.error("Configuration failed: %s", exc)
        return 1
    results: list[CollectionResult] = []
    prompted_passwords: dict[str, str] = {}
    prompted_username: str | None = None
    failed = False
    for grid in grids:
        if args.verify_tls is not None:
            grid = replace(grid, verify_tls=args.verify_tls,
                           ca_bundle=grid.ca_bundle if args.verify_tls else None)
        if not args.test_connection and (Path(args.output_dir) / "raw" / path_component(grid.name)).exists():
            LOG.error("[%s] raw archive already exists; choose a fresh --output-dir", grid.name)
            failed = True
            continue
        try:
            username, password = credentials_from_environment(grid)
            if not username:
                if prompted_username is None:
                    prompted_username = input("Infoblox username: ")
                username = prompted_username
            if not password:
                if grid.password_env not in prompted_passwords:
                    prompted_passwords[grid.password_env] = _secure_password(f"Infoblox password for {grid.name} ({grid.password_env}): ")
                password = prompted_passwords[grid.password_env]
            with InfobloxClient(grid, username, password) as client:
                version = client.detect_version()
                LOG.info("[%s] WAPI version: %s", grid.name, version)
                if args.test_connection:
                    print(f"[{grid.name}] schema connection OK (WAPI {version}); object permissions not tested")
                    continue
                result = collect_grid(client, str(Path(args.output_dir) / "raw"), args.collector)
                results.append(result)
                failed = failed or bool(result.errors)
        except Exception as exc:
            failed = True
            LOG.error("[%s] collection failed: %s", grid.name, exc)
            result = CollectionResult(grid.name, grid_url=grid.url, wapi_version=grid.wapi_version)
            result.fail("WAPI discovery", "Grid", exc)
            results.append(result)
            if not args.test_connection:
                archive_path = Path(args.output_dir) / "raw" / path_component(grid.name)
                if not archive_path.exists():
                    RawStore(Path(args.output_dir) / "raw", result).finish_collection()
    if results and not args.collect_raw_only and not args.test_connection:
        try:
            write_reports(results, args.output_dir, decisions_path=args.decisions)
        except (OSError, ValueError, KeyError) as exc:
            LOG.error("Report generation failed: %s", exc)
            return 1
        print(f"Wrote reports to {args.output_dir}")
    elif results and args.collect_raw_only:
        print(f"Saved raw collection evidence to {Path(args.output_dir) / 'raw'}")
    return 1 if failed else 0
