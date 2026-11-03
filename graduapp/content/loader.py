from pathlib import Path

import yaml

from .schema import Content, ContentError, build_content


def _read(path: Path):
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ContentError([f"{path}: {exc}"]) from exc


def load_content(content_dir: str | Path) -> Content:
    root = Path(content_dir)
    steps = _read(root / "steps.yaml") or {}
    general = _read(root / "general_challenges.yaml") or {}
    teams = _read(root / "teams.yaml") or {}
    itineraries = []
    for path in sorted((root / "itineraries").glob("*.yaml")):
        itineraries.append(_read(path))
    return build_content(
        steps.get("steps"), general.get("challenges"), itineraries, teams.get("teams")
    )
