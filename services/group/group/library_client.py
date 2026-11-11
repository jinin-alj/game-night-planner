import os

import requests

DEFAULT_LIBRARY_URL = "http://library:8000"
TIMEOUT_SECONDS = 2

class LibraryUnavailableError(Exception):
    """raised when the library service can't be reached or answers with an unexpected error"""

def get_library_url() -> str:
    """return the base url of the library service, read from the LIBRARY_URL environment variable"""
    return os.environ.get("LIBRARY_URL", DEFAULT_LIBRARY_URL)

def find_games_that_fit(players: int, minutes: int) -> list[dict]:
    """ask library for the games that fit this many players in this many minutes"""
    response = _get_from_library("/games/fit", {"players": players, "minutes": minutes})
    if response.status_code != 200:
        raise LibraryUnavailableError(f"library answered {response.status_code}")
    return response.json()

def get_game_title(game_id: int) -> str | None:
    """ask library for a game's title, or return None if library has no game with this id"""
    response = _get_from_library(f"/games/{game_id}")

    # a 404 means library is working fine and simply has no game with this id, so it is not treated as an outage
    if response.status_code == 404:
        return None
    if response.status_code != 200:
        raise LibraryUnavailableError(f"library answered {response.status_code}")
    return response.json()["title"]

def _get_from_library(path: str, params: dict | None = None) -> requests.Response:
    """send a GET request to library and give up after a few seconds, so a slow library can never make group hang"""
    url = get_library_url() + path
    try:
        return requests.get(url, params=params, timeout=TIMEOUT_SECONDS)
    except requests.RequestException as error:
        raise LibraryUnavailableError(f"library could not be reached at {url}") from error