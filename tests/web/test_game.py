import re
from datetime import datetime, timedelta, timezone

import pytest

from graduapp import create_app
from graduapp.db import repo

TEAM1 = {"team_id": "team-1", "name": "Team 1", "code": "TEAM1-7342"}
HX = {"HX-Request": "true"}
SECRETS = ["4821", "1337", "0420", "TEAM1-7342", "TEAM2-9051"]

# team-1 plays itinerary-a:
#   0 place-bellecour   text location, timed (k=2 of 3, 600 s), code 4821, unlocks selfie-statue
#   1 tour-metallique   maps_link, riddle, code 1337
#   2 place-terreaux    minimap, riddle, code 0420, unlocks fountain-pose
SING, LAMPS, PYRAMID = "bellecour-sing", "bellecour-count-lamps", "bellecour-human-pyramid"


class Player:
    """A phone: logs in, then talks to the game routes like HTMX would."""

    def __init__(self, client, db):
        self.client, self.db, self.pages = client, db, []
        client.post("/join", data=TEAM1)

    def call(self, method, url, **data):
        response = getattr(self.client, method)(url, data=data or None, headers=HX)
        assert response.status_code == 200, (url, response.status_code)
        html = response.get_data(as_text=True)
        self.pages.append(html)
        return html

    def get(self, url):
        return self.call("get", url)

    def post(self, url, **data):
        return self.call("post", url, **data)

    @property
    def state(self):
        return repo.get_view(self.db, "team-1").state

    def start(self):
        return self.post("/game/start")

    def arrive(self, code, step=None):
        step = self.state.step_index if step is None else step
        return self.post("/game/arrive", step_index=step, code=code)

    def tick(self, cid, text="", step=None):
        step = self.state.step_index if step is None else step
        return self.post("/game/tick", step_index=step, challenge_id=cid, text=text)

    def riddle(self, text, step=None):
        step = self.state.step_index if step is None else step
        return self.post("/game/riddle", step_index=step, text=text)


@pytest.fixture
def me(client, db):
    return Player(client, db)


def types(db):
    return [e.type for e in repo.load_events(db, "team-1")]


# Access

def test_game_routes_need_a_team(client):
    for method, url in [("get", "/game/panel"), ("post", "/game/start"), ("get", "/game/arrive")]:
        plain = getattr(client, method)(url)
        assert plain.status_code == 302 and plain.headers["Location"] == "/"
        htmx = getattr(client, method)(url, headers=HX)
        assert htmx.status_code == 200 and htmx.headers["HX-Redirect"] == "/"


# Mode 0 and 1

def test_not_started_shows_a_start_button(me, client):
    html = client.get("/").get_data(as_text=True)
    assert "Team 1" in html and "Start the game" in html and "I am here" not in html


def test_start_shows_the_first_location(me):
    html = me.start()
    assert "Statue of Louis XIV" in html and "I am here" in html
    assert "Location 1 of 3" in html
    assert types(me.db) == ["TEAM_JOINED", "GAME_STARTED"]


def test_start_twice_is_harmless(me):
    me.start()
    html = me.start()  # a double tap: still the true state, no error
    assert "I am here" in html
    assert types(me.db).count("GAME_STARTED") == 1


# Validation-code popup and unlock popup

def test_i_am_here_opens_the_code_popup(me):
    me.start()
    html = me.get("/game/arrive")
    assert 'id="modal"' in html and 'name="code"' in html and 'name="step_index" value="0"' in html


def test_wrong_code_keeps_the_popup_with_an_error(me):
    me.start()
    html = me.arrive("0000")
    assert "Wrong code" in html and 'name="code"' in html
    assert "I am here" in html and me.state.phase.value == "GOING"
    assert types(me.db)[-1] == "CODE_REJECTED"


