"""Dynamic strategy loader — imports strategy modules from disk and manages DB records.

Strategy directories may contain hyphens (e.g. ``propaganda-arbitrage``), which
are illegal in Python dotted import paths.  All module loading uses
``importlib.util.spec_from_file_location`` to side-step this limitation.
"""

from __future__ import annotations

import importlib.util
import logging
import pathlib
from types import ModuleType
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

_STRATEGIES_ROOT = pathlib.Path(__file__).parent.parent.parent / "strategies"

# Module filenames we attempt to load for each strategy
_STRATEGY_MODULES = ("scraper_config", "pattern_rules", "llm_config")


class StrategyLoadError(Exception):
    """Raised when a required strategy module cannot be loaded."""


class StrategyLoader:
    """Load, register, and query PAE trading strategies.

    Strategies live under ``strategies/<name>/`` and expose Python modules.
    This class bridges those filesystem modules with the ``strategies`` DB table.
    """

    # ── Public API ────────────────────────────────────────────────────────────

    def load_strategy(self, strategy_name: str) -> dict:
        """Import all config modules for *strategy_name* and return a combined dict.

        Loads (if present):
        - ``scraper_config.py``  → keys: ``sources``, ``get_scrapers``, ``config``
        - ``pattern_rules.py``   → keys: ``pattern_rules``, ``patterns``
        - ``llm_config.py``      → keys: ``llm_config``, ``system_prompt``, …

        Args:
            strategy_name: Directory name under ``strategies/``
                (e.g. ``"propaganda-arbitrage"``).

        Returns:
            Combined config dict with a ``"name"`` key and one sub-key per
            loaded module.

        Raises:
            StrategyLoadError: If the strategy directory doesn't exist or
                ``scraper_config.py`` is missing.
        """
        strategy_dir = _STRATEGIES_ROOT / strategy_name
        if not strategy_dir.is_dir():
            raise StrategyLoadError(
                f"Strategy directory not found: {strategy_dir}\n"
                f"Available: {[d.name for d in _STRATEGIES_ROOT.iterdir() if d.is_dir()]}"
            )

        combined: dict = {"name": strategy_name}

        for module_name in _STRATEGY_MODULES:
            path = strategy_dir / f"{module_name}.py"
            if not path.exists():
                logger.debug("Strategy %s: %s.py not found — skipping", strategy_name, module_name)
                continue

            mod = self._load_module(path, f"_pae_{strategy_name}_{module_name}")

            if module_name == "scraper_config":
                combined["sources"] = getattr(mod, "CONFIG", {}).get("sources", [])
                combined["get_scrapers"] = getattr(mod, "get_scrapers", None)
                combined["config"] = getattr(mod, "CONFIG", {})
            elif module_name == "pattern_rules":
                combined["pattern_rules"] = getattr(mod, "PATTERN_RULES", [])
                combined["patterns"] = getattr(mod, "PATTERNS", {})
            elif module_name == "llm_config":
                combined["llm_config"] = getattr(mod, "LLM_CONFIG", {})
                combined["system_prompt"] = getattr(mod, "SYSTEM_PROMPT", "")
                combined["analysis_schema"] = getattr(mod, "ANALYSIS_SCHEMA", {})

        if "sources" not in combined:
            raise StrategyLoadError(
                f"Strategy {strategy_name!r} is missing scraper_config.py"
            )

        logger.info(
            "Loaded strategy %r: %d sources, %d pattern rules",
            strategy_name,
            len(combined.get("sources", [])),
            len(combined.get("pattern_rules", [])),
        )
        return combined

    def get_active_strategies(self, db: Session) -> list[dict]:
        """Return loaded configs for all strategies marked ``is_active=True`` in the DB.

        Strategies that fail to load from disk are logged and skipped, so a
        broken file does not prevent other strategies from running.

        Args:
            db: Active SQLAlchemy session (read-only).

        Returns:
            List of combined config dicts (same structure as ``load_strategy``),
            each extended with ``"db_id"`` and ``"db_version"``.
        """
        from app.models import Strategy

        rows = db.query(Strategy).filter(Strategy.is_active.is_(True)).all()
        configs: list[dict] = []

        for row in rows:
            try:
                cfg = self.load_strategy(row.name)
                cfg["db_id"] = row.id
                cfg["db_version"] = row.version
                configs.append(cfg)
            except StrategyLoadError:
                logger.error(
                    "Active strategy %r (id=%d) failed to load — skipping",
                    row.name, row.id, exc_info=True,
                )

        logger.info("get_active_strategies: %d/%d loaded successfully", len(configs), len(rows))
        return configs

    def register_strategy(
        self,
        db: Session,
        name: str,
        version: str = "0.1.0",
        thesis_path: str | None = None,
    ) -> int:
        """Insert a new strategy row and return its ``id``.

        If a strategy with *name* already exists, returns its existing ``id``
        without modifying the row (idempotent).

        Args:
            db: Active SQLAlchemy session (caller commits).
            name: Strategy slug (e.g. ``"propaganda-arbitrage"``).
            version: Semantic version string.
            thesis_path: Optional relative path to the strategy's ``thesis.md``.

        Returns:
            ``strategies.id`` of the new or existing row.
        """
        from app.models import Strategy

        existing = db.query(Strategy).filter(Strategy.name == name).first()
        if existing:
            logger.info("register_strategy: %r already exists (id=%d)", name, existing.id)
            return existing.id

        # Auto-detect thesis path if not supplied
        if thesis_path is None:
            candidate = _STRATEGIES_ROOT / name / "thesis.md"
            if candidate.exists():
                thesis_path = str(candidate)

        row = Strategy(
            name=name,
            version=version,
            thesis_md_path=thesis_path,
            is_active=False,   # must be activated explicitly
        )
        db.add(row)
        db.flush()   # populate row.id without full commit

        logger.info("register_strategy: inserted %r (id=%d)", name, row.id)
        return row.id

    # ── Internal ──────────────────────────────────────────────────────────────

    @staticmethod
    def _load_module(path: pathlib.Path, module_key: str) -> ModuleType:
        """Load a Python file as a module using spec-from-file-location."""
        spec = importlib.util.spec_from_file_location(module_key, path)
        if spec is None or spec.loader is None:
            raise StrategyLoadError(f"Cannot create import spec for {path}")
        mod = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(mod)
        except Exception as exc:
            raise StrategyLoadError(f"Error executing {path}: {exc}") from exc
        return mod
