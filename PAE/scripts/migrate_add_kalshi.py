#!/usr/bin/env python3
"""Safe idempotent migration: add market_type + Kalshi columns to opportunities table.

Run once before restarting workers after the Kalshi integration update:

    python scripts/migrate_add_kalshi.py

Safe to run multiple times — checks SHOW COLUMNS before each ALTER.
"""

import sys
from pathlib import Path

_repo_root = Path(__file__).parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

from app.core.config import settings
from app.core.database import engine

_MIGRATIONS = [
    (
        "market_type",
        "ALTER TABLE opportunities ADD COLUMN market_type VARCHAR(20) NOT NULL DEFAULT 'us_stock'",
    ),
    (
        "kalshi_market_id",
        "ALTER TABLE opportunities ADD COLUMN kalshi_market_id VARCHAR(100)",
    ),
    (
        "kalshi_side",
        "ALTER TABLE opportunities ADD COLUMN kalshi_side VARCHAR(3)",
    ),
    (
        "kalshi_yes_price",
        "ALTER TABLE opportunities ADD COLUMN kalshi_yes_price DECIMAL(5,2)",
    ),
]


def column_exists(conn, table: str, column: str) -> bool:
    result = conn.exec_driver_sql(f"SHOW COLUMNS FROM `{table}` LIKE '{column}'")
    return result.fetchone() is not None


def run() -> None:
    print(f"Connecting to: {settings.database_url[:40]}...")

    with engine.connect() as conn:
        for col_name, alter_sql in _MIGRATIONS:
            if column_exists(conn, "opportunities", col_name):
                print(f"  SKIP  {col_name} (already exists)")
            else:
                conn.exec_driver_sql(alter_sql)
                conn.commit()
                print(f"  ADDED {col_name}")

    print("Migration complete.")


if __name__ == "__main__":
    run()
