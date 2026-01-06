"""Configuration loader for YAML config files."""

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Environment-based settings."""

    # API Keys (from environment)
    anthropic_api_key: str = ""

    # Slack credentials
    slack_bot_token: str = ""
    slack_signing_secret: str = ""
    slack_app_token: str = ""  # Required for Socket Mode (starts with xapp-)

    # Gmail OAuth paths
    gmail_credentials_file: str = "credentials.json"
    gmail_token_file: str = "token.json"

    # Database
    database_url: str = "sqlite:///./influencer_automation.db"

    # App settings
    environment: str = "development"
    log_level: str = "INFO"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


def get_config_path() -> Path:
    """Get the config directory path."""
    return Path(__file__).parent.parent.parent / "config"


@lru_cache
def load_yaml_config(filename: str) -> dict[str, Any]:
    """Load a YAML configuration file."""
    config_path = get_config_path() / filename
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with open(config_path, "r") as f:
        return yaml.safe_load(f)


@lru_cache
def get_settings() -> Settings:
    """Get application settings."""
    return Settings()


def get_pricing() -> dict[str, Any]:
    """Get pricing configuration."""
    return load_yaml_config("pricing.yaml")


def get_templates() -> dict[str, Any]:
    """Get email templates configuration."""
    return load_yaml_config("templates.yaml")


def get_rules() -> dict[str, Any]:
    """Get automation rules configuration."""
    return load_yaml_config("rules.yaml")


def get_app_config() -> dict[str, Any]:
    """Get main application settings from YAML."""
    return load_yaml_config("settings.yaml")


class PricingConfig:
    """Helper class for pricing calculations."""

    def __init__(self):
        self.config = get_pricing()["pricing"]

    def get_tier(self, follower_count: int) -> str:
        """Determine influencer tier based on follower count."""
        for tier_name, tier_config in self.config["tiers"].items():
            min_followers = tier_config["followers_min"]
            max_followers = tier_config.get("followers_max")

            if min_followers <= follower_count:
                if max_followers is None or follower_count <= max_followers:
                    return tier_name
        return "nano"  # Default to lowest tier

    def get_rate_range(self, tier: str) -> tuple[float, float]:
        """Get min/max rate for a tier."""
        tier_config = self.config["tiers"].get(tier, self.config["tiers"]["nano"])
        return tier_config["rate_min"], tier_config["rate_max"]

    def calculate_rate(
        self, follower_count: int, content_type: str = "instagram_reel"
    ) -> float:
        """Calculate suggested rate for an influencer."""
        tier = self.get_tier(follower_count)
        rate_min, rate_max = self.get_rate_range(tier)

        # Base rate is midpoint of range
        base_rate = (rate_min + rate_max) / 2

        # Apply content multiplier
        multiplier = self.config["content_multipliers"].get(content_type, 1.0)

        return round(base_rate * multiplier, 2)

    def get_max_offer(self, initial_offer: float) -> float:
        """Get maximum we can offer (initial + max increase %)."""
        max_increase = self.config["negotiation"]["max_increase_percent"]
        return round(initial_offer * (1 + max_increase / 100), 2)

    def should_auto_approve(self, amount: float) -> bool:
        """Check if deal amount qualifies for auto-approval."""
        threshold = self.config["negotiation"]["auto_approve_under"]
        return amount < threshold

    def should_escalate(self, amount: float) -> bool:
        """Check if deal amount requires escalation."""
        threshold = self.config["negotiation"]["escalate_over"]
        return amount > threshold
