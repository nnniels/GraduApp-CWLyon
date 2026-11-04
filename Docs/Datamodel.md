# Where the state of the app lives

**One SQLite file:** `instance/graduapp.sqlite`. The path comes from `DATABASE_PATH` in `.env`. While the app runs there are also `graduapp.sqlite-wal` and `-shm` files next to it. That is normal.

| Data | Table |
|---|---|
| Team name, itinerary, join code | `team` |
| Progress: step, phase, deadline | `team_state` |
| Current ticks and their notes | `challenge_completion` |
| Which general challenges a team has already looked at (NEW badge) | `challenge_seen` |
| Full history, source of the score | `event` |
| General-challenge deadline | `game_setting` |

The phone keeps only a signed cookie with the `team_id` and the chosen screen (B or C). Clearing it logs the phone out but loses no progress.

# How to read it

- **History:** `flask show-events`, with `--team team-1` and `--tail 20` to filter.
- **Current state:** a short Python script (no `sqlite3` CLI is needed), or a viewer such as "DB Browser for SQLite" or a VS Code SQLite extension. Open the file read-only while the app runs.

```python
import sqlite3
c = sqlite3.connect("instance/graduapp.sqlite")
print(c.execute("select * from team_state").fetchall())
```

# How to reset

| Goal | What to do |
|---|---|
| **Progress** (all teams back to `NOT_STARTED`, ticks, NEW markers and history erased; names, codes and the general deadline kept) | `flask reset-game` |
| **Progress and team names** (names back to `content/teams.yaml`) | `flask reset-game --names` |
| **Everything, including the database** | Stop the app, delete the three `instance/graduapp.sqlite*` files, then run `flask seed`. |
| **Re-load edited content mid-game** | `flask seed --force`. It never touches progress, but it can break a running game if you changed step order. |

Plain `flask seed` refuses once any team has started, and it never resets progress.

Phones keep their cookie after a reset, so they stay on their team and land on the "Start the game" screen. To pick another team, clear the browser cookies.

**Gap:** there is no reset command, so it's manual SQL today. A `flask reset-game` command would make this safer before the rehearsal. Shall I add one?

**Timer check:** my live check of the new timer was interrupted, so the countdown JavaScript is **not yet verified in a browser**. The 137 tests pass, but they can't run JavaScript. I've now stopped the test server and deleted the scratch databases. I can redo the browser check and finish step 6 whenever you say.



# Data model

Two kinds of data, kept apart on purpose:

| Kind | Where it is authored | Written during the game? | Tables |
|---|---|---|---|
| **Content** (what the game is) | `content/*.yaml`, in git | No | `itinerary`, `step`, `itinerary_step`, `challenge`, `step_unlock` |
| **Game data** (what teams did) | The app | Yes | `team`, `team_state`, `challenge_completion`, `event` |

Content is validated by `graduapp/content/schema.py`, then copied into SQLite by `flask seed`. The DB is the single runtime source: progress refers to stable ids, and the engine never reads YAML.

Schema: [graduapp/db/schema.sql](../graduapp/db/schema.sql).

## Content

### YAML files

| File | Holds |
|---|---|
| `steps.yaml` | The library of all steps |
| `itineraries/*.yaml` | One file per itinerary: `id`, `title`, ordered list of step ids |
| `general_challenges.yaml` | Screen C challenges |
| `teams.yaml` | Teams, their itinerary, their join code |

### Tables

| Table | Key points |
|---|---|
| `itinerary(id, title)` | |
| `step(id, location_kind, location_json, code, kind, riddle_*, challenge_k, challenge_duration_s, points)` | `kind` is `riddle` or `challenges`. |
| `itinerary_step(itinerary_id, position, step_id)` | Order of an itinerary. |
| `challenge(id, scope, step_id, position, text, points, unlocked_at_start)` | `scope` is `step` or `general`. |
| `step_unlock(step_id, challenge_id)` | General challenges revealed on arrival. |

### Choices

| Choice | Reason |
|---|---|
| **Steps are a library, itineraries only list ids** (`itinerary_step`) | Two itineraries may share steps. A step and its code are then written once. Cost: an author edits two files. |
| **Step defined once, with `kind` + CHECK** | The DB itself rejects a step that is both riddle and challenges, or neither. The validator catches it earlier with a readable message. |
| **One `challenge` table, two scopes** | Ticking, scoring and the completion table work the same way for both. A CHECK ties `step_id` to `scope = 'step'`. |
| **Step challenges are inline in their step** | They belong to exactly one step. No shared pool to manage. |
| **`location_json` instead of columns** | The location is only displayed, never queried. Its shape depends on `location_kind` (text, URL, lat/lon), and the validator enforces it. |
| **Codes stored as TEXT, and must be quoted in YAML** | YAML reads an unquoted `0123` as a number and drops the zero. The validator rejects non-strings. |
| **Unknown YAML keys are errors** | A typo like `unlock:` would otherwise be silently ignored. |
| **All errors reported at once** | The author fixes the content in one pass. |
| **Positions are in `itinerary_step`, not in `step`** | A shared step can sit at a different position in each itinerary. |
| **`unlocked_at_start` on general challenges** | Needed for challenges visible from the beginning. No separate table for this. |

