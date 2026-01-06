#!/usr/bin/env python3
"""
Seed script to import influencers from a CSV file.

Usage:
    python scripts/seed_influencers.py influencers.csv

CSV format:
    email,name,platform,handle,follower_count,content_type,initial_rate
"""

import csv
import os
import sys
from argparse import ArgumentParser

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.database.repository import get_repository
from src.database.models import init_db
from src.utils.config import get_settings, PricingConfig
from src.utils.logging import setup_logging, get_logger


def main():
    parser = ArgumentParser(description="Import influencers from CSV")
    parser.add_argument("csv_file", help="Path to CSV file")
    parser.add_argument("--dry-run", action="store_true", help="Don't actually import")
    args = parser.parse_args()

    setup_logging("INFO")
    logger = get_logger("seed")

    # Initialize database
    settings = get_settings()
    init_db(settings.database_url)

    repo = get_repository()
    pricing = PricingConfig()

    if not os.path.exists(args.csv_file):
        logger.error(f"File not found: {args.csv_file}")
        sys.exit(1)

    imported = 0
    skipped = 0
    errors = 0

    with open(args.csv_file, "r") as f:
        reader = csv.DictReader(f)

        for row in reader:
            email = row.get("email", "").strip()
            if not email:
                logger.warning(f"Skipping row without email: {row}")
                skipped += 1
                continue

            # Check if already exists
            existing = repo.get_influencer_by_email(email)
            if existing:
                logger.info(f"Skipping existing influencer: {email}")
                skipped += 1
                continue

            # Parse data
            try:
                follower_count = int(row.get("follower_count", 0) or 0)
                tier = pricing.get_tier(follower_count) if follower_count else None

                # Calculate initial rate if not provided
                initial_rate = row.get("initial_rate")
                if initial_rate:
                    initial_rate = float(initial_rate)
                elif follower_count:
                    content_type = row.get("content_type", "instagram_reel")
                    initial_rate = pricing.calculate_rate(follower_count, content_type)

                if args.dry_run:
                    logger.info(
                        f"[DRY RUN] Would import: {email} "
                        f"({row.get('name')}, {follower_count} followers, ${initial_rate})"
                    )
                else:
                    repo.create_influencer(
                        email=email,
                        name=row.get("name"),
                        platform=row.get("platform"),
                        handle=row.get("handle"),
                        follower_count=follower_count,
                        tier=tier,
                        initial_rate=initial_rate,
                        content_type=row.get("content_type"),
                    )
                    logger.info(f"Imported: {email}")

                imported += 1

            except Exception as e:
                logger.error(f"Error importing {email}: {e}")
                errors += 1

    print(f"\n{'[DRY RUN] ' if args.dry_run else ''}Summary:")
    print(f"  Imported: {imported}")
    print(f"  Skipped: {skipped}")
    print(f"  Errors: {errors}")


if __name__ == "__main__":
    main()
