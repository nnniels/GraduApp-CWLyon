"""Screen C: the B/C toggle, the general challenges, the NEW badge, the mini-timer."""
from datetime import datetime, timedelta, timezone

import pytest

from graduapp.db import repo

from .test_game import LAMPS, SECRETS, SING, Player, expire, types

PAST = lambda: datetime.now(timezone.utc) - timedelta(minutes=1)
FUTURE = lambda: datetime.now(timezone.utc) + timedelta(hours=1)
MODAL_EMPTY = '<div id="modal" hx-swap-oob="true"></div>'


@pytest.fixture
def me(client, db):
    return Player(client, db)


def show(me, name):
    return me.post("/game/view", view=name)


def tick_general(me, cid, text=""):
    return me.post("/game/general/tick", challenge_id=cid, text=text)


def play_to_the_end(me):
    me.start()
    me.arrive("4821")
    me.tick(SING)
    me.tick(LAMPS)
    me.arrive("1337")
    me.riddle("a map")
    me.arrive("0420")
    me.riddle("Bartholdi")


# Toggle

def test_no_toggle_before_the_game_starts(me, client):
    html = client.get("/").get_data(as_text=True)
    assert "Start the game" in html and 'class="toggle"' not in html
    html = show(me, "c")  # even if asked, there is only one screen yet
    assert "Start the game" in html and "To do" not in html


def test_toggle_appears_once_started(me):
    html = me.start()
    assert 'class="toggle"' in html and "Itinerary" in html and "Challenges" in html


def test_c_lists_only_the_unlocked_challenges(me):
    me.start()
    html = show(me, "c")
    assert "To do (2)" in html and "Done (0)" in html
    assert "Take a team photo" in html and "street musician" in html
    assert "Selfie imitating" not in html and "Pose like the fountain" not in html
    assert "I am here" not in html  # screen B content is not rendered


def test_the_view_survives_reloads_and_refreshes(me, client):
    me.start()
    show(me, "c")
    assert "To do (2)" in client.get("/").get_data(as_text=True)
    assert "To do (2)" in me.get("/game/panel")  # what the timer asks for
    assert "I am here" in show(me, "b")
    assert "I am here" in client.get("/").get_data(as_text=True)


def test_unknown_view_falls_back_to_b(me):
    me.start()
    assert "I am here" in show(me, "zzz")


def test_toggle_requires_a_team(client):
    assert client.post("/game/view", data={"view": "c"}).status_code == 302


# NEW badge

def test_new_badge_lifecycle(me):
    html = me.start()
    assert "2 new" in html  # the two challenges open from the start

    html = show(me, "c")
    assert html.count('class="new"') == 2 and 'class="badge"' not in html
    assert me.state.general_ticked == frozenset()  # looking is not ticking

    html = show(me, "b")
    assert 'class="badge"' not in html  # leaving C marks everything as seen
    assert repo.get_seen_general(me.db, "team-1") == {"team-photo", "street-musician"}

    html = me.arrive("4821")  # unlocks selfie-statue
    assert "1 new" in html
    html = show(me, "c")
    assert html.count('class="new"') == 1
    assert 'Selfie imitating a statue <span class="new">NEW</span>' in html
    assert 'class="badge"' not in show(me, "b")


def test_new_stays_until_the_team_leaves_c(me, client):
    me.start()
    show(me, "c")
    assert client.get("/").get_data(as_text=True).count('class="new"') == 2  # reload keeps it


def test_new_survives_a_phone_swap(me, client, app):
    me.start()
    show(me, "c")
    show(me, "b")
    other_phone = app.test_client()
    other_phone.post("/join", data={"team_id": "team-1", "name": "Team 1", "code": "TEAM1-7342"})
    html = other_phone.get("/").get_data(as_text=True)
    assert 'class="badge"' not in html  # seen state is stored for the team, not the phone


# Ticking general challenges

def test_tick_and_untick_a_general_challenge(me):
    me.start()
    show(me, "c")
    popup = me.get("/game/general/team-photo")
    assert "Challenge completed" in popup and "Take a team photo" in popup

    html = tick_general(me, "team-photo", "with a baker")
    assert "Done (1)" in html and "To do (1)" in html
    assert MODAL_EMPTY in html and 'class="popup"' not in html
    assert me.state.general_ticked == {"team-photo"}
    ticked = [e for e in repo.load_events(me.db, "team-1") if e.type == "CHALLENGE_TICKED"]
    assert ticked[0].payload == {"scope": "general", "challenge_id": "team-photo", "text": "with a baker"}

    popup = me.get("/game/general/team-photo")
    assert "Challenge uncompleted" in popup and "with a baker" in popup
    html = me.post("/game/general/untick", challenge_id="team-photo")
    assert "Done (0)" in html and "To do (2)" in html
    assert me.state.general_ticked == frozenset()
    assert types(me.db)[-1] == "CHALLENGE_UNTICKED"


