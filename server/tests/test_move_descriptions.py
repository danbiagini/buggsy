from server.orchestrator.move_descriptions import load_packaged_descriptions

DS_DANCES = "pollen-robotics/reachy-mini-dances-library"
DS_EMOTIONS = "pollen-robotics/reachy-mini-emotions-library"


def test_loads_packaged_dances():
    out = load_packaged_descriptions([DS_DANCES])
    # Spot-check a known curated entry.
    assert f"{DS_DANCES}/simple_nod" in out
    assert "nod" in out[f"{DS_DANCES}/simple_nod"].lower()
    # Every key is fully qualified with the dataset prefix.
    assert all(k.startswith(DS_DANCES + "/") for k in out)


def test_loads_packaged_emotions_and_excludes_negatives():
    out = load_packaged_descriptions([DS_EMOTIONS])
    # Positive entries are present.
    assert f"{DS_EMOTIONS}/welcoming1" in out
    assert f"{DS_EMOTIONS}/curious1" in out
    # Office-persona-inappropriate entries are intentionally NOT shipped.
    for excluded in ["rage1", "furious1", "contempt1", "dying1", "go_away1"]:
        assert f"{DS_EMOTIONS}/{excluded}" not in out


def test_unknown_dataset_silently_skipped():
    out = load_packaged_descriptions(["someone/nonexistent-dataset"])
    assert out == {}


def test_multiple_datasets_merge():
    out = load_packaged_descriptions([DS_DANCES, DS_EMOTIONS])
    # Entries from both datasets show up, namespaced by their prefix.
    dance_keys = [k for k in out if k.startswith(DS_DANCES)]
    emotion_keys = [k for k in out if k.startswith(DS_EMOTIONS)]
    assert dance_keys and emotion_keys
    # Sanity: total matches the sum of the individual loads.
    only_dances = load_packaged_descriptions([DS_DANCES])
    only_emotions = load_packaged_descriptions([DS_EMOTIONS])
    assert len(out) == len(only_dances) + len(only_emotions)
