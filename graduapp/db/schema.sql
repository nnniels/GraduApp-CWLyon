-- Content tables: filled by `flask seed` from content/*.yaml. Never written during the game.
CREATE TABLE IF NOT EXISTS itinerary (
    id    TEXT PRIMARY KEY,
    title TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS step (
    id                   TEXT PRIMARY KEY,
    location_kind        TEXT NOT NULL CHECK (location_kind IN ('text', 'maps_link', 'minimap')),
    location_json        TEXT NOT NULL,
    code                 TEXT NOT NULL,
    kind                 TEXT NOT NULL CHECK (kind IN ('riddle', 'challenges')),
    riddle_text          TEXT,
    riddle_image         TEXT,
    challenge_k          INTEGER,
    challenge_duration_s INTEGER,
    points               INTEGER NOT NULL DEFAULT 0 CHECK (points >= 0),
    fun_fact             TEXT,
    get_there            TEXT,
    CHECK (
        (kind = 'riddle' AND riddle_text IS NOT NULL
            AND challenge_k IS NULL AND challenge_duration_s IS NULL)
        OR
        (kind = 'challenges' AND riddle_text IS NULL AND riddle_image IS NULL
            AND challenge_k >= 1 AND challenge_duration_s > 0)
    )
);

CREATE TABLE IF NOT EXISTS itinerary_step (
    itinerary_id TEXT    NOT NULL REFERENCES itinerary (id),
    position     INTEGER NOT NULL CHECK (position >= 0),
    step_id      TEXT    NOT NULL REFERENCES step (id),
    PRIMARY KEY (itinerary_id, position),
    UNIQUE (itinerary_id, step_id)
);

-- One table for both kinds. A 'step' challenge belongs to exactly one step.
CREATE TABLE IF NOT EXISTS challenge (
    id                TEXT PRIMARY KEY,
    scope             TEXT NOT NULL CHECK (scope IN ('step', 'general')),
    step_id           TEXT REFERENCES step (id),
    position          INTEGER NOT NULL DEFAULT 0,
    text              TEXT NOT NULL,
    points            INTEGER NOT NULL DEFAULT 1 CHECK (points >= 0),
    unlocked_at_start INTEGER NOT NULL DEFAULT 0 CHECK (unlocked_at_start IN (0, 1)),
    CHECK ((scope = 'step') = (step_id IS NOT NULL)),
    CHECK (scope = 'general' OR unlocked_at_start = 0)
);

-- General challenges added to screen C when the team arrives at the step.
CREATE TABLE IF NOT EXISTS step_unlock (
    step_id      TEXT NOT NULL REFERENCES step (id),
    challenge_id TEXT NOT NULL REFERENCES challenge (id),
    PRIMARY KEY (step_id, challenge_id)
);

-- Game tables: written by the engine through db/repo.py.
CREATE TABLE IF NOT EXISTS team (
    id           TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    itinerary_id TEXT NOT NULL REFERENCES itinerary (id),
    join_code    TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS team_state (
    team_id        TEXT PRIMARY KEY REFERENCES team (id),
    step_index     INTEGER NOT NULL DEFAULT 0 CHECK (step_index >= 0),
    phase          TEXT NOT NULL DEFAULT 'NOT_STARTED'
                   CHECK (phase IN ('NOT_STARTED', 'GOING', 'RIDDLE', 'CHALLENGES', 'ENDED')),
    phase_deadline TEXT,
    CHECK ((phase = 'CHALLENGES') = (phase_deadline IS NOT NULL))
);

-- Current ticks only (projection for the UI). History lives in `event`.
CREATE TABLE IF NOT EXISTS challenge_completion (
    team_id      TEXT NOT NULL REFERENCES team (id),
    challenge_id TEXT NOT NULL REFERENCES challenge (id),
    text         TEXT NOT NULL,
    ticked_at    TEXT NOT NULL,
    PRIMARY KEY (team_id, challenge_id)
);

-- General challenges the team has already looked at on screen C (drives the NEW badge).
-- UI state only: not a game event, never scored. Cascade so re-seeding can remove a challenge.
CREATE TABLE IF NOT EXISTS challenge_seen (
    team_id      TEXT NOT NULL REFERENCES team (id),
    challenge_id TEXT NOT NULL REFERENCES challenge (id) ON DELETE CASCADE,
    PRIMARY KEY (team_id, challenge_id)
);

-- Game-wide settings set by the organiser. `general_deadline`: ISO 8601 UTC, absent = no limit.
CREATE TABLE IF NOT EXISTS game_setting (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- Append-only audit log. Source of truth for review and scoring. ts is ISO 8601 UTC.
CREATE TABLE IF NOT EXISTS event (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    team_id      TEXT NOT NULL REFERENCES team (id),
    type         TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    ts           TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS event_team_idx ON event (team_id, id);
