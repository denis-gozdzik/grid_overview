"""Template archetypes keep coarse construction separate from exact variants and review."""
from infoblox_inventory.template_archetypes import build_template_archetype_catalog


def _bundle(
    grid,
    model,
    *,
    status="LINKED",
    family="MS_SERVER",
    association="MS_SERVER",
    prefix="/24",
    network="net",
    range_name="range",
    start="HOST_OFFSET_4",
    end="LAST_USABLE",
    exclusions="offset 248, count 3, end 5 before broadcast",
    options="DISABLED",
    attention="OK",
    flags="",
):
    return {
        "Grid": grid,
        "Bundle Model ID": model,
        "Bundle Status": status,
        "Provisioning Family": family,
        "Network Template": f"{grid}-{network}" if network else "",
        "Network Prefix": prefix,
        "Range Template": f"{grid}-{range_name}" if range_name else "",
        "Range Start": start,
        "Range End": end,
        "Exclusion Pattern": exclusions,
        "Options State": options,
        "Attention": attention,
        "Review Flags": flags,
        "Notes": "",
        "Range Association": association,
        "Fixed Address Templates": "",
    }


def _model(model_id, signature, pattern):
    return {
        "Bundle Model ID": model_id,
        "Model Signature": signature,
        "Pattern Summary": pattern,
    }


def test_exact_variants_collapse_under_coarse_archetype():
    bundles = [
        _bundle("G1", "V1", prefix="/24"),
        _bundle("G2", "V1", prefix="/27"),
        _bundle(
            "G3", "V2", prefix="/24", start="HOST_OFFSET_10",
            end="HOST_OFFSET_239 (16 before broadcast)", exclusions="NONE",
        ),
    ]
    models = [
        _model("V1", "MS_SERVER | /24,/27 | +4→LAST_USABLE", "start +4 → end last usable"),
        _model("V2", "MS_SERVER | /24 | +10→BCAST-16", "start +10 → end 16 before broadcast"),
    ]

    archetypes, variants, instances, grid_map, review = build_template_archetype_catalog(
        bundles, models, ["G1", "G2", "G3"]
    )

    assert len(archetypes) == 1
    archetype = archetypes[0]
    assert archetype["Archetype"] == "Microsoft DHCP — Network + Range"
    assert archetype["Instance Count"] == 3
    assert archetype["Grid Count"] == 3
    assert archetype["Grid Coverage %"] == 100.0
    assert archetype["Commonality"] == "ALL_COLLECTED_GRIDS"
    assert archetype["Variant Count"] == 2
    assert archetype["Prefixes"] == "/24, /27"

    assert len(variants) == 2
    assert {row["Variant ID"] for row in variants} == {"V1", "V2"}
    assert len(instances) == 3
    assert len(grid_map) == 3
    assert review == []


def test_member_and_failover_are_separate_infoblox_archetypes():
    bundles = [
        _bundle("G1", "V1", family="INFOBLOX", association="MEMBER"),
        _bundle("G2", "V2", family="INFOBLOX", association="FAILOVER"),
    ]

    archetypes, _variants, _instances, _grid_map, review = build_template_archetype_catalog(
        bundles, [_model("V1", "x", "x"), _model("V2", "y", "y")], ["G1", "G2"]
    )

    assert {row["Archetype"] for row in archetypes} == {
        "Infoblox DHCP — Network + Range (MEMBER)",
        "Infoblox DHCP — Network + Range (FAILOVER)",
    }
    assert review == []


def test_network_only_is_valid_archetype_but_orphan_and_mismatch_are_review_only():
    bundles = [
        _bundle(
            "G1", "V1", status="NETWORK_ONLY", family="INFOBLOX_MEMBER",
            association="", range_name="", start="", end="", exclusions="",
        ),
        _bundle(
            "G2", "ORPHAN", status="ORPHAN_RANGE_TEMPLATE", family="ORPHAN_FAILOVER",
            association="FAILOVER", network="", attention="REVIEW",
        ),
        _bundle(
            "G3", "MIXED", family="MIXED_OR_INCONSISTENT", association="NONE",
            attention="REVIEW", flags="NETWORK_RANGE_ASSOCIATION_MISMATCH",
        ),
    ]

    archetypes, variants, instances, grid_map, review = build_template_archetype_catalog(
        bundles, [_model("V1", "x", "x")], ["G1", "G2", "G3"]
    )

    assert len(archetypes) == 1
    assert archetypes[0]["Archetype"] == "Infoblox DHCP — Network Only"
    assert archetypes[0]["Commonality"] == "GRID_SPECIFIC"
    assert len(variants) == 1
    assert len(instances) == 1
    assert len(grid_map) == 1
    assert {row["Issue"] for row in review} == {
        "ORPHAN_RANGE_TEMPLATE",
        "NETWORK_RANGE_ASSOCIATION_MISMATCH",
    }
