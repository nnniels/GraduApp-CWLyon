import copy
from pathlib import Path

import pytest

from graduapp.content.loader import load_content
from graduapp.content.schema import ContentError, build_content

CONTENT_DIR = Path(__file__).resolve().parents[2] / "content"


def raw():
    """Minimal valid raw content, deep-copied so each test can break one thing."""
    return copy.deepcopy(
        dict(
            steps_raw=[
                {
                    "id": "s1",
                    "location": {"kind": "text", "text": "Here"},
                    "code": "1111",
                    "unlocks": ["g1"],
                    "challenges": {"k": 1, "duration_s": 60, "items": [{"id": "c1", "text": "Do it"}]},
                },
                {
                    "id": "s2",
                    "location": {"kind": "minimap", "lat": 45.0, "lon": 4.0},
                    "code": "2222",
                    "riddle": {"text": "Riddle?"},
                },
            ],
            general_raw=[{"id": "g1", "text": "General", "unlocked_at_start": True}],
            itineraries_raw=[{"id": "it", "title": "It", "steps": ["s1", "s2"]}],
            teams_raw=[{"id": "t1", "name": "T1", "itinerary": "it", "join_code": "J1"}],
        )
    )


def test_real_content_is_valid():
    content = load_content(CONTENT_DIR)
    assert content.teams and content.itineraries and content.steps


def test_minimal_content_is_valid():
    content = build_content(**raw())
    assert content.steps["s1"].challenges.k == 1
    assert content.steps["s2"].riddle.text == "Riddle?"


def break_it(mutate):
    data = raw()
    mutate(data)
    with pytest.raises(ContentError) as exc:
        build_content(**data)
    return "\n".join(exc.value.errors)


def test_k_greater_than_items():
    assert "'k'" in break_it(lambda d: d["steps_raw"][0]["challenges"].update(k=2))


def test_riddle_and_challenges_together():
    msg = break_it(lambda d: d["steps_raw"][0].update(riddle={"text": "x"}))
    assert "exactly one" in msg


def test_neither_riddle_nor_challenges():
    assert "exactly one" in break_it(lambda d: d["steps_raw"][1].pop("riddle"))


def test_dangling_unlock():
    assert "unknown general challenge 'nope'" in break_it(
        lambda d: d["steps_raw"][0].update(unlocks=["nope"])
    )


def test_unknown_step_in_itinerary():
    assert "unknown step 'zzz'" in break_it(lambda d: d["itineraries_raw"][0]["steps"].append("zzz"))


def test_duplicate_challenge_id_across_scopes():
    assert "duplicate challenge id" in break_it(
        lambda d: d["general_raw"].append({"id": "c1", "text": "Clash"})
    )


def test_unquoted_numeric_code_rejected():
    assert "quoted" in break_it(lambda d: d["steps_raw"][0].update(code=123))


def test_typo_in_key_rejected():
    assert "unknown key 'unlock'" in break_it(lambda d: d["steps_raw"][0].update(unlock=["g1"]))


def test_unknown_team_itinerary():
    assert "unknown itinerary" in break_it(lambda d: d["teams_raw"][0].update(itinerary="x"))


def test_duplicate_join_code():
    assert "duplicate join_code" in break_it(
        lambda d: d["teams_raw"].append({"id": "t2", "name": "T2", "itinerary": "it", "join_code": "J1"})
    )


def test_bad_location():
    assert "location" in break_it(lambda d: d["steps_raw"][1]["location"].pop("lat"))


def test_javascript_url_is_rejected():
    msg = break_it(
        lambda d: d["steps_raw"][1].update(location={"kind": "maps_link", "url": "javascript:alert(1)"})
    )
    assert "http" in msg


def test_errors_are_collected():
    def mutate(d):
        d["steps_raw"][0]["challenges"]["k"] = 9
        d["teams_raw"][0]["itinerary"] = "x"

    data = raw()
    mutate(data)
    with pytest.raises(ContentError) as exc:
        build_content(**data)
    assert len(exc.value.errors) >= 2
