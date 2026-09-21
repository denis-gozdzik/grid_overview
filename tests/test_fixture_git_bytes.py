"""Real Git clean/checkout operations must preserve original captured evidence bytes."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest


REPOSITORY = Path(__file__).resolve().parents[1]
CAPTURE_NAMES = ("live_lab_20260920", "topology_lab_20260920", "reservations_lab_20260920")


def _git(directory, *arguments):
    # Use only the isolated repository; inherited Git routing/configuration must
    # not redirect the command to the developer's actual repository or index.
    environment = {key: value for key, value in os.environ.items() if not key.upper().startswith("GIT_")}
    environment.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull, GIT_ATTR_NOSYSTEM="1")
    command = [shutil.which("git") or "git", "-c", f"core.attributesFile={os.devnull}",
               "-c", "core.safecrlf=false", *arguments]
    result = subprocess.run(command, cwd=directory, env=environment, check=True, capture_output=True)
    return result.stdout


def _evidence_hashes(directory):
    expected = {}
    for capture_name in CAPTURE_NAMES:
        capture = directory / "tests" / "fixtures" / capture_name
        provenance = json.loads((capture / "provenance.json").read_text(encoding="utf-8"))
        for relative, digest in provenance["sha256"].items():
            path = capture / relative
            assert hashlib.sha256(path.read_bytes()).hexdigest() == digest
            expected[path.relative_to(directory).as_posix()] = digest
    return expected


@pytest.mark.skipif(shutil.which("git") is None, reason="Git is required to test Git line-ending conversions")
@pytest.mark.parametrize("autocrlf,eol", [("true", "crlf"), ("false", "lf")])
def test_captured_evidence_survives_clean_and_checkout_for_platform_newline_modes(tmp_path, autocrlf, eol):
    isolated = tmp_path / "fixture-repository"
    isolated.mkdir()
    shutil.copyfile(REPOSITORY / ".gitattributes", isolated / ".gitattributes")
    for name in CAPTURE_NAMES:
        capture = isolated / "tests" / "fixtures" / name
        shutil.copytree(REPOSITORY / "tests" / "fixtures" / name, capture)
        # Both newline styles must be preserved, independent of the captured
        # files' current style. Probes exist only in this temporary repository.
        for newline, suffix in ((b"\n", "lf"), (b"\r\n", "crlf")):
            (capture / f"synthetic-{suffix}.json").write_bytes(newline.join([b'{', b'  "synthetic": true', b'}', b'']))
    expected_hashes = _evidence_hashes(isolated)
    assert len(expected_hashes) == 49
    originals = {path.relative_to(isolated).as_posix(): path.read_bytes()
                 for path in (isolated / "tests" / "fixtures").rglob("*.json")}
    _git(isolated, "init", "--quiet", "--object-format=sha1")
    settings = ("-c", f"core.autocrlf={autocrlf}", "-c", f"core.eol={eol}")
    _git(isolated, *settings, "add", "--", ".gitattributes", "tests/fixtures")
    index = {}
    for line in _git(isolated, "ls-files", "--stage").decode("utf-8").splitlines():
        metadata, path = line.split("\t", 1)
        index[path] = metadata.split()[1]
    for path, original in originals.items():
        blob = f"blob {len(original)}\0".encode() + original
        assert index[path] == hashlib.sha1(blob).hexdigest(), f"Git clean changed captured bytes: {path}"
    # Damage only copied files to prove the checkout actually rewrites them.
    for path in originals:
        (isolated / path).write_bytes(b"temporary checkout marker\n")
    _git(isolated, *settings, "checkout-index", "--all", "--force")
    for path, original in originals.items():
        assert (isolated / path).read_bytes() == original, f"Git checkout changed captured bytes: {path}"
    assert _evidence_hashes(isolated) == expected_hashes
