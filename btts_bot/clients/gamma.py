"""Gamma client for reading local Polymarket market data files."""

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class GammaClient:
    """Reads market data from a local JSON data file."""

    def __init__(self, data_file: str) -> None:
        self._data_file = Path(data_file)

    def fetch_games(self) -> list[dict] | None:
        """Read all games from the local JSON data file.

        Returns the list of game dicts from the JSON, or None on failure.
        """
        try:
            data = json.loads(self._data_file.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                logger.error(
                    "Invalid data file format in %s: root JSON value must be an object",
                    self._data_file,
                )
                return None

            games = data.get("games", [])
            if games is None:
                games = []
            if not isinstance(games, list):
                logger.error(
                    "Invalid data file format in %s: 'games' must be a list",
                    self._data_file,
                )
                return None

            logger.info("Fetched %d games from data file", len(games))
            return games
        except FileNotFoundError:
            logger.error("Data file not found: %s", self._data_file)
            return None
        except (json.JSONDecodeError, OSError) as exc:
            logger.error("Failed to read data file %s: %s", self._data_file, exc)
            return None
