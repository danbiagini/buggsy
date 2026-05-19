from server.orchestrator.move_catalog import MoveCatalog


DS1 = "pollen-robotics/reachy-mini-dances-library"
DS2 = "pollen-robotics/reachy-mini-emotions-library"


def test_is_known_only_for_described_entries():
    cat = MoveCatalog(descriptions={
        f"{DS1}/dance_a": "a happy dance",
        f"{DS2}/curious": "curious tilt",
    })
    assert cat.is_known(DS1, "dance_a")
    assert cat.is_known(DS2, "curious")
    assert not cat.is_known(DS1, "missing")
    assert not cat.is_known("unknown/dataset", "dance_a")


def test_total_known_counts_descriptions():
    cat = MoveCatalog(descriptions={
        f"{DS1}/a": "a", f"{DS1}/b": "b", f"{DS2}/c": "c",
    })
    assert cat.total_known() == 3


def test_list_entries_splits_dataset_and_name():
    cat = MoveCatalog(descriptions={
        f"{DS1}/dance_a": "a happy dance",
        f"{DS2}/curious": "curious tilt",
    })
    entries = {(e.dataset, e.name): e.description for e in cat.list_entries()}
    assert entries == {
        (DS1, "dance_a"): "a happy dance",
        (DS2, "curious"): "curious tilt",
    }


def test_empty_catalog():
    cat = MoveCatalog(descriptions={})
    assert cat.total_known() == 0
    assert cat.list_entries() == []
    assert not cat.is_known("anything", "anywhere")


def test_malformed_key_skipped(caplog):
    # Keys with no "/" can't be split into dataset+name; they should be
    # quietly skipped from list_entries (still counted by total_known).
    cat = MoveCatalog(descriptions={"no-slash-key": "x", f"{DS1}/ok": "y"})
    entries = cat.list_entries()
    assert [(e.dataset, e.name) for e in entries] == [(DS1, "ok")]
