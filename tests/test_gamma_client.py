"""Tests for GammaClient."""

import json
import tempfile
import unittest
from pathlib import Path

from btts_bot.clients.gamma import GammaClient


class GammaClientFetchGamesTests(unittest.TestCase):
    def _write_json(self, tmp_dir: str, data: dict) -> str:
        path = Path(tmp_dir) / "games.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        return str(path)

    def test_fetch_games_returns_games_list_on_success(self) -> None:
        """GammaClient.fetch_games() returns games list from local JSON file."""
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_json(
                tmp, {"date": "2026-03-23", "games": [{"id": "1"}, {"id": "2"}]}
            )
            client = GammaClient(path)
            result = client.fetch_games()
        self.assertEqual(result, [{"id": "1"}, {"id": "2"}])

    def test_fetch_games_returns_empty_list_when_no_games_key(self) -> None:
        """Returns empty list when 'games' key is absent."""
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_json(tmp, {"date": "2026-03-23"})
            client = GammaClient(path)
            result = client.fetch_games()
        self.assertEqual(result, [])

    def test_fetch_games_reads_from_configured_path(self) -> None:
        """GammaClient reads the exact file path from constructor."""
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_json(tmp, {"games": [{"id": "42"}]})
            client = GammaClient(path)
            result = client.fetch_games()
        self.assertEqual(result, [{"id": "42"}])

    def test_fetch_games_returns_none_when_file_not_found(self) -> None:
        """Returns None when the file does not exist."""
        client = GammaClient("/nonexistent/path/games.json")
        result = client.fetch_games()
        self.assertIsNone(result)

    def test_fetch_games_returns_none_on_malformed_json(self) -> None:
        """Returns None when the file contains invalid JSON."""
        with tempfile.TemporaryDirectory() as tmp:
            bad_path = Path(tmp) / "games.json"
            bad_path.write_text("{ not valid json }", encoding="utf-8")
            client = GammaClient(str(bad_path))
            result = client.fetch_games()
        self.assertIsNone(result)

    def test_fetch_games_logs_error_when_file_not_found(self) -> None:
        """Logs an ERROR when the file does not exist."""
        client = GammaClient("/nonexistent/path/games.json")
        with self.assertLogs("btts_bot.clients.gamma", level="ERROR") as log:
            client.fetch_games()
        self.assertTrue(any("not found" in msg.lower() for msg in log.output))

    def test_fetch_games_logs_error_on_malformed_json(self) -> None:
        """Logs an ERROR when JSON is malformed."""
        with tempfile.TemporaryDirectory() as tmp:
            bad_path = Path(tmp) / "games.json"
            bad_path.write_text("<<<invalid>>>", encoding="utf-8")
            client = GammaClient(str(bad_path))
            with self.assertLogs("btts_bot.clients.gamma", level="ERROR") as log:
                client.fetch_games()
        self.assertTrue(any("failed to read" in msg.lower() for msg in log.output))

    def test_fetch_games_returns_none_when_root_is_not_object(self) -> None:
        """Returns None when JSON root is not an object."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "games.json"
            path.write_text('[{"id": "1"}]', encoding="utf-8")
            client = GammaClient(str(path))
            result = client.fetch_games()
        self.assertIsNone(result)

    def test_fetch_games_returns_none_when_games_is_not_list(self) -> None:
        """Returns None when 'games' key is not a list."""
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_json(tmp, {"games": {"id": "1"}})
            client = GammaClient(path)
            result = client.fetch_games()
        self.assertIsNone(result)

    def test_fetch_games_treats_null_games_as_empty_list(self) -> None:
        """Treats null 'games' as an empty list."""
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_json(tmp, {"games": None})
            client = GammaClient(path)
            result = client.fetch_games()
        self.assertEqual(result, [])


if __name__ == "__main__":
    unittest.main()
