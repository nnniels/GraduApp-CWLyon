"""Content structures and validation. Pure: takes parsed YAML (dicts), returns frozen dataclasses.

All problems are collected and reported at once, so an author fixes the files in one pass.
"""
from dataclasses import dataclass


class ContentError(Exception):
    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("Invalid content:\n- " + "\n- ".join(errors))


@dataclass(frozen=True)
class Challenge:
    id: str
    text: str
    points: int = 1
    unlocked_at_start: bool = False


@dataclass(frozen=True)
class Riddle:
    text: str
    image: str | None = None


@dataclass(frozen=True)
class StepChallenges:
    k: int
    duration_s: int
    items: tuple[Challenge, ...]


@dataclass(frozen=True)
class Step:
    id: str
    location: dict
    code: str
    unlocks: tuple[str, ...]
    points: int
    riddle: Riddle | None
    challenges: StepChallenges | None


@dataclass(frozen=True)
class Itinerary:
    id: str
    title: str
    step_ids: tuple[str, ...]


@dataclass(frozen=True)
class Team:
    id: str
    name: str
    itinerary_id: str
    join_code: str


@dataclass(frozen=True)
class Content:
    steps: dict[str, Step]
    general_challenges: tuple[Challenge, ...]
    itineraries: dict[str, Itinerary]
    teams: tuple[Team, ...]


_LOCATION_FIELDS = {
    "text": {"text": str},
    "maps_link": {"url": str},
    "minimap": {"lat": (int, float), "lon": (int, float)},
}


def _is_str(v) -> bool:
    return isinstance(v, str) and v.strip() != ""


def _is_int(v, minimum: int) -> bool:
    return isinstance(v, int) and not isinstance(v, bool) and v >= minimum


