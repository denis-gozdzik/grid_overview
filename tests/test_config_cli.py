import pytest
import warnings

from infoblox_inventory import cli
from infoblox_inventory.client import InfobloxClient, WapiError
from infoblox_inventory.config import GridConfig, credentials_from_environment, load_config
from infoblox_inventory.models import CollectionResult
from infoblox_inventory.storage import RawStore, load_raw


def config_file(tmp_path, extra=""):
    config = tmp_path / "grids.yaml"
    config.write_text("grids:\n  - name: grid-a\n    url: https://grid-a.example\n"
                      "    username: readonly\n    password_env: GRID_A_PASSWORD\n" + extra, encoding="utf-8")
    return config


def test_per_grid_password_environment_and_tls_configuration(tmp_path, monkeypatch):
    path = config_file(tmp_path, "    ca_bundle: trusted.pem\n"
                       "  - name: grid-b\n    url: https://grid-b.example/\n"
                       "    password_env: GRID_B_PASSWORD\n    verify_tls: false\n")
    monkeypatch.setenv("GRID_A_PASSWORD", "first-secret")
    monkeypatch.setenv("GRID_B_PASSWORD", "second-secret")
    monkeypatch.setenv("INFOBLOX_PASSWORD", "unrelated-secret")
    monkeypatch.setenv("INFOBLOX_USER", "environment-user")
    grids = load_config(path)
    assert credentials_from_environment(grids[0]) == ("readonly", "first-secret")
    assert credentials_from_environment(grids[1]) == ("environment-user", "second-secret")
    assert grids[0].wapi_version == grids[1].wapi_version == "2.13.7"
    assert grids[0].ca_bundle == "trusted.pem"
    assert grids[1].verify_tls is False
    assert grids[1].url == "https://grid-b.example"
    assert load_config(path, "grid-b") == [grids[1]]


@pytest.mark.parametrize("key", ["password", "wapi-pass", "token"])
def test_config_rejects_plaintext_passwords_without_echoing_them(tmp_path, key):
    path = config_file(tmp_path, f"    {key}: password-never-echo\n")
    with pytest.raises(ValueError) as error:
        load_config(path)
    assert "password-never-echo" not in str(error.value)


@pytest.mark.parametrize("extra", ["    verify_tls: 'false'\n", "    connect_timeout: 0\n", "    read_timeout: .nan\n"])
def test_config_rejects_ambiguous_tls_and_unbounded_timeouts(tmp_path, extra):
    with pytest.raises(ValueError):
        load_config(config_file(tmp_path, extra))


@pytest.mark.parametrize("url", ["http://grid.example", "https://user:password-never-echo@grid.example",
                                 "https://grid.example/wapi/v2.13.7", "https://grid.example?secret=value"])
def test_grid_rejects_credentials_or_non_origin_urls(url):
    with pytest.raises(ValueError) as error:
        GridConfig("grid-a", url)
    assert "password-never-echo" not in str(error.value)


def test_insecure_warns_and_ca_bundle_is_passed_to_session(caplog):
    with InfobloxClient(GridConfig("lab", "https://grid.example", verify_tls=False), "user", "secret") as client:
        assert client.session.verify is False
    assert "TLS certificate verification is disabled" in caplog.text
    assert "secret" not in caplog.text
    with InfobloxClient(GridConfig("prod", "https://grid.example", ca_bundle="private-ca.pem"), "user", "secret") as client:
        assert client.session.verify == "private-ca.pem"


def test_cli_rejects_unknown_collector_before_authentication(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "load_config", lambda *args: pytest.fail("Invalid collector reached configuration"))
    with pytest.raises(SystemExit) as error:
        cli.main(["--config", str(tmp_path / "absent.yaml"), "--collector", "netwroks"])
    assert error.value.code == 2


def test_raw_only_skips_reporting_and_uses_per_grid_credentials(tmp_path, monkeypatch):
    path = config_file(tmp_path, "  - name: grid-b\n    url: https://grid-b.example\n"
                       "    username: second-user\n    password_env: GRID_B_PASSWORD\n")
    monkeypatch.setenv("GRID_A_PASSWORD", "first-secret")
    monkeypatch.setenv("GRID_B_PASSWORD", "second-secret")
    opened = []
    closed = []

    class FakeClient:
        def __init__(self, grid, username, password):
            self.grid = grid
            self.wapi_version = grid.wapi_version
            opened.append((grid.name, username, password, grid.verify_tls))

        def __enter__(self):
            return self

        def __exit__(self, *args):
            closed.append(self.grid.name)

        def detect_version(self):
            return self.wapi_version

    def collect(client, raw_dir, only):
        result = CollectionResult(client.grid.name, wapi_version=client.wapi_version)
        RawStore(raw_dir, result).finish_collection()
        return result

    monkeypatch.setattr(cli, "InfobloxClient", FakeClient)
    monkeypatch.setattr(cli, "collect_grid", collect)
    monkeypatch.setattr(cli, "write_reports", lambda *args: pytest.fail("Raw-only requested reports/normalization"))
    monkeypatch.setattr(cli.getpass, "getpass", lambda *args: pytest.fail("Configured credentials triggered prompting"))
    output = tmp_path / "raw-output"
    assert cli.main(["--config", str(path), "--collect-raw-only", "--insecure", "--output-dir", str(output)]) == 0
    assert opened == [("grid-a", "readonly", "first-secret", False), ("grid-b", "second-user", "second-secret", False)]
    assert closed == ["grid-a", "grid-b"]
    assert len(list(output.glob("raw/*/manifest.json"))) == 2
    assert not list(output.glob("*.xlsx"))


