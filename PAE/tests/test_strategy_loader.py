"""Tests for app.core.strategy_loader."""

import pathlib
from unittest.mock import MagicMock, patch

import pytest

from app.core.strategy_loader import StrategyLoader, StrategyLoadError


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_strategy_row(id: int, name: str, version: str = "0.1.0", is_active: bool = True):
    row = MagicMock()
    row.id = id
    row.name = name
    row.version = version
    row.is_active = is_active
    return row


def _make_db(rows: list = None):
    db = MagicMock()
    q = MagicMock()
    q.filter.return_value = q
    q.all.return_value = rows or []
    q.first.return_value = None
    db.query.return_value = q
    db.add = MagicMock()
    db.flush = MagicMock()
    return db


# ── load_strategy — integration against real files ────────────────────────────

class TestLoadStrategyIntegration:
    """These tests load the actual propaganda-arbitrage strategy from disk."""

    def setup_method(self):
        self.loader = StrategyLoader()

    def test_loads_propaganda_arbitrage(self):
        cfg = self.loader.load_strategy("propaganda-arbitrage")
        assert cfg["name"] == "propaganda-arbitrage"

    def test_has_sources(self):
        cfg = self.loader.load_strategy("propaganda-arbitrage")
        assert isinstance(cfg["sources"], list)
        assert len(cfg["sources"]) > 0

    def test_sources_have_required_fields(self):
        cfg = self.loader.load_strategy("propaganda-arbitrage")
        for src in cfg["sources"]:
            assert "name" in src
            assert "url" in src
            assert "category" in src

    def test_has_pattern_rules(self):
        cfg = self.loader.load_strategy("propaganda-arbitrage")
        assert isinstance(cfg.get("pattern_rules", []), list)
        assert len(cfg["pattern_rules"]) > 0

    def test_pattern_rules_have_required_fields(self):
        cfg = self.loader.load_strategy("propaganda-arbitrage")
        for rule in cfg["pattern_rules"]:
            assert "name" in rule
            assert "keywords" in rule
            assert "signal_type" in rule
            assert "confidence" in rule

    def test_has_patterns_dict(self):
        cfg = self.loader.load_strategy("propaganda-arbitrage")
        assert isinstance(cfg.get("patterns", {}), dict)
        assert "coverage_gap" in cfg["patterns"]

    def test_has_llm_config(self):
        cfg = self.loader.load_strategy("propaganda-arbitrage")
        assert isinstance(cfg.get("llm_config", {}), dict)
        assert "thesis_generation" in cfg["llm_config"]
        assert "exit_analysis" in cfg["llm_config"]

    def test_has_get_scrapers_callable(self):
        cfg = self.loader.load_strategy("propaganda-arbitrage")
        assert callable(cfg["get_scrapers"])
        scrapers = cfg["get_scrapers"]()
        assert isinstance(scrapers, list)

    def test_get_scrapers_returns_same_as_sources(self):
        cfg = self.loader.load_strategy("propaganda-arbitrage")
        assert cfg["get_scrapers"]() == cfg["sources"]

    def test_raises_for_unknown_strategy(self):
        with pytest.raises(StrategyLoadError, match="not found"):
            self.loader.load_strategy("nonexistent-strategy-xyz")


# ── load_strategy — unit tests with temp dirs ─────────────────────────────────

class TestLoadStrategyUnit:
    def test_raises_when_scraper_config_missing(self, tmp_path):
        loader = StrategyLoader()
        # Override _STRATEGIES_ROOT via monkeypatching the module-level constant
        import app.core.strategy_loader as sl_module
        original = sl_module._STRATEGIES_ROOT
        try:
            sl_module._STRATEGIES_ROOT = tmp_path
            (tmp_path / "empty-strategy").mkdir()
            with pytest.raises(StrategyLoadError):
                loader.load_strategy("empty-strategy")
        finally:
            sl_module._STRATEGIES_ROOT = original

    def test_raises_for_nonexistent_directory(self, tmp_path):
        import app.core.strategy_loader as sl_module
        original = sl_module._STRATEGIES_ROOT
        try:
            sl_module._STRATEGIES_ROOT = tmp_path
            with pytest.raises(StrategyLoadError, match="not found"):
                loader = StrategyLoader()
                loader.load_strategy("does-not-exist")
        finally:
            sl_module._STRATEGIES_ROOT = original

    def test_skips_missing_optional_modules(self, tmp_path):
        """A strategy with only scraper_config.py should still load."""
        import app.core.strategy_loader as sl_module
        original = sl_module._STRATEGIES_ROOT
        try:
            sl_module._STRATEGIES_ROOT = tmp_path
            strat_dir = tmp_path / "minimal-strat"
            strat_dir.mkdir()
            (strat_dir / "scraper_config.py").write_text(
                "CONFIG = {'name': 'minimal-strat', 'sources': []}\n"
                "def get_scrapers(): return CONFIG['sources']\n"
            )
            loader = StrategyLoader()
            cfg = loader.load_strategy("minimal-strat")
            assert cfg["name"] == "minimal-strat"
            assert cfg.get("pattern_rules", []) == []
            assert cfg.get("llm_config", {}) == {}
        finally:
            sl_module._STRATEGIES_ROOT = original

    def test_raises_on_syntax_error_in_module(self, tmp_path):
        import app.core.strategy_loader as sl_module
        original = sl_module._STRATEGIES_ROOT
        try:
            sl_module._STRATEGIES_ROOT = tmp_path
            strat_dir = tmp_path / "broken-strat"
            strat_dir.mkdir()
            (strat_dir / "scraper_config.py").write_text("this is not valid python !!!")
            loader = StrategyLoader()
            with pytest.raises(StrategyLoadError):
                loader.load_strategy("broken-strat")
        finally:
            sl_module._STRATEGIES_ROOT = original


