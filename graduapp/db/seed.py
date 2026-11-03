import json
import sqlite3

from ..content.schema import Content


class SeedError(Exception):
    pass


def _prune(conn: sqlite3.Connection, table: str, ids: list[str]) -> None:
    # Raises IntegrityError if a removed row is still referenced: loud on purpose.
    conn.execute(
        f"DELETE FROM {table} WHERE id NOT IN (SELECT value FROM json_each(?))",
        (json.dumps(ids),),
    )


def seed(conn: sqlite3.Connection, content: Content, force: bool = False) -> None:
    """Idempotent. Refuses to run once a team has started, unless force=True.

    Team names are only set on first insert (they are editable in the app).
    Teams are never deleted.
    """
    started = conn.execute(
        "SELECT COUNT(*) FROM team_state WHERE phase != 'NOT_STARTED'"
    ).fetchone()[0]
    if started and not force:
        raise SeedError(f"{started} team(s) already started. Use force to re-seed anyway.")

    with conn:
        conn.execute("DELETE FROM step_unlock")
        conn.execute("DELETE FROM itinerary_step")

        for it in content.itineraries.values():
            conn.execute(
                "INSERT INTO itinerary (id, title) VALUES (?, ?) "
                "ON CONFLICT (id) DO UPDATE SET title = excluded.title",
                (it.id, it.title),
            )

        for s in content.steps.values():
            r, c = s.riddle, s.challenges
            conn.execute(
                "INSERT INTO step (id, location_kind, location_json, code, kind, riddle_text, "
                "riddle_image, challenge_k, challenge_duration_s, points) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT (id) DO UPDATE SET location_kind = excluded.location_kind, "
                "location_json = excluded.location_json, code = excluded.code, kind = excluded.kind, "
                "riddle_text = excluded.riddle_text, riddle_image = excluded.riddle_image, "
                "challenge_k = excluded.challenge_k, "
                "challenge_duration_s = excluded.challenge_duration_s, points = excluded.points",
                (
                    s.id, s.location["kind"], json.dumps(s.location), s.code,
                    "riddle" if r else "challenges",
                    r.text if r else None, r.image if r else None,
                    c.k if c else None, c.duration_s if c else None, s.points,
                ),
            )

        challenge_rows = [
            (ch.id, "general", None, pos, ch.text, ch.points, int(ch.unlocked_at_start))
            for pos, ch in enumerate(content.general_challenges)
        ]
        for s in content.steps.values():
            if s.challenges:
                challenge_rows += [
                    (ch.id, "step", s.id, pos, ch.text, ch.points, 0)
                    for pos, ch in enumerate(s.challenges.items)
                ]
        conn.executemany(
            "INSERT INTO challenge (id, scope, step_id, position, text, points, unlocked_at_start) "
            "VALUES (?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT (id) DO UPDATE SET scope = excluded.scope, step_id = excluded.step_id, "
            "position = excluded.position, text = excluded.text, points = excluded.points, "
            "unlocked_at_start = excluded.unlocked_at_start",
            challenge_rows,
        )

        conn.executemany(
            "INSERT INTO step_unlock (step_id, challenge_id) VALUES (?, ?)",
            [(s.id, u) for s in content.steps.values() for u in s.unlocks],
        )
        conn.executemany(
            "INSERT INTO itinerary_step (itinerary_id, position, step_id) VALUES (?, ?, ?)",
            [
                (it.id, pos, sid)
                for it in content.itineraries.values()
                for pos, sid in enumerate(it.step_ids)
            ],
        )

        for t in content.teams:
            conn.execute(
                "INSERT INTO team (id, name, itinerary_id, join_code) VALUES (?, ?, ?, ?) "
                "ON CONFLICT (id) DO UPDATE SET itinerary_id = excluded.itinerary_id, "
                "join_code = excluded.join_code",
                (t.id, t.name, t.itinerary_id, t.join_code),
            )
            conn.execute("INSERT OR IGNORE INTO team_state (team_id) VALUES (?)", (t.id,))

        _prune(conn, "challenge", [row[0] for row in challenge_rows])
        _prune(conn, "step", list(content.steps))
        _prune(conn, "itinerary", list(content.itineraries))