## Game data

| Table | Key points |
|---|---|
| `team(id, name, itinerary_id, join_code UNIQUE)` | The `name` is editable in the app. |
| `team_state(team_id, step_index, phase, phase_deadline)` | One row per team, as in the state machine. |
| `challenge_completion(team_id, challenge_id, text, ticked_at)` | Current ticks only. Unticking deletes the row. |
| `challenge_seen(team_id, challenge_id)` | General challenges the team has looked at on screen C. Drives the NEW badge. UI state only: not an event, never scored. Cascades if a challenge is removed by a re-seed. |
| `event(id, team_id, type, payload_json, ts)` | Append-only. Index on `(team_id, id)`. |
| `game_setting(key, value)` | Organiser settings. Today only `general_deadline`: until when general challenges can be ticked. Absent means no limit. |

### Choices

| Choice | Reason |
|---|---|
| **`team_state` separate from `team`** | `team` is mostly content. `team_state` changes at every action. Easier to reset and to reason about. |
| **CHECK `phase = 'CHALLENGES'` iff `phase_deadline` is set** | A timed phase can never exist without a deadline. |
| **`event` is the source of truth, `challenge_completion` a projection** | The log is for review and scoring and keeps all history (ticks, unticks, wrong codes). The completion table makes the UI query trivial. Both are written in one transaction by `db/repo.py`. |
| **Scoring read from events, not stored** | Nothing stored twice, and a future leaderboard is a query. |
| **No `unlocked_challenge` table** | Derived: initial general challenges, plus the `step_unlock` of every step the team has reached. Reaching a step is known from `step_index` and `phase`. One less thing to keep in sync. |
| **`challenge_seen` is a table, not a cookie** | NEW must survive a reload and a phone swap, and a team is not a phone. It is marked when the team *leaves* screen C, so the NEW tags stay visible for the whole visit. |
| **The selected screen (B/C) lives in the cookie** | It is pure display state, per phone. It is not stored in the DB and never logged. |
| **Timestamps as ISO 8601 UTC text** | Readable in the DB, sortable, no timezone confusion. Converted by the app. |
| **`payload_json` as JSON text** | Payloads differ by event type. Never filtered in SQL, only read back. |
| **Join code `UNIQUE`** | It identifies the team at screen A. |
| **Key/value `game_setting` table** | One row today, but the organiser screen will add more settings without a migration. |
| **Foreign keys on, WAL mode, busy timeout** | Set in `db/connection.py`. Integrity errors are loud, and readers do not block the writer. |

## Repo layer (`db/repo.py`)

| Rule | Reason |
|---|---|
| One `BEGIN IMMEDIATE` transaction per action: load, transition, persist | Concurrent requests are serialised, so a double tap applies once (tested with two connections). |
| State, events and `challenge_completion` are written together | The projection cannot drift from the log. |
| A refused action still persists the expiry it revealed, then re-raises | A timed-out step has failed whatever the request was. |
| `resolve_team` on every page load | Expiry is lazy: viewing the page must also record it. |
| Team listing never returns join codes; `check_join_code` compares in constant time | Codes never reach a template. |
| Datetimes must be timezone-aware, stored as UTC | No naive-time bugs. |
| `step_ticked` loaded only for the current step | Ticks of closed steps are history, not state. |

## Seeding rules (`flask seed`)

| Rule | Reason |
|---|---|
| Validate first, load only if valid, in one transaction | A bad edit never leaves a half-loaded DB. |
| Idempotent: upsert by id | Safe to run again after each content edit. |
| **Refuses once any team has started** (`--force` overrides) | Changing steps under a running game would corrupt `step_index`. |
| Team `name` is set on insert only | Teams rename themselves. Re-seeding must not undo it. |
| Join codes and itinerary allocation are updated | They are authored in YAML. |
| Teams are never deleted | They own the history. Remove them by hand. |
| Removed steps, challenges and itineraries are pruned, and fail loudly if still referenced | Silent orphans would be worse. |

## Known limits

- **Changing a content id after teams have completed it** breaks the history. Treat ids as permanent.
- **Code matching** (case, spaces) is an engine decision, not stored in the model. I suggest trimming and ignoring case.
- **Riddle answers** are not in a table. They live in `RIDDLE_ANSWERED` events, and the organiser view reads them from there.
- **Rate-limit counters** are not in the DB (Flask-Limiter, in memory), so they reset when the app restarts.
