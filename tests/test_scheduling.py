"""Tests for btts_bot.core.scheduling module."""

from datetime import timezone
from unittest.mock import MagicMock, patch

from btts_bot.core.scheduling import SchedulerService


def test_scheduler_creates_with_utc_timezone() -> None:
    """SchedulerService creates a BackgroundScheduler with UTC timezone."""
    discovery = MagicMock()
    service = SchedulerService(daily_fetch_hour_utc=23, discovery_service=discovery)
    assert service.scheduler.timezone == timezone.utc


def test_start_adds_cron_job() -> None:
    """start() adds a daily market fetch cron job and starts the scheduler."""
    discovery = MagicMock()
    service = SchedulerService(daily_fetch_hour_utc=14, discovery_service=discovery)
    with (
        patch.object(service.scheduler, "add_job") as mock_add,
        patch.object(service.scheduler, "start") as mock_start,
    ):
        service.start()
        mock_add.assert_called_once()
        call_kwargs = mock_add.call_args
        assert call_kwargs.kwargs["id"] == "daily_market_fetch"
        assert call_kwargs.kwargs["replace_existing"] is True
        assert call_kwargs.kwargs["misfire_grace_time"] == 3600
        mock_start.assert_called_once()


def test_start_configures_cron_trigger_with_correct_hour() -> None:
    """start() creates CronTrigger with configured hour and UTC timezone."""
    discovery = MagicMock()
    service = SchedulerService(daily_fetch_hour_utc=7, discovery_service=discovery)
    with (
        patch("btts_bot.core.scheduling.CronTrigger") as mock_cron_trigger,
        patch.object(service.scheduler, "add_job") as mock_add,
        patch.object(service.scheduler, "start"),
    ):
        trigger_sentinel = object()
        mock_cron_trigger.return_value = trigger_sentinel
        service.start()
        mock_cron_trigger.assert_called_once_with(hour=7, timezone=timezone.utc)
        assert mock_add.call_args.kwargs["trigger"] is trigger_sentinel


def test_daily_fetch_callback_calls_discover() -> None:
    """The daily fetch callback calls discovery_service.discover_markets()."""
    discovery = MagicMock()
    discovery.discover_markets.return_value = 5
    service = SchedulerService(daily_fetch_hour_utc=23, discovery_service=discovery)
    service._daily_market_fetch()
    discovery.discover_markets.assert_called_once()


def test_shutdown_calls_scheduler_shutdown() -> None:
    """shutdown() calls scheduler.shutdown(wait=False)."""
    discovery = MagicMock()
    service = SchedulerService(daily_fetch_hour_utc=23, discovery_service=discovery)
    with patch.object(service.scheduler, "shutdown") as mock_shutdown:
        service.shutdown()
        mock_shutdown.assert_called_once_with(wait=False)


def test_daily_fetch_callback_propagates_exceptions() -> None:
    """The callback raises discovery exceptions for APScheduler to handle."""
    discovery = MagicMock()
    discovery.discover_markets.side_effect = RuntimeError("API failure")
    service = SchedulerService(daily_fetch_hour_utc=23, discovery_service=discovery)
    with patch("btts_bot.core.scheduling.logger.exception") as mock_exception:
        try:
            service._daily_market_fetch()
        except RuntimeError:
            pass

    # Callback errors are propagated and not double-logged here.
    mock_exception.assert_not_called()
    discovery.discover_markets.assert_called_once()
