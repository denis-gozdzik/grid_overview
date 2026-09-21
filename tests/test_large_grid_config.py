import pytest

from infoblox_inventory.config import GridConfig, load_config


def write_config(tmp_path, extra=""):
    path = tmp_path / "grids.yaml"
    path.write_text(
        "grids:\n  - name: grid-a\n    url: https://grid-a.example\n" + extra,
        encoding="utf-8",
    )
    return path


def test_default_page_size_and_timeouts_preserve_existing_configs(tmp_path):
    direct = GridConfig("grid-a", "https://grid-a.example")
    loaded = load_config(write_config(tmp_path))[0]
    assert direct == loaded
    assert loaded.page_size == 250
    assert loaded.timeout == (10.0, 60.0)


@pytest.mark.parametrize("page_size", [1, 125, 250, 1000])
def test_explicit_page_size_is_loaded_without_coercion(tmp_path, page_size):
    loaded = load_config(write_config(tmp_path, f"    page_size: {page_size}\n"))[0]
    assert loaded.page_size == page_size
    assert isinstance(loaded.page_size, int)


@pytest.mark.parametrize("page_size", [0, -1, 1001, 10**50, True, False, 250.0, 1.5, "250", None, [], {}])
def test_grid_rejects_invalid_page_size(page_size):
    with pytest.raises(ValueError, match="page_size must be an integer between 1 and 1000"):
        GridConfig("grid-a", "https://grid-a.example", page_size=page_size)


@pytest.mark.parametrize("yaml_value", ["0", "-1", "1001", "true", "false", "250.0", "'250'", "null", "[]", "{}"])
def test_yaml_rejects_invalid_page_size_with_clear_error(tmp_path, yaml_value):
    with pytest.raises(ValueError, match="page_size must be an integer between 1 and 1000"):
        load_config(write_config(tmp_path, f"    page_size: {yaml_value}\n"))


def test_timeout_configuration_keeps_independent_explicit_values(tmp_path):
    loaded = load_config(write_config(tmp_path, "    connect_timeout: 3.5\n    read_timeout: 120\n"))[0]
    assert loaded.timeout == (3.5, 120)


@pytest.mark.parametrize("key", ["connect_timeout", "read_timeout"])
@pytest.mark.parametrize("yaml_value", ["0", "-1", ".inf", "-.inf", ".nan", "true", "'60'", "null", "[]", "{}"])
def test_yaml_rejects_invalid_timeout_values(tmp_path, key, yaml_value):
    with pytest.raises(ValueError, match="timeouts must be finite positive numbers"):
        load_config(write_config(tmp_path, f"    {key}: {yaml_value}\n"))


@pytest.mark.parametrize("timeout", [None, 60, "60", {}, {1, 2}, (), (10,), (10, 60, 90), (True, 60), (10, None)])
def test_grid_rejects_malformed_timeout_structure_with_value_error(timeout):
    with pytest.raises(ValueError, match="timeouts must be finite positive numbers"):
        GridConfig("grid-a", "https://grid-a.example", timeout=timeout)


def test_existing_positional_grid_configuration_remains_compatible():
    grid = GridConfig("grid-a", "https://grid-a.example", "2.13.7", True, None, (5, 90), "reader", "GRID_PASSWORD")
    assert grid.timeout == (5, 90)
    assert grid.username == "reader"
    assert grid.password_env == "GRID_PASSWORD"
    assert grid.page_size == 250


def test_example_configuration_has_explicit_safe_collection_defaults():
    from pathlib import Path

    example = Path(__file__).resolve().parents[1] / "config" / "grids.example.yaml"
    grids = load_config(example)
    assert len(grids) == 2
    assert all(grid.page_size == 250 and grid.timeout == (10, 60) for grid in grids)
