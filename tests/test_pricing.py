"""Tests for pricing configuration."""

import pytest
from src.utils.config import PricingConfig


class TestPricingConfig:
    """Tests for PricingConfig."""

    def test_get_tier_nano(self):
        """Test nano tier detection."""
        pricing = PricingConfig()
        assert pricing.get_tier(5000) == "nano"

    def test_get_tier_micro(self):
        """Test micro tier detection."""
        pricing = PricingConfig()
        assert pricing.get_tier(25000) == "micro"

    def test_get_tier_mid(self):
        """Test mid tier detection."""
        pricing = PricingConfig()
        assert pricing.get_tier(100000) == "mid"

    def test_get_tier_macro(self):
        """Test macro tier detection."""
        pricing = PricingConfig()
        assert pricing.get_tier(750000) == "macro"

    def test_get_tier_mega(self):
        """Test mega tier detection."""
        pricing = PricingConfig()
        assert pricing.get_tier(2000000) == "mega"

    def test_calculate_rate_basic(self):
        """Test basic rate calculation."""
        pricing = PricingConfig()
        rate = pricing.calculate_rate(25000, "instagram_reel")
        # Should be in micro tier range
        assert 150 <= rate <= 500

    def test_calculate_rate_with_multiplier(self):
        """Test rate calculation with content type multiplier."""
        pricing = PricingConfig()

        reel_rate = pricing.calculate_rate(50000, "instagram_reel")
        story_rate = pricing.calculate_rate(50000, "instagram_story")

        # Story should be cheaper (0.5 multiplier vs 1.0)
        assert story_rate < reel_rate

    def test_get_max_offer(self):
        """Test max offer calculation."""
        pricing = PricingConfig()
        max_offer = pricing.get_max_offer(100)
        # Should be 20% higher (based on config)
        assert max_offer == 120

    def test_should_auto_approve_under_threshold(self):
        """Test auto-approve for small amounts."""
        pricing = PricingConfig()
        assert pricing.should_auto_approve(50)
        assert pricing.should_auto_approve(99)

    def test_should_not_auto_approve_over_threshold(self):
        """Test no auto-approve for larger amounts."""
        pricing = PricingConfig()
        assert not pricing.should_auto_approve(100)
        assert not pricing.should_auto_approve(500)

    def test_should_escalate_high_amounts(self):
        """Test escalation for high-value deals."""
        pricing = PricingConfig()
        assert pricing.should_escalate(6000)
        assert pricing.should_escalate(10000)

    def test_should_not_escalate_normal_amounts(self):
        """Test no escalation for normal amounts."""
        pricing = PricingConfig()
        assert not pricing.should_escalate(500)
        assert not pricing.should_escalate(2000)