def build_content(steps_raw, general_raw, itineraries_raw, teams_raw) -> Content:
    errors: list[str] = []
    challenge_ids: set[str] = set()

    def check_keys(raw: dict, allowed: set[str], where: str) -> None:
        for key in sorted(set(raw) - allowed):
            errors.append(f"{where}: unknown key '{key}'")

    def challenge(raw, where: str, general: bool) -> Challenge | None:
        if not isinstance(raw, dict):
            errors.append(f"{where}: must be a mapping")
            return None
        allowed = {"id", "text", "points"} | ({"unlocked_at_start"} if general else set())
        check_keys(raw, allowed, where)
        ok = True
        cid = raw.get("id")
        if not _is_str(cid):
            errors.append(f"{where}: 'id' must be a non-empty string")
            ok = False
        elif cid in challenge_ids:
            errors.append(f"{where}: duplicate challenge id '{cid}'")
            ok = False
        else:
            challenge_ids.add(cid)
        if not _is_str(raw.get("text")):
            errors.append(f"{where}: 'text' must be a non-empty string")
            ok = False
        points = raw.get("points", 1)
        if not _is_int(points, 0):
            errors.append(f"{where}: 'points' must be an integer >= 0")
            ok = False
        start = raw.get("unlocked_at_start", False)
        if not isinstance(start, bool):
            errors.append(f"{where}: 'unlocked_at_start' must be true or false")
            ok = False
        return Challenge(cid, raw["text"], points, start) if ok else None

    def location(raw, where: str) -> dict | None:
        if not isinstance(raw, dict) or raw.get("kind") not in _LOCATION_FIELDS:
            errors.append(f"{where}.location: 'kind' must be one of {sorted(_LOCATION_FIELDS)}")
            return None
        fields = _LOCATION_FIELDS[raw["kind"]]
        check_keys(raw, {"kind", "label"} | set(fields), f"{where}.location")
        ok = True
        for name, typ in fields.items():
            value = raw.get(name)
            if not isinstance(value, typ) or isinstance(value, bool) or value == "":
                errors.append(f"{where}.location: '{name}' is required for kind '{raw['kind']}'")
                ok = False
        # The URL becomes a link on the phones: refuse javascript: and the like.
        if ok and raw["kind"] == "maps_link" and not raw["url"].startswith(("https://", "http://")):
            errors.append(f"{where}.location: 'url' must start with https:// or http://")
            ok = False
        return dict(raw) if ok else None

    general = []
    for i, raw in enumerate(general_raw or []):
        c = challenge(raw, f"general_challenges[{i}]", general=True)
        if c:
            general.append(c)
    general_ids = {c.id for c in general}

    steps: dict[str, Step] = {}
    for i, raw in enumerate(steps_raw or []):
        where = f"steps[{i}]"
        if not isinstance(raw, dict):
            errors.append(f"{where}: must be a mapping")
            continue
        sid = raw.get("id")
        if _is_str(sid):
            where = f"step '{sid}'"
        check_keys(raw, {"id", "location", "code", "unlocks", "points", "riddle", "challenges"}, where)
        if not _is_str(sid):
            errors.append(f"{where}: 'id' must be a non-empty string")
            continue
        if sid in steps:
            errors.append(f"{where}: duplicate step id")
            continue

        loc = location(raw.get("location"), where)
        # Quoted on purpose: YAML reads an unquoted 0123 as a number and drops the zero.
        if not _is_str(raw.get("code")):
            errors.append(f"{where}: 'code' must be a quoted, non-empty string")
        points = raw.get("points", 0)
        if not _is_int(points, 0):
            errors.append(f"{where}: 'points' must be an integer >= 0")

        unlocks = raw.get("unlocks") or []
        if not isinstance(unlocks, list):
            errors.append(f"{where}: 'unlocks' must be a list")
            unlocks = []
        for u in unlocks:
            if u not in general_ids:
                errors.append(f"{where}: unlocks unknown general challenge '{u}'")

        riddle = challenges = None
        has_riddle, has_challenges = "riddle" in raw, "challenges" in raw
        if has_riddle == has_challenges:
            errors.append(f"{where}: exactly one of 'riddle' or 'challenges' is required")
        elif has_riddle:
            r = raw["riddle"]
            if isinstance(r, dict):
                check_keys(r, {"text", "image"}, f"{where}.riddle")
            if not isinstance(r, dict) or not _is_str(r.get("text")):
                errors.append(f"{where}.riddle: 'text' must be a non-empty string")
            else:
                riddle = Riddle(r["text"], r.get("image"))
        else:
            c = raw["challenges"]
            if not isinstance(c, dict):
                errors.append(f"{where}.challenges: must be a mapping")
            else:
                check_keys(c, {"k", "duration_s", "items"}, f"{where}.challenges")
                items = [
                    challenge(it, f"{where}.challenges.items[{j}]", general=False)
                    for j, it in enumerate(c.get("items") or [])
                ]
                items = [it for it in items if it]
                if not _is_int(c.get("duration_s"), 1):
                    errors.append(f"{where}.challenges: 'duration_s' must be an integer > 0")
                if not _is_int(c.get("k"), 1) or c["k"] > len(items):
                    errors.append(f"{where}.challenges: 'k' must be between 1 and the number of items")
                elif _is_int(c.get("duration_s"), 1):
                    challenges = StepChallenges(c["k"], c["duration_s"], tuple(items))

        if loc and _is_str(raw.get("code")) and _is_int(points, 0) and (riddle or challenges):
            steps[sid] = Step(sid, loc, raw["code"], tuple(unlocks), points, riddle, challenges)

    itineraries: dict[str, Itinerary] = {}
    for i, raw in enumerate(itineraries_raw or []):
        where = f"itineraries[{i}]"
        if not isinstance(raw, dict) or not _is_str(raw.get("id")):
            errors.append(f"{where}: 'id' must be a non-empty string")
            continue
        where = f"itinerary '{raw['id']}'"
        check_keys(raw, {"id", "title", "steps"}, where)
        if raw["id"] in itineraries:
            errors.append(f"{where}: duplicate itinerary id")
            continue
        step_ids = raw.get("steps")
        if not _is_str(raw.get("title")):
            errors.append(f"{where}: 'title' must be a non-empty string")
        if not isinstance(step_ids, list) or not step_ids:
            errors.append(f"{where}: 'steps' must be a non-empty list of step ids")
            continue
        for sid in step_ids:
            if sid not in steps:
                errors.append(f"{where}: unknown step '{sid}'")
        if len(set(step_ids)) != len(step_ids):
            errors.append(f"{where}: a step appears twice")
        itineraries[raw["id"]] = Itinerary(raw["id"], str(raw.get("title")), tuple(step_ids))

    teams: list[Team] = []
    team_ids: set[str] = set()
    join_codes: set[str] = set()
    for i, raw in enumerate(teams_raw or []):
        where = f"teams[{i}]"
        if not isinstance(raw, dict):
            errors.append(f"{where}: must be a mapping")
            continue
        check_keys(raw, {"id", "name", "itinerary", "join_code"}, where)
        ok = True
        for key in ("id", "name", "itinerary", "join_code"):
            if not _is_str(raw.get(key)):
                errors.append(f"{where}: '{key}' must be a non-empty (quoted) string")
                ok = False
        if not ok:
            continue
        if raw["id"] in team_ids:
            errors.append(f"{where}: duplicate team id '{raw['id']}'")
        if raw["join_code"] in join_codes:
            errors.append(f"{where}: duplicate join_code")
        if raw["itinerary"] not in itineraries:
            errors.append(f"{where}: unknown itinerary '{raw['itinerary']}'")
        team_ids.add(raw["id"])
        join_codes.add(raw["join_code"])
        teams.append(Team(raw["id"], raw["name"], raw["itinerary"], raw["join_code"]))

    if errors:
        raise ContentError(errors)
    return Content(steps, tuple(general), itineraries, tuple(teams))
