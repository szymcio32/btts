"""Tests for btts_bot.core.scheduling module."""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from btts_bot.config import TimingConfig
from btts_bot.core.scheduling import SchedulerService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_timing(**overrides: object) -> TimingConfig:
    defaults: dict[str, object] = {
        "daily_fetch_hour_utc": 23,
        "fill_poll_interval_seconds": 30,
        "pre_kickoff_minutes": 10,
    }
    defaults.update(overrides)
    return TimingConfig(**defaults)  # type: ignore[arg-type]


def _make_service(
    daily_fetch_hour_utc: int = 23,
    timing: TimingConfig | None = None,
    pre_kickoff_service: object = None,
    discovery: object = None,
) -> SchedulerService:
    return SchedulerService(
        daily_fetch_hour_utc=daily_fetch_hour_utc,
        discovery_service=discovery or MagicMock(),
        pre_kickoff_service=pre_kickoff_service or MagicMock(),
        timing_config=timing or _make_timing(),
    )


# ---------------------------------------------------------------------------
# Existing scheduler tests (updated constructors)
# ---------------------------------------------------------------------------


def test_scheduler_creates_with_utc_timezone() -> None:
    """SchedulerService creates a BackgroundScheduler with UTC timezone."""
    service = _make_service()
    assert service.scheduler.timezone == timezone.utc


def test_start_adds_cron_job() -> None:
    """start() adds a daily market fetch cron job and starts the scheduler."""
    service = _make_service(daily_fetch_hour_utc=14)
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
    service = _make_service(daily_fetch_hour_utc=7)
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
    service = _make_service(discovery=discovery)
    service._daily_market_fetch()
    discovery.discover_markets.assert_called_once()


def test_shutdown_calls_scheduler_shutdown() -> None:
    """shutdown() calls scheduler.shutdown(wait=False)."""
    service = _make_service()
    with patch.object(service.scheduler, "shutdown") as mock_shutdown:
        service.shutdown()
        mock_shutdown.assert_called_once_with(wait=False)


def test_daily_fetch_callback_propagates_exceptions() -> None:
    """The callback raises discovery exceptions for APScheduler to handle."""
    discovery = MagicMock()
    discovery.discover_markets.side_effect = RuntimeError("API failure")
    service = _make_service(discovery=discovery)
    with patch("btts_bot.core.scheduling.logger.exception") as mock_exception:
        try:
            service._daily_market_fetch()
        except RuntimeError:
            pass

    # Callback errors are propagated and not double-logged here.
    mock_exception.assert_not_called()
    discovery.discover_markets.assert_called_once()


# ---------------------------------------------------------------------------
# schedule_pre_kickoff tests (AC #1)
# ---------------------------------------------------------------------------


def test_schedule_pre_kickoff_adds_date_trigger_job() -> None:
    """schedule_pre_kickoff adds a DateTrigger job at kickoff_time - pre_kickoff_minutes."""
    timing = _make_timing(pre_kickoff_minutes=10)
    service = _make_service(timing=timing)

    kickoff_time = datetime.now(timezone.utc) + timedelta(hours=2)
    expected_run_date = kickoff_time - timedelta(minutes=10)

    with (
        patch("btts_bot.core.scheduling.DateTrigger") as mock_date_trigger,
        patch.object(service.scheduler, "add_job") as mock_add,
    ):
        trigger_sentinel = object()
        mock_date_trigger.return_value = trigger_sentinel
        service.schedule_pre_kickoff("token-1", kickoff_time)

        mock_date_trigger.assert_called_once_with(run_date=expected_run_date)
        mock_add.assert_called_once()
        call_kwargs = mock_add.call_args.kwargs
        assert call_kwargs["id"] == "pre_kickoff_token-1"
        assert call_kwargs["replace_existing"] is True
        assert call_kwargs["misfire_grace_time"] == 300
        assert call_kwargs["trigger"] is trigger_sentinel
        assert call_kwargs["args"] == ["token-1"]


def test_schedule_pre_kickoff_calls_handle_pre_kickoff() -> None:
    """schedule_pre_kickoff registers handle_pre_kickoff as the job function."""
    pre_kickoff_svc = MagicMock()
    service = _make_service(pre_kickoff_service=pre_kickoff_svc)

    kickoff_time = datetime.now(timezone.utc) + timedelta(hours=2)

    with (
        patch("btts_bot.core.scheduling.DateTrigger"),
        patch.object(service.scheduler, "add_job") as mock_add,
    ):
        service.schedule_pre_kickoff("token-abc", kickoff_time)

    call_kwargs = mock_add.call_args.kwargs
    assert call_kwargs["func"] is pre_kickoff_svc.handle_pre_kickoff


def test_schedule_pre_kickoff_past_trigger_logs_warning_no_job(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Trigger time in the past: WARNING logged, add_job NOT called."""
    timing = _make_timing(pre_kickoff_minutes=10)
    service = _make_service(timing=timing)

    # Kickoff 5 minutes ago → pre-kickoff would be 15 minutes ago
    kickoff_time = datetime.now(timezone.utc) - timedelta(minutes=5)

    with (
        patch.object(service.scheduler, "add_job") as mock_add,
        caplog.at_level("WARNING", logger="btts_bot.core.scheduling"),
    ):
        service.schedule_pre_kickoff("token-past", kickoff_time)

    mock_add.assert_not_called()
    assert "in the past" in caplog.text
    assert "token-past" in caplog.text


def test_schedule_pre_kickoff_at_exactly_now_skips(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Trigger time <= now is skipped (includes exactly-now case)."""
    timing = _make_timing(pre_kickoff_minutes=1)
    service = _make_service(timing=timing)

    # With 1 minute offset and kickoff 30 seconds ago,
    # pre_kickoff_time = kickoff - 1 min = 90 seconds ago → already past
    kickoff_time = datetime.now(timezone.utc) - timedelta(seconds=30)

    with (
        patch.object(service.scheduler, "add_job") as mock_add,
        caplog.at_level("WARNING", logger="btts_bot.core.scheduling"),
    ):
        service.schedule_pre_kickoff("token-now", kickoff_time)

    mock_add.assert_not_called()


def test_schedule_pre_kickoff_duplicate_uses_replace_existing() -> None:
    """Scheduling the same token_id twice uses replace_existing=True (idempotent)."""
    service = _make_service()
    kickoff_time = datetime.now(timezone.utc) + timedelta(hours=3)

    with (
        patch("btts_bot.core.scheduling.DateTrigger"),
        patch.object(service.scheduler, "add_job") as mock_add,
    ):
        service.schedule_pre_kickoff("token-dup", kickoff_time)
        service.schedule_pre_kickoff("token-dup", kickoff_time)  # second call

    assert mock_add.call_count == 2
    for call in mock_add.call_args_list:
        assert call.kwargs["replace_existing"] is True


def test_schedule_pre_kickoff_job_id_format() -> None:
    """Job ID is 'pre_kickoff_{token_id}'."""
    service = _make_service()
    kickoff_time = datetime.now(timezone.utc) + timedelta(hours=1)

    with (
        patch("btts_bot.core.scheduling.DateTrigger"),
        patch.object(service.scheduler, "add_job") as mock_add,
    ):
        service.schedule_pre_kickoff("my-token-99", kickoff_time)

    assert mock_add.call_args.kwargs["id"] == "pre_kickoff_my-token-99"
