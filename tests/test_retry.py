"""
Tests for btts_bot.retry — @with_retry decorator.
Story 1.4: Retry Decorator for API Resilience.
"""

import logging
import unittest
from unittest.mock import MagicMock, patch

import requests

from btts_bot.retry import MAX_RETRIES, with_retry


class TestWithRetrySuccessPath(unittest.TestCase):
    """AC #4: No retry overhead when function succeeds first call."""

    def test_success_first_call_returns_value(self):
        @with_retry
        def always_succeeds():
            return 42

        result = always_succeeds()
        self.assertEqual(result, 42)

    @patch("btts_bot.retry.time.sleep")
    def test_success_first_call_no_sleep(self, mock_sleep):
        @with_retry
        def always_succeeds():
            return "hello"

        result = always_succeeds()
        self.assertEqual(result, "hello")
        mock_sleep.assert_not_called()

    def test_preserves_function_name_via_wraps(self):
        @with_retry
        def my_api_call():
            return None

        self.assertEqual(my_api_call.__name__, "my_api_call")


class TestWithRetryRetryableErrors(unittest.TestCase):
    """AC #1: Retryable errors are retried up to MAX_RETRIES times."""

    @patch("btts_bot.retry.random.uniform", return_value=0.0)
    @patch("btts_bot.retry.time.sleep")
    def test_retryable_500_retries_max_times_returns_none(self, mock_sleep, mock_uniform):
        call_count = 0

        @with_retry
        def flaky_500():
            nonlocal call_count
            call_count += 1
            resp = MagicMock()
            resp.status_code = 500
            raise requests.HTTPError(response=resp)

        result = flaky_500()
        self.assertIsNone(result)
        self.assertEqual(call_count, MAX_RETRIES)
        self.assertEqual(mock_sleep.call_count, MAX_RETRIES)

    @patch("btts_bot.retry.random.uniform", return_value=0.0)
    @patch("btts_bot.retry.time.sleep")
    def test_retryable_429_retries_max_times_returns_none(self, mock_sleep, mock_uniform):
        call_count = 0

        @with_retry
        def flaky_429():
            nonlocal call_count
            call_count += 1
            resp = MagicMock()
            resp.status_code = 429
            raise requests.HTTPError(response=resp)

        result = flaky_429()
        self.assertIsNone(result)
        self.assertEqual(call_count, MAX_RETRIES)

    @patch("btts_bot.retry.random.uniform", return_value=0.0)
    @patch("btts_bot.retry.time.sleep")
    def test_retryable_425_retries_and_returns_none(self, mock_sleep, mock_uniform):
        @with_retry
        def flaky_425():
            resp = MagicMock()
            resp.status_code = 425
            raise requests.HTTPError(response=resp)

        result = flaky_425()
        self.assertIsNone(result)

    @patch("btts_bot.retry.random.uniform", return_value=0.0)
    @patch("btts_bot.retry.time.sleep")
    def test_retryable_503_retries_and_returns_none(self, mock_sleep, mock_uniform):
        @with_retry
        def flaky_503():
            resp = MagicMock()
            resp.status_code = 503
            raise requests.HTTPError(response=resp)

        result = flaky_503()
        self.assertIsNone(result)

    @patch("btts_bot.retry.random.uniform", return_value=0.0)
    @patch("btts_bot.retry.time.sleep")
    def test_connection_error_treated_as_retryable_returns_none(self, mock_sleep, mock_uniform):
        """AC #1: Network errors (ConnectionError) are retryable."""

        @with_retry
        def network_fail():
            raise requests.ConnectionError("connection refused")

        result = network_fail()
        self.assertIsNone(result)
        self.assertEqual(mock_sleep.call_count, MAX_RETRIES)

    @patch("btts_bot.retry.random.uniform", return_value=0.0)
    @patch("btts_bot.retry.time.sleep")
    def test_timeout_error_treated_as_retryable(self, mock_sleep, mock_uniform):
        @with_retry
        def timeout_fail():
            raise requests.Timeout("timed out")

        result = timeout_fail()
        self.assertIsNone(result)

    @patch("btts_bot.retry.random.uniform", return_value=0.0)
    @patch("btts_bot.retry.time.sleep")
    def test_generic_exception_treated_as_retryable(self, mock_sleep, mock_uniform):
        @with_retry
        def generic_fail():
            raise RuntimeError("something went wrong")

        result = generic_fail()
        self.assertIsNone(result)
        self.assertEqual(mock_sleep.call_count, MAX_RETRIES)


