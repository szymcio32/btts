"""Scheduled job management for market fetching and polling."""

from __future__ import annotations

import logging
from datetime import timezone
from typing import TYPE_CHECKING

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

if TYPE_CHECKING:
    from btts_bot.core.market_discovery import MarketDiscoveryService

logger = logging.getLogger(__name__)


class SchedulerService:
    """Manages scheduled jobs using APScheduler BackgroundScheduler."""

    def __init__(
        self,
        daily_fetch_hour_utc: int,
        discovery_service: MarketDiscoveryService,
    ) -> None:
        self._daily_fetch_hour_utc = daily_fetch_hour_utc
        self._discovery_service = discovery_service
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

    def _daily_market_fetch(self) -> None:
        """Callback for the daily market fetch cron job."""
        logger.info("Daily scheduled market fetch starting")
        count = self._discovery_service.discover_markets()
        logger.info("Daily scheduled market fetch complete: %d new markets", count)
