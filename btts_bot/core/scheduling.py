"""Scheduled job management for market fetching and polling."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger

from btts_bot.config import TimingConfig
from btts_bot.core.pre_kickoff import PreKickoffService

if TYPE_CHECKING:
    from btts_bot.core.market_discovery import MarketDiscoveryService

logger = logging.getLogger(__name__)


class SchedulerService:
    """Manages scheduled jobs using APScheduler BackgroundScheduler."""

    def __init__(
        self,
        daily_fetch_hour_utc: int,
        discovery_service: MarketDiscoveryService,
        pre_kickoff_service: PreKickoffService,
        timing_config: TimingConfig,
    ) -> None:
        self._daily_fetch_hour_utc = daily_fetch_hour_utc
        self._discovery_service = discovery_service
        self._pre_kickoff_service = pre_kickoff_service
        self._timing = timing_config
        self._scheduler = BackgroundScheduler(timezone=timezone.utc)

    @property
    def scheduler(self) -> BackgroundScheduler:
        """Expose scheduler for future stories to add jobs."""
        return self._scheduler

    def start(self) -> None:
        """Add scheduled jobs and start the scheduler."""
        self._scheduler.add_job(
            func=self._daily_market_fetch,
            trigger=CronTrigger(hour=self._daily_fetch_hour_utc, timezone=timezone.utc),
            id="daily_market_fetch",
            name="Daily market fetch",
            replace_existing=True,
            misfire_grace_time=3600,
        )
        self._scheduler.start()
        logger.info(
            "Scheduler started: daily market fetch at %02d:00 UTC",
            self._daily_fetch_hour_utc,
        )

    def shutdown(self) -> None:
        """Shut down the scheduler without waiting for running jobs."""
        self._scheduler.shutdown(wait=False)
        logger.info("Scheduler shut down")

    def schedule_pre_kickoff(self, token_id: str, kickoff_time: datetime) -> None:
        """Register a one-shot DateTrigger for pre-kickoff consolidation.

        Fires at ``kickoff_time - pre_kickoff_minutes``.  Idempotent: calling
        with the same token_id again replaces the existing job.

        Does nothing (with a WARNING) if the trigger time is already in the past.
        """
        pre_kickoff_time = kickoff_time - timedelta(minutes=self._timing.pre_kickoff_minutes)

        if pre_kickoff_time <= datetime.now(timezone.utc):
            logger.warning(
                "Pre-kickoff trigger for token=%s is in the past (kickoff=%s), skipping",
                token_id,
                kickoff_time.isoformat(),
            )
            return

        self._scheduler.add_job(
            func=self._pre_kickoff_service.handle_pre_kickoff,
            trigger=DateTrigger(run_date=pre_kickoff_time),
            args=[token_id],
            id=f"pre_kickoff_{token_id}",
            name=f"Pre-kickoff: {token_id}",
            replace_existing=True,
            misfire_grace_time=300,  # 5-minute grace for misfired triggers
        )
        logger.info(
            "Pre-kickoff trigger scheduled: token=%s at %s",
            token_id,
            pre_kickoff_time.isoformat(),
        )

    def _daily_market_fetch(self) -> None:
        """Callback for the daily market fetch cron job."""
        logger.info("Daily scheduled market fetch starting")
        count = self._discovery_service.discover_markets()
        logger.info("Daily scheduled market fetch complete: %d new markets", count)
