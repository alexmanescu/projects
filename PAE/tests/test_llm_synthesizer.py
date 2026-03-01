"""Tests for app.services.analysis.llm_synthesizer."""

import time
from unittest.mock import MagicMock, patch, call

import pytest
import requests as req

from app.services.analysis.llm_synthesizer import (
    LLMResponse,
    LLMSynthesizer,
    LLMUnavailableError,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _make_synth(ollama_ok: bool = True, claude_ok: bool = True) -> LLMSynthesizer:
    """Build a synthesizer with mocked availability checks."""
    with patch.object(LLMSynthesizer, "_check_availability"):
        synth = LLMSynthesizer(
            ollama_url="http://localhost:11434",
            ollama_model="test-model",
            claude_key="sk-test" if claude_ok else "",
            claude_model="claude-test",
        )
    synth._ollama_available = ollama_ok
    synth._claude_available = claude_ok
    return synth


def _ollama_response(text: str, tokens: int = 50) -> LLMResponse:
    return LLMResponse(
        text=text, backend="ollama", model="test-model",
        latency_ms=100, tokens_out=tokens,
    )


def _claude_response(text: str, tokens_in: int = 80, tokens_out: int = 60) -> LLMResponse:
    return LLMResponse(
        text=text, backend="claude", model="claude-test",
        latency_ms=800, tokens_in=tokens_in, tokens_out=tokens_out,
    )


# ── LLMResponse.tokens_used ──────────────────────────────────────────────────

class TestLLMResponse:
    def test_tokens_used_sums_in_and_out(self):
        r = LLMResponse("text", "claude", "m", 100, tokens_in=80, tokens_out=60)
        assert r.tokens_used == 140

    def test_tokens_used_none_when_missing(self):
        r = LLMResponse("text", "ollama", "m", 100, tokens_out=50)
        assert r.tokens_used is None

    def test_tokens_used_none_when_both_none(self):
        r = LLMResponse("text", "ollama", "m", 100)
        assert r.tokens_used is None


# ── _check_availability ───────────────────────────────────────────────────────

class TestCheckAvailability:
    def test_ollama_available_on_200(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        synth = _make_synth(ollama_ok=False, claude_ok=False)
        synth._http = MagicMock()
        synth._http.get.return_value = mock_resp

        synth._check_availability()
        assert synth._ollama_available is True

    def test_ollama_unavailable_on_connection_error(self):
        synth = _make_synth(ollama_ok=True, claude_ok=False)
        synth._http = MagicMock()
        synth._http.get.side_effect = req.ConnectionError("refused")

        synth._check_availability()
        assert synth._ollama_available is False

    def test_ollama_unavailable_on_non_200(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 503
        synth = _make_synth(ollama_ok=True, claude_ok=False)
        synth._http = MagicMock()
        synth._http.get.return_value = mock_resp

        synth._check_availability()
        assert synth._ollama_available is False

    def test_claude_available_when_key_set(self):
        synth = _make_synth(ollama_ok=False, claude_ok=False)
        synth._claude_key = "sk-real-key"
        synth._http = MagicMock()
        synth._http.get.side_effect = req.ConnectionError()

        synth._check_availability()
        assert synth._claude_available is True

    def test_claude_unavailable_when_no_key(self):
        synth = _make_synth(ollama_ok=False, claude_ok=False)
        synth._claude_key = ""
        synth._http = MagicMock()
        synth._http.get.side_effect = req.ConnectionError()

        synth._check_availability()
        assert synth._claude_available is False

    def test_check_availability_never_raises(self):
        synth = _make_synth()
        synth._http = MagicMock()
        synth._http.get.side_effect = RuntimeError("unexpected")
        # Must not propagate
        synth._check_availability()


# ── is_available ──────────────────────────────────────────────────────────────

class TestIsAvailable:
    def test_true_when_ollama_only(self):
        synth = _make_synth(ollama_ok=True, claude_ok=False)
        assert synth.is_available() is True

    def test_true_when_claude_only(self):
        synth = _make_synth(ollama_ok=False, claude_ok=True)
        assert synth.is_available() is True

    def test_false_when_neither(self):
        synth = _make_synth(ollama_ok=False, claude_ok=False)
        assert synth.is_available() is False


# ── _strip_thinking_tags ──────────────────────────────────────────────────────

class TestStripThinkingTags:
    def test_removes_think_block(self):
        text = "<think>some internal reasoning</think>Final answer."
        assert LLMSynthesizer._strip_thinking_tags(text) == "Final answer."

    def test_removes_multiline_think_block(self):
        text = "<think>\nline1\nline2\n</think>Result"
        assert LLMSynthesizer._strip_thinking_tags(text) == "Result"

    def test_no_tags_unchanged(self):
        text = "Plain response."
        assert LLMSynthesizer._strip_thinking_tags(text) == "Plain response."

    def test_case_insensitive(self):
        text = "<THINK>ignored</THINK>answer"
        assert LLMSynthesizer._strip_thinking_tags(text) == "answer"

    def test_strips_surrounding_whitespace(self):
        text = "<think>...</think>   answer   "
        assert LLMSynthesizer._strip_thinking_tags(text) == "answer"

    def test_multiple_think_blocks(self):
        text = "<think>a</think>middle<think>b</think>end"
        assert LLMSynthesizer._strip_thinking_tags(text) == "middleend"


# ── _parse_float ──────────────────────────────────────────────────────────────

class TestParseFloat:
    def test_parses_decimal_score(self):
        assert LLMSynthesizer._parse_float("0.75") == pytest.approx(0.75)

    def test_parses_one(self):
        assert LLMSynthesizer._parse_float("1.0") == pytest.approx(1.0)

    def test_parses_zero(self):
        assert LLMSynthesizer._parse_float("0.00") == pytest.approx(0.0)

    def test_extracts_from_sentence(self):
        result = LLMSynthesizer._parse_float("The confidence score is 0.82 based on the data.")
        assert result == pytest.approx(0.82)

    def test_returns_default_for_garbage(self):
        assert LLMSynthesizer._parse_float("no numbers here at all", default=0.3) == 0.3

    def test_returns_default_for_empty(self):
        assert LLMSynthesizer._parse_float("", default=0.5) == 0.5

    def test_clamps_above_one(self):
        # A value > 1 from the fallback path should be ignored → default
        result = LLMSynthesizer._parse_float("5.3", default=0.5)
        assert result == 0.5

    @pytest.mark.parametrize("text,expected", [
        ("0.0", 0.0), ("0.5", 0.5), ("0.99", 0.99), ("1.0", 1.0),
    ])
    def test_parametrized_valid_scores(self, text, expected):
        assert LLMSynthesizer._parse_float(text) == pytest.approx(expected)


# ── Prompt builders ───────────────────────────────────────────────────────────

class TestBuildThesisPrompt:
    def test_includes_topic(self):
        data = {"topic": "Russia sanctions", "western_count": 10, "asia_count": 2,
                "gap_ratio": 5.0, "article_titles": ["Title A", "Title B"]}
        prompt = LLMSynthesizer._build_thesis_prompt(data)
        assert "Russia sanctions" in prompt

    def test_includes_coverage_counts(self):
        data = {"topic": "T", "western_count": 7, "asia_count": 3, "gap_ratio": 2.3,
                "article_titles": []}
        prompt = LLMSynthesizer._build_thesis_prompt(data)
        assert "7" in prompt
        assert "3" in prompt

    def test_includes_article_titles(self):
        data = {"topic": "T", "western_count": 1, "asia_count": 1, "gap_ratio": 1.0,
                "article_titles": ["Specific Headline Here"]}
        prompt = LLMSynthesizer._build_thesis_prompt(data)
        assert "Specific Headline Here" in prompt

    def test_caps_titles_at_ten(self):
        data = {"topic": "T", "western_count": 1, "asia_count": 1, "gap_ratio": 1.0,
                "article_titles": [f"Title {i}" for i in range(20)]}
        prompt = LLMSynthesizer._build_thesis_prompt(data)
        assert "Title 10" not in prompt
        assert "Title 9" in prompt

    def test_empty_titles_handled(self):
        data = {"topic": "T", "western_count": 0, "asia_count": 0, "gap_ratio": 0,
                "article_titles": []}
        prompt = LLMSynthesizer._build_thesis_prompt(data)
        assert "none" in prompt.lower()


class TestBuildExitPrompt:
    def test_includes_ticker(self):
        pos = {"ticker": "LMT", "entry_price": 450.0, "current_price": 480.0,
               "thesis": "Defence spending thesis", "return_pct": 6.7}
        prompt = LLMSynthesizer._build_exit_prompt(pos, [])
        assert "LMT" in prompt

    def test_includes_return_pct(self):
        pos = {"ticker": "X", "entry_price": 100, "current_price": 95,
               "thesis": "T", "return_pct": -5.0}
        prompt = LLMSynthesizer._build_exit_prompt(pos, [])
        assert "-5.0" in prompt

    def test_includes_news_headlines(self):
        pos = {"ticker": "X", "entry_price": 100, "current_price": 100,
               "thesis": "T", "return_pct": 0}
        news = [{"title": "Specific News Event Here"}]
        prompt = LLMSynthesizer._build_exit_prompt(pos, news)
        assert "Specific News Event Here" in prompt

    def test_no_news_handled(self):
        pos = {"ticker": "X", "entry_price": 100, "current_price": 100,
               "thesis": "T", "return_pct": 0}
        prompt = LLMSynthesizer._build_exit_prompt(pos, [])
        assert "no recent news" in prompt.lower()


# ── _call_with_retry ──────────────────────────────────────────────────────────

class TestCallWithRetry:
    def setup_method(self):
        self.synth = _make_synth()

    def test_returns_on_first_success(self):
        resp = _ollama_response("ok")
        fn = MagicMock(return_value=resp)
        result = self.synth._call_with_retry(fn, max_retries=3, base_delay=0)
        assert result.text == "ok"
        fn.assert_called_once()

    def test_retries_on_failure_then_succeeds(self):
        resp = _ollama_response("ok")
        fn = MagicMock(side_effect=[RuntimeError("fail"), resp])
        result = self.synth._call_with_retry(fn, max_retries=2, base_delay=0)
        assert result.text == "ok"
        assert fn.call_count == 2

    def test_raises_after_max_retries(self):
        fn = MagicMock(side_effect=RuntimeError("always fails"))
        with pytest.raises(RuntimeError, match="always fails"):
            self.synth._call_with_retry(fn, max_retries=2, base_delay=0)
        assert fn.call_count == 2

    def test_kwargs_forwarded(self):
        resp = _ollama_response("ok")
        fn = MagicMock(return_value=resp)
        self.synth._call_with_retry(fn, max_retries=1, base_delay=0,
                                    temperature=0.7, max_tokens=500)
        fn.assert_called_once_with(temperature=0.7, max_tokens=500)


# ── generate_thesis routing ───────────────────────────────────────────────────

class TestGenerateThesis:
    _PATTERN = {
        "topic": "Russia sanctions", "western_count": 8, "asia_count": 2,
        "gap_ratio": 4.0, "article_titles": ["Headline A", "Headline B"],
    }

    def test_uses_ollama_when_available(self):
        synth = _make_synth(ollama_ok=True, claude_ok=True)
        with patch.object(synth, "_call_ollama", return_value=_ollama_response("Thesis.")) as mock_ollama:
            result = synth.generate_thesis(self._PATTERN, strategy_id=1)
        mock_ollama.assert_called_once()
        assert result == "Thesis."

    def test_falls_back_to_claude_when_ollama_unavailable(self):
        synth = _make_synth(ollama_ok=False, claude_ok=True)
        with patch.object(synth, "_call_claude", return_value=_claude_response("Claude thesis.")) as mock_claude:
            result = synth.generate_thesis(self._PATTERN, strategy_id=1)
        mock_claude.assert_called_once()
        assert result == "Claude thesis."

    def test_falls_back_to_claude_when_ollama_errors(self):
        synth = _make_synth(ollama_ok=True, claude_ok=True)
        with patch.object(synth, "_call_ollama", side_effect=RuntimeError("timeout")):
            with patch.object(synth, "_call_claude", return_value=_claude_response("Fallback.")):
                result = synth.generate_thesis(self._PATTERN, strategy_id=1)
        assert result == "Fallback."

    def test_raises_when_both_unavailable(self):
        synth = _make_synth(ollama_ok=False, claude_ok=False)
        with pytest.raises(LLMUnavailableError):
            synth.generate_thesis(self._PATTERN, strategy_id=1)

    def test_raises_when_both_error(self):
        synth = _make_synth(ollama_ok=True, claude_ok=True)
        with patch.object(synth, "_call_ollama", side_effect=RuntimeError("ollama fail")):
            with patch.object(synth, "_call_claude", side_effect=RuntimeError("claude fail")):
                with pytest.raises(LLMUnavailableError):
                    synth.generate_thesis(self._PATTERN, strategy_id=1)


# ── analyze_exit_signal routing ───────────────────────────────────────────────

class TestAnalyzeExitSignal:
    _POS = {"ticker": "LMT", "entry_price": 450, "current_price": 480,
             "thesis": "Defence spending", "return_pct": 6.7}
    _NEWS = [{"title": "Pentagon budget approved"}]

    def test_uses_claude_when_available(self):
        synth = _make_synth(ollama_ok=True, claude_ok=True)
        with patch.object(synth, "_call_claude", return_value=_claude_response("HOLD.")) as mock_c:
            result = synth.analyze_exit_signal(self._POS, self._NEWS)
        mock_c.assert_called_once()
        assert result == "HOLD."

    def test_falls_back_to_ollama_when_claude_unavailable(self):
        synth = _make_synth(ollama_ok=True, claude_ok=False)
        with patch.object(synth, "_call_ollama", return_value=_ollama_response("EXIT.")) as mock_o:
            result = synth.analyze_exit_signal(self._POS, self._NEWS)
        mock_o.assert_called_once()
        assert result == "EXIT."

    def test_falls_back_to_ollama_when_claude_errors(self):
        synth = _make_synth(ollama_ok=True, claude_ok=True)
        with patch.object(synth, "_call_claude", side_effect=RuntimeError("API error")):
            with patch.object(synth, "_call_ollama", return_value=_ollama_response("REDUCE.")):
                result = synth.analyze_exit_signal(self._POS, self._NEWS)
        assert result == "REDUCE."

    def test_raises_when_both_unavailable(self):
        synth = _make_synth(ollama_ok=False, claude_ok=False)
        with pytest.raises(LLMUnavailableError):
            synth.analyze_exit_signal(self._POS, self._NEWS)


# ── score_signal_strength ─────────────────────────────────────────────────────

class TestScoreSignalStrength:
    def test_returns_parsed_float(self):
        synth = _make_synth(ollama_ok=True, claude_ok=False)
        with patch.object(synth, "_call_ollama", return_value=_ollama_response("0.73")):
            score = synth.score_signal_strength(["Russia", "LMT"], {"sentiment": "bullish"})
        assert score == pytest.approx(0.73)

    def test_returns_default_when_ollama_unavailable(self):
        synth = _make_synth(ollama_ok=False, claude_ok=False)
        score = synth.score_signal_strength(["entity"], {"sentiment": "neutral"})
        assert score == pytest.approx(0.5)

    def test_returns_default_when_ollama_errors(self):
        synth = _make_synth(ollama_ok=True, claude_ok=False)
        with patch.object(synth, "_call_ollama", side_effect=RuntimeError("down")):
            score = synth.score_signal_strength([], {})
        assert score == pytest.approx(0.5)

    def test_parses_float_embedded_in_text(self):
        synth = _make_synth(ollama_ok=True, claude_ok=False)
        with patch.object(synth, "_call_ollama", return_value=_ollama_response(
            "Based on the evidence, I would rate this 0.68 confidence."
        )):
            score = synth.score_signal_strength(["Iran"], {"sentiment": "bearish"})
        assert score == pytest.approx(0.68)

    def test_score_clamped_to_0_1(self):
        synth = _make_synth(ollama_ok=True, claude_ok=False)
        with patch.object(synth, "_call_ollama", return_value=_ollama_response("0.999")):
            score = synth.score_signal_strength([], {})
        assert 0.0 <= score <= 1.0

    def test_does_not_use_claude_as_fallback(self):
        """score_signal_strength should never call Claude — just return default."""
        synth = _make_synth(ollama_ok=False, claude_ok=True)
        with patch.object(synth, "_call_claude") as mock_claude:
            score = synth.score_signal_strength([], {})
        mock_claude.assert_not_called()
        assert score == pytest.approx(0.5)