def test_right_code_shows_the_unlock_popup_and_the_challenges(me):
    me.start()
    html = me.arrive(" 4821 ")
    assert "Location reached!" in html
    assert "New challenges unlocked" in html and "Selfie imitating a statue" in html
    assert "Complete 2 of the 3 challenges" in html
    for text in ("Build a human pyramid", "Sing the national anthem", "Count the lamp posts"):
        assert text in html
    assert 'data-deadline="' in html
    assert re.search(r">(10:00|09:5\d)<", html)  # the 600 s timer, just started
    assert me.state.phase.value == "CHALLENGES"


def test_arrival_without_unlocks_gets_a_simple_success_popup(me):
    me.start()
    me.arrive("4821")
    me.tick(SING)
    me.tick(LAMPS)
    html = me.arrive("1337")  # tour-metallique unlocks nothing
    assert "Location reached!" in html and "New challenges unlocked" not in html


def test_double_arrive_does_not_replay(me):
    me.start()
    me.arrive("4821")
    html = me.arrive("4821", step=0)  # stale second tap
    assert "Challenges" in html
    assert types(me.db).count("ARRIVED") == 1


def test_popup_is_empty_when_arrive_is_not_possible(me):
    html = me.get("/game/arrive")  # not started
    assert 'name="code"' not in html


# Mode 3: challenges, tick popup, untick popup

def test_tick_popup_then_tick(me):
    me.start()
    me.arrive("4821")
    popup = me.get(f"/game/challenge/{SING}")
    assert "Challenge completed" in popup and "Sing the national anthem" in popup
    html = me.tick(SING, "we sang loudly")
    assert "1 / 2 done" in html and "ticked" in html
    assert me.state.step_ticked == {SING}


def test_untick_needs_the_uncompleted_popup(me):
    me.start()
    me.arrive("4821")
    me.tick(SING, "proof text")
    popup = me.get(f"/game/challenge/{SING}")
    assert "Challenge uncompleted" in popup and "proof text" in popup
    html = me.post("/game/untick", step_index=0, challenge_id=SING)
    assert "0 / 2 done" in html and me.state.step_ticked == frozenset()


def test_proof_text_is_escaped(me):
    me.start()
    me.arrive("4821")
    me.tick(SING, "<script>alert(1)</script>")
    popup = me.get(f"/game/challenge/{SING}")
    assert "<script>alert(1)</script>" not in popup and "&lt;script&gt;" in popup


def test_reaching_k_validates_the_location(me):
    me.start()
    me.arrive("4821")
    me.tick(SING)
    html = me.tick(PYRAMID)
    assert "Location validated!" in html
    assert "Fourviere" in html and "https://maps.google.com/?q=45.7624,4.8222" in html
    assert "Open in Google Maps" in html
    assert 'rel="noopener noreferrer"' in html
    assert me.state.step_index == 1


def test_popup_for_a_foreign_or_unknown_challenge_is_refused(me):
    me.start()
    me.arrive("4821")
    for cid in ("c-unknown", "team-photo"):  # unknown, and a general (not step) challenge
        assert 'class="popup"' not in me.get(f"/game/challenge/{cid}")


def test_stale_tick_is_ignored(me):
    me.start()
    me.arrive("4821")
    html = me.tick(SING, step=7)
    assert "0 / 2 done" in html and me.state.step_ticked == frozenset()


# Expiry

