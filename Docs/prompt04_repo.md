The repo layer in `db/repo.py` is written, and the full suite passes (84 tests). That completes the plan up to milestone M1: you can play a whole game from pytest.

**What it does**
- **`apply_action(conn, team_id, action, now)`** loads the team's course and state, calls the engine, and saves the new state, the events and the tick records. All of it runs in one transaction.
- **`resolve_team(conn, team_id, now)`** saves a timed-out step. The web layer will call it on every page load.
- **`load_course`** turns the content tables into the engine's `Course`.
- **`get_view`, `load_events` and `get_score`** supply what a screen needs to render.
- **Teams:** `list_teams`, `get_team`, `check_join_code` and `rename_team` serve screen A.
- **`get/set_general_deadline`** store the organiser's cutoff in a new `game_setting` table.

**Safety properties, all tested**
- **A double tap applies once.** Two connections race on a real file database, and exactly one request is applied while the other is refused. This works because each write takes the database write lock up front.
- **A refused late request still saves the failed step.** The step is recorded as failed before the refusal is reported.
- **A wrong code is logged** and the state is unchanged.
- **Join codes never leave the repo.** The team list has no code field, and codes are compared in constant time, ignoring case and surrounding spaces.
- **Naive datetimes are rejected.** All times are stored as UTC.

I updated `Datamodel.md` with the new table and the repo rules. The `general_deadline` question in `state_machine.md` is now closed.

**Not done yet**
- **Content loading:** `load_course` runs several queries on every request. That is fine for 5 teams, and it can be cached later.
- **Rate limiting:** the 10-attempt team-creation limit and the wrong-code throttling belong to the web layer.

Next is the web layer: signed team cookie, screen A with the join-code check and rate limit, then screen B. I'd build screen A first. Shall I proceed?



<span style="color:#99BBFF">

Let's pause for a minute and recap. Our plan was the following :
Build a **vertical slice first**: one team, one hard-coded itinerary, playable end to end on a phone. Then widen. Don't build all of the data model, then all of the UI.

## Work packages

| # | Package | Content |
|---|---|---|
| 0 | **Skeleton & infra** | Repo layout, venv, Flask app factory, SQLite with WAL, gunicorn, `.env` for secrets, base Jinja layout (mobile CSS), HTMX vendored locally (no CDN). |
| 1 | **Content & data model** | YAML schema, loader and validator, DB tables (Team, TeamState, Event, ChallengeCompletion), seed script. |
| 2 | **Game engine** (pure Python, no HTTP) | State machine: `going → (riddle | challenges) → next step → end`. Functions like `arrive(code)`, `submit_riddle()`, `tick_challenge()`, `expire()`. Atomic transitions, an event log entry for each, and server-side deadlines. |
| 3 | **Tests of the engine** | pytest: nominal path, k of n success, timeout failure, double-submit, wrong code, unlock logic. |
| 4 | **Team identity** | Screen A, join code check, signed session cookie, and the team lock. |
| 5 | **Screen B** | Four modes as HTMX partials, the validation-code popup, and the unlock popup. |
| 6 | **Timer** | Client countdown from a server deadline, clock offset, server-side expiry on every request, and a mini-timer visible in C. |
| 7 | **Screen C** | General challenges, tick/undo popups, and a "NEW" badge on unlocked ones. |
| 8 | **Organiser view (D)** | Password-protected. Team progress, answers, the event log, and the location validation codes. A CSV export is cheap and useful for the review. |
| 9 | **Exposure & hardening** | Named Cloudflare tunnel with systemd, Cloudflare Access on `/admin`, rate-limiting on code entry, and no secrets or answers leaked to the client. |
| 10 | **Content authoring** | The real itineraries, riddles, challenges and codes. It runs in parallel and is often the longest task. |
| 11 | **Rehearsal** | A dry run on 4G with 2 phones, a kill-and-restart test, a backup, and a fallback plan. |

## Order

```
0 → 1 → 2 → 3 ─┬→ 4 → 5 → 6 → 7 → 8 → 9 → 11
               │
               └→ 10 (parallel, from step 1 on)
```

Write me a short recap of where we are at.
Analyze what remain to be done before we can do a minimal dry run. By minimal, I mean just be able to have screen A displayed on a phone, click on a button, access screen B. Then, manually check the data created (wether the team is logged, etc).


</span>

# Recap

## Where we are

