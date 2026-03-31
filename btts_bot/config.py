"""
Pydantic configuration models for btts-bot.
Implemented in Story 1.2.
"""

from pathlib import Path
import sys

import yaml
from pydantic import BaseModel, Field, ValidationError, field_validator


class LeagueConfig(BaseModel):
    name: str
    abbreviation: str


class BttsConfig(BaseModel):
    order_size: int = Field(gt=0)
    price_diff: float = Field(gt=0, lt=1.0)
    min_order_size: int = Field(default=5, gt=0)
    buy_expiration_hours: int = Field(default=12, gt=0)


class LiquidityConfig(BaseModel):
    standard_depth: int
    deep_book_threshold: int
    low_liquidity_total: int
    tick_offset: float


class TimingConfig(BaseModel):
    daily_fetch_hour_utc: int = Field(ge=0, le=23)
    fill_poll_interval_seconds: int = Field(default=30, gt=0)
    pre_kickoff_minutes: int = Field(default=10, gt=0)


class LoggingConfig(BaseModel):
    level: str = "INFO"
    file_path: str = "btts_bot.log"
    max_bytes: int = Field(default=10_485_760, gt=0)
    backup_count: int = Field(default=5, ge=0)

    @field_validator("level")
    @classmethod
    def validate_log_level(cls, value: str) -> str:
        valid_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        normalized = value.upper()
        if normalized not in valid_levels:
            allowed = ", ".join(sorted(valid_levels))
            raise ValueError(f"Invalid log level '{value}'. Must be one of: {allowed}")
        return normalized


class BotConfig(BaseModel):
    leagues: list[LeagueConfig] = Field(min_length=1)
    btts: BttsConfig
    liquidity: LiquidityConfig
    timing: TimingConfig
    logging: LoggingConfig
    data_file: str = Field(min_length=1)  # Path to the local JSON data file with games/markets

    @field_validator("data_file")
    @classmethod
    def validate_data_file(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("data_file must not be empty")
        return value


def load_config(config_path: Path) -> BotConfig:
    if not config_path.exists():
        print(f"Error: Config file not found: {config_path}", file=sys.stderr)
        raise SystemExit(1)

    try:
        data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as error:
        print(f"Error: Invalid YAML in {config_path}: {error}", file=sys.stderr)
        raise SystemExit(1) from error

    if data is None:
        print(f"Error: Config file is empty: {config_path}", file=sys.stderr)
        raise SystemExit(1)

    try:
        return BotConfig.model_validate(data)
    except ValidationError as error:
        print(f"Error: Invalid configuration in {config_path}:\n{error}", file=sys.stderr)
        raise SystemExit(1) from error
