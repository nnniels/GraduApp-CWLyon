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
| `event(id, team_id, type, payload_json, ts)` | Append-only. Index on `(team_id, id)`. |

### Choices

| Choice | Reason |
|---|---|
| **`team_state` separate from `team`** | `team` is mostly content. `team_state` changes at every action. Easier to reset and to reason about. |
| **CHECK `phase = 'CHALLENGES'` iff `phase_deadline` is set** | A timed phase can never exist without a deadline. |
| **`event` is the source of truth, `challenge_completion` a projection** | The log is for review and scoring and keeps all history (ticks, unticks, wrong codes). The completion table makes the UI query trivial. Both are written in one transaction by `db/repo.py`. |
| **Scoring read from events, not stored** | Nothing stored twice, and a future leaderboard is a query. |
| **No `unlocked_challenge` table** | Derived: initial general challenges, plus the `step_unlock` of every step the team has reached. Reaching a step is known from `step_index` and `phase`. One less thing to keep in sync. |
| **Timestamps as ISO 8601 UTC text** | Readable in the DB, sortable, no timezone confusion. Converted by the app. |
| **`payload_json` as JSON text** | Payloads differ by event type. Never filtered in SQL, only read back. |
| **Join code `UNIQUE`** | It identifies the team at screen A. |
| **Foreign keys on, WAL mode, busy timeout** | Set in `db/connection.py`. Integrity errors are loud, and readers do not block the writer. |

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