# ── register_strategy ─────────────────────────────────────────────────────────

class TestRegisterStrategy:
    def setup_method(self):
        self.loader = StrategyLoader()

    def test_inserts_new_strategy_row(self):
        db = _make_db()
        db.query.return_value.filter.return_value.first.return_value = None

        # Give the flush a side-effect that sets row.id
        def flush_side_effect():
            pass
        db.flush.side_effect = flush_side_effect

        from app.models import Strategy as S
        with patch("app.core.strategy_loader.Strategy") as MockStrategy:
            mock_row = MagicMock()
            mock_row.id = 7
            MockStrategy.return_value = mock_row

            row_id = self.loader.register_strategy(db, "new-strategy", "1.0.0")

        db.add.assert_called_once_with(mock_row)
        db.flush.assert_called_once()

    def test_returns_existing_id_without_insert(self):
        existing = _make_strategy_row(id=5, name="existing-strategy")
        db = _make_db()
        db.query.return_value.filter.return_value.first.return_value = existing

        row_id = self.loader.register_strategy(db, "existing-strategy")
        assert row_id == 5
        db.add.assert_not_called()

    def test_is_active_false_by_default(self):
        db = _make_db()
        db.query.return_value.filter.return_value.first.return_value = None

        with patch("app.core.strategy_loader.Strategy") as MockStrategy:
            mock_row = MagicMock()
            mock_row.id = 1
            MockStrategy.return_value = mock_row
            self.loader.register_strategy(db, "test-strategy")

        _, kwargs = MockStrategy.call_args
        assert kwargs.get("is_active", True) is False

    def test_thesis_path_autodetected(self):
        """If thesis.md exists in the strategy dir, it should be set automatically."""
        db = _make_db()
        db.query.return_value.filter.return_value.first.return_value = None

        with patch("app.core.strategy_loader.Strategy") as MockStrategy:
            mock_row = MagicMock()
            mock_row.id = 1
            MockStrategy.return_value = mock_row
            # propaganda-arbitrage has a real thesis.md
            self.loader.register_strategy(db, "propaganda-arbitrage")

        _, kwargs = MockStrategy.call_args
        thesis = kwargs.get("thesis_md_path", "")
        assert thesis is not None
        assert "thesis.md" in (thesis or "")


# ── get_active_strategies ─────────────────────────────────────────────────────

class TestGetActiveStrategies:
    def setup_method(self):
        self.loader = StrategyLoader()

    def test_returns_loaded_configs(self):
        rows = [_make_strategy_row(1, "propaganda-arbitrage")]
        db = _make_db(rows)

        configs = self.loader.get_active_strategies(db)
        assert len(configs) == 1
        assert configs[0]["name"] == "propaganda-arbitrage"
        assert configs[0]["db_id"] == 1

    def test_broken_strategy_skipped_without_raising(self):
        rows = [
            _make_strategy_row(1, "propaganda-arbitrage"),
            _make_strategy_row(2, "nonexistent-strategy-xyz"),
        ]
        db = _make_db(rows)

        configs = self.loader.get_active_strategies(db)
        # Only the real strategy should load; broken one is skipped
        names = [c["name"] for c in configs]
        assert "propaganda-arbitrage" in names
        assert "nonexistent-strategy-xyz" not in names

    def test_empty_db_returns_empty_list(self):
        db = _make_db([])
        configs = self.loader.get_active_strategies(db)
        assert configs == []

    def test_db_id_and_version_added_to_config(self):
        rows = [_make_strategy_row(99, "propaganda-arbitrage", version="2.0.0")]
        db = _make_db(rows)

        configs = self.loader.get_active_strategies(db)
        assert configs[0]["db_id"] == 99
        assert configs[0]["db_version"] == "2.0.0"
