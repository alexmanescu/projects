"""Migration: Fix DECIMAL(3,2) → DECIMAL(5,2) on opportunities table.

Run once against the remote MySQL database:

    python scripts/migrate_fix_decimals.py

Safe to re-run — ALTER TABLE on an already-correct column is a no-op in MySQL.
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from app.core.database import engine


def run() -> None:
    with engine.connect() as conn:
        # ── 1. Widen stop_loss_pct ─────────────────────────────────────────────
        print("Altering stop_loss_pct DECIMAL(3,2) → DECIMAL(5,2)...")
        conn.execute(text(
            "ALTER TABLE opportunities MODIFY COLUMN stop_loss_pct DECIMAL(5,2)"
        ))
        print("  ✅ stop_loss_pct done")

        # ── 2. Widen confluence_score ──────────────────────────────────────────
        print("Altering confluence_score DECIMAL(3,2) → DECIMAL(5,2)...")
        conn.execute(text(
            "ALTER TABLE opportunities MODIFY COLUMN confluence_score DECIMAL(5,2)"
        ))
        print("  ✅ confluence_score done")

        # ── 3. Fix truncated stop_loss_pct values in existing pending rows ─────
        print("Restoring truncated stop_loss_pct=9.99 → 15.0 on pending rows...")
        result = conn.execute(text(
            "UPDATE opportunities "
            "SET stop_loss_pct = 15.0 "
            "WHERE stop_loss_pct = 9.99 AND status = 'pending'"
        ))
        print(f"  ✅ {result.rowcount} row(s) updated")

        conn.commit()

        # ── 4. Verify ──────────────────────────────────────────────────────────
        print("\nVerification — sample of pending opportunities:")
        rows = conn.execute(text(
            "SELECT id, ticker, stop_loss_pct, confluence_score, status "
            "FROM opportunities ORDER BY id DESC LIMIT 5"
        )).fetchall()
        for row in rows:
            print(f"  id={row.id}  ticker={row.ticker}  "
                  f"stop_loss_pct={row.stop_loss_pct}  "
                  f"confluence_score={row.confluence_score}  "
                  f"status={row.status}")

        print("\n✅ Migration complete.")


if __name__ == "__main__":
    run()