def expire(db):
    past = (datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat()
    db.execute("UPDATE team_state SET phase_deadline = ? WHERE team_id = 'team-1'", (past,))
    db.commit()


def test_page_load_after_the_deadline_shows_the_failure_popup(me, client):
    me.start()
    me.arrive("4821")
    me.tick(SING)
    expire(me.db)
    html = client.get("/").get_data(as_text=True)
    assert "Time is up" in html and "Fourviere" in html  # failed, next location given
    assert types(me.db).count("STEP_FAILED") == 1
    assert me.state.step_index == 1


def test_late_tick_reveals_the_failure(me):
    me.start()
    me.arrive("4821")
    expire(me.db)
    html = me.tick(LAMPS)
    assert "Time is up" in html and "Fourviere" in html
    assert types(me.db).count("STEP_FAILED") == 1


# Timer

def test_timer_carries_what_the_script_needs(me, client):
    me.start()
    html = me.arrive("4821")
    assert 'id="timer"' in html and 'data-refresh-url="/game/panel"' in html
    deadline = re.search(r'data-deadline="([^"]+)"', html).group(1)
    server_now = re.search(r'data-server-now="([^"]+)"', html).group(1)
    remaining = datetime.fromisoformat(deadline) - datetime.fromisoformat(server_now)
    assert timedelta(seconds=595) < remaining <= timedelta(seconds=600)
    assert "js/timer.js" in client.get("/").get_data(as_text=True)  # loaded by the full page


def test_panel_route_resolves_expiry_for_the_timer_refresh(me):
    me.start()
    me.arrive("4821")
    expire(me.db)
    html = me.get("/game/panel")  # what the timer asks for when it reaches 0
    assert "Time is up" in html and 'id="timer"' not in html
    assert me.state.step_index == 1


def test_panel_route_before_the_deadline_keeps_the_timer(me):
    me.start()
    me.arrive("4821")
    html = me.get("/game/panel")
    assert 'id="timer"' in html and "Time is up" not in html


# Mode 2 and 4: riddle, minimap, end

def reach_riddle(me):
    me.start()
    me.arrive("4821")
    me.tick(SING)
    me.tick(LAMPS)
    me.arrive("1337")


def test_riddle_mode(me):
    reach_riddle(me)
    html = me.post("/game/riddle", step_index=1, text="   ")
    assert "Riddle" in html and "I have cities but no houses" in html  # empty answer: still here
    assert me.state.step_index == 1
    html = me.riddle("a map")
    assert me.state.step_index == 2
    assert "openstreetmap.org/export/embed.html" in html and "Place des Terreaux" in html
    assert "google.com/maps?q=45.7676,4.8338" in html


def test_full_game_to_the_end_screen(me, db):
    reach_riddle(me)
    me.riddle("a map")
    me.arrive("0420")
    html = me.riddle("Bartholdi")
    assert "You reached the end!" in html and "/brand/flag" in html
    assert me.state.phase.value == "ENDED"
    assert repo.get_score(db, "team-1").steps_succeeded == 3
    assert types(me.db)[-1] == "GAME_ENDED"


# Secrets

def test_no_validation_code_ever_reaches_a_phone(me, client):
    reach_riddle(me)
    me.riddle("a map")
    me.arrive("0420")
    me.get("/game/arrive")
    me.get("/game/panel")
    me.riddle("Bartholdi")
    me.pages.append(client.get("/").get_data(as_text=True))
    for page in me.pages:
        visible = re.sub(r'data-[a-z-]+="[^"]*"', "", page)  # timestamps may contain digits
        for secret in SECRETS:
            assert secret not in visible


def test_step_content_has_no_code_field(me):
    step = repo.get_step_content(me.db, "place-bellecour")
    assert not hasattr(step, "code")


# Media

def test_media_is_served_to_teams_only(db_path, tmp_path):
    images = tmp_path / "images"
    images.mkdir()
    (images / "pic.txt").write_text("hello")
    app = create_app(
        {"TESTING": True, "SECRET_KEY": "k", "DATABASE_PATH": db_path, "CONTENT_DIR": str(tmp_path)}
    )
    client = app.test_client()
    assert client.get("/game/media/pic.txt").status_code == 302  # not logged in
    client.post("/join", data=TEAM1)
    assert client.get("/game/media/pic.txt").get_data(as_text=True) == "hello"
    assert client.get("/game/media/missing.png").status_code == 404
    assert client.get("/game/media/..%2Fsecret.txt").status_code == 404
