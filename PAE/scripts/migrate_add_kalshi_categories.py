#!/usr/bin/env python3
"""Safe idempotent migration: create the kalshi_categories table.

Run once before restarting workers after the self-growing categories update:

    python scripts/migrate_add_kalshi_categories.py

Safe to run multiple times — uses CREATE TABLE IF NOT EXISTS.
"""

import sys
from pathlib import Path

_repo_root = Path(__file__).parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

from app.core.config import settings
from app.core.database import engine

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS `kalshi_categories` (
    `id`                  INT           NOT NULL AUTO_INCREMENT,
    `term`                VARCHAR(100)  NOT NULL,
    `category`            VARCHAR(50)   NOT NULL,
    `status`              VARCHAR(20)   NOT NULL DEFAULT 'suggested',
    `source`              VARCHAR(200)  NULL,
    `telegram_message_id` BIGINT        NULL,
    `created_at`          TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `approved_at`         TIMESTAMP     NULL,
    PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""


def run() -> None:
    print(f"Connecting to: {settings.database_url[:40]}...")

    with engine.connect() as conn:
        conn.exec_driver_sql(_CREATE_TABLE)
        conn.commit()
        print("  OK  kalshi_categories table created (or already existed)")

    print("Migration complete.")


if __name__ == "__main__":
    run()