def test_cli_discovery_failure_returns_nonzero_and_saves_failure_evidence(tmp_path, monkeypatch):
    path = config_file(tmp_path)
    monkeypatch.setenv("GRID_A_PASSWORD", "secret")

    class FailedClient:
        def __init__(self, *args):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def detect_version(self):
            raise WapiError("GET / failed: HTTP 403")

    monkeypatch.setattr(cli, "InfobloxClient", FailedClient)
    output = tmp_path / "failed"
    assert cli.main(["--config", str(path), "--collect-raw-only", "--output-dir", str(output)]) == 1
    manifest = output / "raw/grid-a/manifest.json"
    assert manifest.exists()
    assert "403" in manifest.read_text()
    assert "secret" not in manifest.read_text()
    assert cli.main(["--offline", str(output), "--output-dir", str(tmp_path / "offline")]) == 1


def test_cli_preserves_existing_archive_before_attempting_authentication(tmp_path, monkeypatch):
    path = config_file(tmp_path)
    output = tmp_path / "existing"
    store = RawStore(output / "raw", CollectionResult("grid-a"))
    before = (store.path / "manifest.json").read_bytes()
    monkeypatch.setattr(cli, "credentials_from_environment", lambda *args: pytest.fail("Existing archive reached authentication"))
    assert cli.main(["--config", str(path), "--collect-raw-only", "--output-dir", str(output)]) == 1
    assert (store.path / "manifest.json").read_bytes() == before


@pytest.mark.parametrize("with_saved_page", [False, True])
def test_interrupted_archive_replays_available_evidence_with_nonzero_exit(tmp_path, monkeypatch, with_saved_page):
    store = RawStore(tmp_path / "raw", CollectionResult("grid-a"))
    rows = [{"_ref": "networkview/a:default", "name": "default"}]
    if with_saved_page:
        query = store.start_query("networkview", "raw", {"_return_fields": "name"})
        store.save_page(query, 1, {"result": rows, "next_page_id": "never-collected"})
    before = (store.path / "manifest.json").read_bytes()
    replay = load_raw(tmp_path)[0]
    assert replay.errors
    assert any(row["Collection Status"] == "PARTIAL" for row in replay.coverage)
    assert replay.records == ({"networkview": rows} if with_saved_page else {})
    monkeypatch.setattr(cli, "InfobloxClient", lambda *args: pytest.fail("Interrupted replay reached live client"))
    output = tmp_path / "reports"
    assert cli.main(["--offline", str(tmp_path), "--output-dir", str(output)]) == 1
    assert (output / "current_state_inventory.xlsx").is_file()
    assert "interrupted" in (output / "current_state_summary.md").read_text()
    assert (store.path / "manifest.json").read_bytes() == before


def test_password_prompt_refuses_echoing_fallback_before_network_access(tmp_path, monkeypatch, caplog):
    path = config_file(tmp_path)
    monkeypatch.delenv("GRID_A_PASSWORD", raising=False)

    def unsafe_prompt(*args):
        warnings.warn("Cannot disable terminal echo", cli.getpass.GetPassWarning)
        pytest.fail("Password prompt proceeded with echo enabled")

    monkeypatch.setattr(cli.getpass, "getpass", unsafe_prompt)
    monkeypatch.setattr(cli, "InfobloxClient", lambda *args: pytest.fail("Unsafe prompt reached networking"))
    output = tmp_path / "failed-prompt"
    assert cli.main(["--config", str(path), "--collect-raw-only", "--output-dir", str(output)]) == 1
    assert "Secure password prompt unavailable" in caplog.text
    assert load_raw(output)[0].errors


@pytest.mark.parametrize("manifest", [[], None, {"format_version": 1}])
def test_offline_invalid_manifest_returns_failure_without_networking(tmp_path, monkeypatch, manifest):
    import json

    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(cli, "InfobloxClient", lambda *args: pytest.fail("Invalid archive reached networking"))
    assert cli.main(["--offline", str(tmp_path), "--output-dir", str(tmp_path / "reports")]) == 1