def test_note_is_escaped(me):
    me.start()
    show(me, "c")
    tick_general(me, "team-photo", "<script>alert(1)</script>")
    popup = me.get("/game/general/team-photo")
    assert "<script>alert(1)</script>" not in popup and "&lt;script&gt;" in popup


def test_locked_challenges_cannot_be_opened_or_ticked(me):
    me.start()
    show(me, "c")
    assert 'class="popup"' not in me.get("/game/general/selfie-statue")  # locked until step 0
    tick_general(me, "selfie-statue")
    assert me.state.general_ticked == frozenset()
    assert 'class="popup"' not in me.get("/game/general/nope")


def test_nothing_can_be_ticked_before_the_start(me):
    tick_general(me, "team-photo")
    assert me.state.general_ticked == frozenset()
    assert 'class="popup"' not in me.get("/game/general/team-photo")


def test_a_step_challenge_is_not_a_general_challenge(me):
    me.start()
    me.arrive("4821")
    show(me, "c")
    tick_general(me, SING)  # a step challenge id sent to the general route
    assert me.state.general_ticked == frozenset() and me.state.step_ticked == frozenset()
    assert 'class="popup"' not in me.get(f"/game/general/{SING}")


# The deadline set by the organiser

def test_after_the_general_deadline_c_is_read_only(me):
    me.start()
    tick_general(me, "team-photo")
    repo.set_general_deadline(me.db, PAST())
    html = show(me, "c")
    assert "closed" in html and "hx-get" not in html  # nothing can be opened any more
    assert "Take a team photo" in html and "Done (1)" in html  # but the list is still readable
    assert 'class="popup"' not in me.get("/game/general/street-musician")
    tick_general(me, "street-musician")
    assert me.state.general_ticked == {"team-photo"}


def test_before_the_general_deadline_c_is_open(me):
    me.start()
    repo.set_general_deadline(me.db, FUTURE())
    show(me, "c")
    assert "closed" not in tick_general(me, "team-photo")
    assert me.state.general_ticked == {"team-photo"}


# Mini-timer

def test_mini_timer_is_shown_in_c_during_a_timed_step(me):
    me.start()
    me.arrive("4821")
    b = show(me, "b")
    assert b.count('id="timer"') == 1 and "timer mini" not in b
    c = show(me, "c")
    assert c.count('id="timer"') == 1 and 'class="timer mini"' in c
    assert "Location challenges: time left" in c and 'data-refresh-url="/game/panel"' in c


def test_no_mini_timer_outside_a_timed_step(me):
    me.start()
    assert 'id="timer"' not in show(me, "c")


def test_the_timer_refresh_in_c_shows_the_failure_and_stays_in_c(me):
    me.start()
    me.arrive("4821")
    show(me, "c")
    expire(me.db)
    html = me.get("/game/panel")  # what the mini-timer calls at zero
    assert "Time is up" in html and 'id="timer"' not in html
    assert "To do (3)" in html and me.state.step_index == 1  # 2 from the start + the unlocked selfie


def test_ticking_general_challenges_does_not_disturb_a_timed_step(me):
    me.start()
    me.arrive("4821")
    show(me, "c")
    html = tick_general(me, "team-photo")
    assert 'id="timer"' in html
    assert me.state.phase.value == "CHALLENGES" and me.state.step_ticked == frozenset()
    assert me.state.phase_deadline is not None


# After the end, and secrets

def test_c_stays_usable_after_the_end(me):
    play_to_the_end(me)
    assert me.state.phase.value == "ENDED"
    html = show(me, "c")
    assert 'class="toggle"' in html
    assert "Selfie imitating a statue" in html and "Pose like the fountain" in html  # all unlocked
    tick_general(me, "fountain-pose", "done")
    assert me.state.general_ticked == {"fountain-pose"}
    assert "You reached the end!" in show(me, "b")


def test_screen_c_leaks_no_validation_code(me, client):
    play_to_the_end(me)
    pages = [show(me, "c"), me.get("/game/general/team-photo"), client.get("/").get_data(as_text=True)]
    for page in pages:
        for secret in SECRETS:
            assert secret not in page