class TestWithRetryNonRetryableErrors(unittest.TestCase):
    """AC #2: Non-retryable errors are re-raised immediately."""

    @patch("btts_bot.retry.time.sleep")
    def test_non_retryable_message_not_enough_balance_reraises(self, mock_sleep):
        call_count = 0

        @with_retry
        def balance_fail():
            nonlocal call_count
            call_count += 1
            raise ValueError("not enough balance to place order")

        with self.assertRaises(ValueError):
            balance_fail()

        self.assertEqual(call_count, 1)  # called exactly once — no retries
        mock_sleep.assert_not_called()

    @patch("btts_bot.retry.time.sleep")
    def test_non_retryable_message_minimum_tick_size_reraises(self, mock_sleep):
        call_count = 0

        @with_retry
        def tick_fail():
            nonlocal call_count
            call_count += 1
            raise ValueError("minimum tick size violation")

        with self.assertRaises(ValueError):
            tick_fail()

        self.assertEqual(call_count, 1)
        mock_sleep.assert_not_called()

    @patch("btts_bot.retry.time.sleep")
    def test_http_400_reraises_immediately(self, mock_sleep):
        call_count = 0

        @with_retry
        def bad_request():
            nonlocal call_count
            call_count += 1
            resp = MagicMock()
            resp.status_code = 400
            raise requests.HTTPError(response=resp)

        with self.assertRaises(requests.HTTPError):
            bad_request()

        self.assertEqual(call_count, 1)
        mock_sleep.assert_not_called()

    @patch("btts_bot.retry.time.sleep")
    def test_non_retryable_message_case_insensitive(self, mock_sleep):
        """Non-retryable message check is case-insensitive (lowercased)."""

        @with_retry
        def mixed_case_fail():
            raise ValueError("NOT ENOUGH BALANCE")

        with self.assertRaises(ValueError):
            mixed_case_fail()

        mock_sleep.assert_not_called()


class TestWithRetryLogging(unittest.TestCase):
    """AC #1, #3: Correct log levels emitted on retries and exhaustion."""

    @patch("btts_bot.retry.random.uniform", return_value=0.0)
    @patch("btts_bot.retry.time.sleep")
    def test_warning_logged_on_each_retry(self, mock_sleep, mock_uniform):
        @with_retry
        def flaky():
            raise requests.ConnectionError("fail")

        with self.assertLogs("btts_bot.retry", level="WARNING") as log_ctx:
            flaky()

        warning_records = [r for r in log_ctx.records if r.levelno == logging.WARNING]
        self.assertEqual(len(warning_records), MAX_RETRIES)

    @patch("btts_bot.retry.random.uniform", return_value=0.0)
    @patch("btts_bot.retry.time.sleep")
    def test_error_logged_on_exhaustion(self, mock_sleep, mock_uniform):
        @with_retry
        def always_fails():
            raise requests.ConnectionError("fail")

        with self.assertLogs("btts_bot.retry", level="WARNING") as log_ctx:
            result = always_fails()

        self.assertIsNone(result)
        error_records = [r for r in log_ctx.records if r.levelno == logging.ERROR]
        self.assertEqual(len(error_records), 1)
        self.assertIn("retries exhausted", error_records[0].message)

    @patch("btts_bot.retry.random.uniform", return_value=0.0)
    @patch("btts_bot.retry.time.sleep")
    def test_warning_log_includes_function_name(self, mock_sleep, mock_uniform):
        @with_retry
        def my_special_func():
            raise requests.ConnectionError("fail")

        with self.assertLogs("btts_bot.retry", level="WARNING") as log_ctx:
            my_special_func()

        warning_records = [r for r in log_ctx.records if r.levelno == logging.WARNING]
        for rec in warning_records:
            self.assertIn("my_special_func", rec.message)

    @patch("btts_bot.retry.random.uniform", return_value=0.0)
    @patch("btts_bot.retry.time.sleep")
    def test_no_logs_on_success(self, mock_sleep, mock_uniform):
        @with_retry
        def happy():
            return "ok"

        # assertLogs raises AssertionError if no logs captured — so we check manually
        with self.assertRaises(AssertionError):
            with self.assertLogs("btts_bot.retry", level="WARNING"):
                happy()


class TestWithRetryExponentialBackoff(unittest.TestCase):
    """Verify delay computation follows exponential backoff."""

    @patch("btts_bot.retry.random.uniform", return_value=0.0)
    @patch("btts_bot.retry.time.sleep")
    def test_exponential_delays(self, mock_sleep, mock_uniform):
        """Delays should be 1, 2, 4, 8, 16 seconds (BASE_DELAY * 2^attempt)."""

        @with_retry
        def always_fails():
            raise RuntimeError("fail")

        always_fails()

        expected_delays = [1.0, 2.0, 4.0, 8.0, 16.0]
        actual_delays = [call.args[0] for call in mock_sleep.call_args_list]
        self.assertEqual(actual_delays, expected_delays)

    @patch("btts_bot.retry.random.uniform", return_value=0.0)
    @patch("btts_bot.retry.time.sleep")
    def test_delay_capped_at_max(self, mock_sleep, mock_uniform):
        """Delay is capped at MAX_DELAY (30s) regardless of attempt count."""
        from btts_bot.retry import MAX_DELAY

        attempts = []

        @with_retry
        def always_fails():
            attempts.append(1)
            raise RuntimeError("fail")

        always_fails()

        for call in mock_sleep.call_args_list:
            self.assertLessEqual(call.args[0], MAX_DELAY)


if __name__ == "__main__":
    unittest.main()