| # | Package | Status |
|---|---|---|
| 0 | Skeleton & infra | ✅ Layout, app factory, config, HTMX vendored (49 KB). Gunicorn/tunnel service files written but untested. |
| 1 | Content & data model | ✅ YAML validator, schema, `flask seed`, sample content, `Datamodel.md` |
| 2 | Game engine | ✅ Pure Python, plus scoring and the general-challenge deadline |
| 3 | Engine tests | ✅ |
| – | Repo layer (added) | ✅ Atomic `apply_action`, expiry persistence, teams, settings |
| 4–11 | Everything web-facing | ❌ Not started |

- **Milestone M1 is reached.** A whole game can be played from pytest: 84 tests pass.
- **The git history is clean.** Only `Docs/prompt04_repo.md` is untracked.
- **No HTTP code exists yet** beyond a placeholder page at `/`. Nothing connects Flask to the database.

## Remaining work for the minimal dry run

The goal is screen A on a phone, a button click, screen B, then a manual check of the data.

| # | Task | Notes |
|---|---|---|
| 1 | **DB per request** | Open a connection per request and close it on teardown. Nothing does this today. SQLite connections can't be shared across threads, so each request gets its own. |
| 2 | **Screen A** | List the teams (names only), a name field, a code field and a Confirm button. Template `team_select.html` plus a POST route. |
| 3 | **Join logic** | Check the code first, then rename, then set the cookie, then log the event. The order matters: renaming before the check would let anyone rename any team. |
| 4 | **Team cookie** | Store `team_id` in Flask's signed session. `/` redirects to B when the cookie is set. |
| 5 | **Screen B stub** | Team name, current phase and a Start button. It is enough to see the engine respond. Real modes come in package 5. |
| 6 | **Log the join** | This is the **gap** for your manual check. The engine has no "team joined" event, so nothing in the DB would show which team logged in. I'd add `TEAM_JOINED` and `TEAM_RENAMED` events, written by the repo and not by the engine, since they aren't game transitions. |
| 7 | **Rate limit** | Flask-Limiter on the join route, 10 attempts. See the flaw below. |
| 8 | **A way to read the data** | A small `flask show-events` command, or a `python -c` one-liner. This is safer than a debug web page. |
| 9 | **Make it reachable from the phone** | See the options below. |
| 10 | **A reset** | Clearing the phone's cookies is enough for now. I'd add `/logout` for dev only. |

## Flaws to settle before coding

| Issue | Why it matters | Options |
|---|---|---|
| **Rate-limit key behind the tunnel** | Behind Cloudflare Tunnel every request appears to come from `127.0.0.1`. A per-IP limit would lock out everybody after 10 attempts in total. | **A.** Limit per team id (no IP needed, but a stranger can lock a team out). **B.** Read the real IP from `CF-Connecting-IP`, trusted only from the tunnel. **C.** Both. I lean towards **A** for now. It is simple and fits a friendly game. |
| **`SECRET_KEY` default** | The code falls back to `dev-only-change-me`, so cookies could be forged if `.env` is missing. | Refuse to start outside debug mode if the key is unset. |
| **Cookie `Secure` flag** | It works over the HTTPS tunnel but breaks plain-HTTP LAN testing. | Make it a config switch, off for the LAN test. |
| **CSRF** | Forms post with a cookie. `SameSite=Lax` covers most of it. | Acceptable for now. Revisit in hardening. |

## Reaching the phone

| Option | Pros | Cons |
|---|---|---|
| **Same Wi-Fi: `flask run --host 0.0.0.0`** | No extra tools. Quickest. | Needs a Windows firewall rule. Corporate Wi-Fi often isolates devices. |
| **Phone hotspot, laptop joined to it** | Avoids corporate isolation. | Slightly fiddly. |
| **Quick tunnel (`cloudflared --url`)** | Tests the real path with HTTPS. | The corporate certificate check failed earlier on curl, so it may be blocked. Try it last. |

I'd try the LAN first, then the hotspot if the corporate network blocks it. The tunnel is for the later rehearsal.

## Proposed order

1. Add `TEAM_JOINED` and `TEAM_RENAMED` events to the repo, with tests.
2. Add the per-request DB connection and the secret-key guard.
3. Build screen A and the join route with the cookie.
4. Add the screen B stub.
5. Add the rate limit.
6. Add `flask show-events`.
7. Write web tests with the Flask test client, then do the manual phone test.

## Questions for you

1. Rate limit: team id (A), real IP (B), or both?
2. Should the Start button already be on the screen B stub? It would let you check an engine transition end to end from the phone.