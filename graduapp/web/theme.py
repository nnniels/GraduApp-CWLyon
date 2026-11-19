"""Look-and-feel values that the templates need. The colours themselves live in static/css/theme.css."""

TEAM_SLOTS = 4  # matches the --team-N colours in theme.css

# Brand images served without login (team select) or with it (the end screen).
# Only these names are served: the public route never reads an arbitrary file.
BRAND_IMAGES = {
    "title": "App_logo.png",
    "skyline": "Frame.png",
    "flag": "Checkered finish flag and tricolor confetti.png",
}


def team_slot(index: int) -> int:
    """Colour slot (1-4) of the team at this position in the team list. Cycles past 4 teams."""
    return index % TEAM_SLOTS + 1
