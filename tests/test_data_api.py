"""Tests for DataApiClient (Story 5.1)."""

import unittest
from unittest.mock import MagicMock, patch

from btts_bot.clients.data_api import DataApiClient


class TestDataApiClientGetPositions(unittest.TestCase):
    """AC #1, #5: DataApiClient.get_positions() behavior."""

    def _make_client(self) -> DataApiClient:
        return DataApiClient(proxy_address="0xproxy")

    def test_get_positions_returns_list_on_success(self) -> None:
        """Successful query returns parsed position list."""
        client = self._make_client()
        mock_response = MagicMock()
        mock_response.json.return_value = [
            {"asset": "token-1", "size": "10.5"},
            {"asset": "token-2", "size": "5.0"},
        ]
        mock_response.raise_for_status = MagicMock()

        with patch("btts_bot.clients.data_api.requests.get", return_value=mock_response):
            result = client.get_positions()

        self.assertIsNotNone(result)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["asset"], "token-1")
        self.assertEqual(result[1]["asset"], "token-2")

    def test_get_positions_calls_correct_endpoint(self) -> None:
        """get_positions() queries the correct Data API URL with proxy_address param."""
        client = DataApiClient(proxy_address="0xmywallet")
        mock_response = MagicMock()
        mock_response.json.return_value = []
        mock_response.raise_for_status = MagicMock()

        with patch(
            "btts_bot.clients.data_api.requests.get", return_value=mock_response
        ) as mock_get:
            client.get_positions()

        mock_get.assert_called_once()
        call_args = mock_get.call_args
        self.assertIn("data-api.polymarket.com/positions", call_args.args[0])
        self.assertEqual(call_args.kwargs["params"]["user"], "0xmywallet")

    def test_get_positions_empty_list_returned_correctly(self) -> None:
        """Empty position list is returned without error."""
        client = self._make_client()
        mock_response = MagicMock()
        mock_response.json.return_value = []
        mock_response.raise_for_status = MagicMock()

        with patch("btts_bot.clients.data_api.requests.get", return_value=mock_response):
            result = client.get_positions()

        self.assertEqual(result, [])

    def test_get_positions_non_list_response_returns_empty_list(self) -> None:
        """If API returns a non-list JSON value, returns empty list with a warning."""
        client = self._make_client()
        mock_response = MagicMock()
        mock_response.json.return_value = {"error": "unexpected"}
        mock_response.raise_for_status = MagicMock()

        with patch("btts_bot.clients.data_api.requests.get", return_value=mock_response):
            result = client.get_positions()

        self.assertEqual(result, [])

    def test_get_positions_retries_on_transient_error_then_succeeds(self) -> None:
        """API error triggers retry; eventual success returns data."""
        import requests as req

        client = self._make_client()
        mock_response = MagicMock()
        mock_response.json.return_value = [{"asset": "token-1", "size": "5.0"}]
        mock_response.raise_for_status = MagicMock()

        with (
            patch(
                "btts_bot.clients.data_api.requests.get",
                side_effect=[
                    req.ConnectionError("transient"),
                    mock_response,
                ],
            ),
            patch("time.sleep"),
        ):
            result = client.get_positions()

        self.assertIsNotNone(result)
        self.assertEqual(len(result), 1)

    def test_get_positions_returns_none_after_exhausted_retries(self) -> None:
        """If all retries are exhausted, returns None."""
        import requests as req

        client = self._make_client()

        with (
            patch(
                "btts_bot.clients.data_api.requests.get",
                side_effect=req.ConnectionError("persistent failure"),
            ),
            patch("time.sleep"),
        ):
            result = client.get_positions()

        self.assertIsNone(result)

    def test_get_positions_http_error_triggers_retry(self) -> None:
        """HTTP 503 triggers retry."""
        import requests as req

        client = self._make_client()

        # Build a 503 response error
        error_response = MagicMock()
        error_response.status_code = 503
        http_error = req.HTTPError(response=error_response)

        mock_success = MagicMock()
        mock_success.json.return_value = [{"asset": "t1", "size": "3.0"}]
        mock_success.raise_for_status = MagicMock()

        with (
            patch(
                "btts_bot.clients.data_api.requests.get",
                side_effect=[http_error, mock_success],
            ),
            patch("time.sleep"),
        ):
            result = client.get_positions()

        self.assertIsNotNone(result)

    def test_get_positions_400_error_not_retried(self) -> None:
        """HTTP 400 is not retried (re-raised immediately)."""
        import requests as req

        client = self._make_client()

        error_response = MagicMock()
        error_response.status_code = 400
        http_error = req.HTTPError(response=error_response)

        with (
            patch(
                "btts_bot.clients.data_api.requests.get",
                side_effect=http_error,
            ),
        ):
            with self.assertRaises(req.HTTPError):
                client.get_positions()


if __name__ == "__main__":
    unittest.main()
