"""Tests for app.utils.url_normalizer."""

import pytest
from app.utils.url_normalizer import normalize_url, urls_are_equivalent


class TestNormalizeUrl:
    # ── Scheme ────────────────────────────────────────────────────────────────

    def test_upgrades_http_to_https(self):
        assert normalize_url("http://example.com/page").startswith("https://")

    def test_keeps_https_scheme(self):
        assert normalize_url("https://example.com/page").startswith("https://")

    # ── Hostname ──────────────────────────────────────────────────────────────

    def test_lowercases_hostname(self):
        assert normalize_url("https://EXAMPLE.COM/page") == "https://example.com/page"

    def test_removes_www(self):
        assert normalize_url("https://www.example.com/page") == "https://example.com/page"

    def test_does_not_remove_non_www_subdomain(self):
        result = normalize_url("https://news.example.com/page")
        assert "news.example.com" in result

    # ── Port handling ─────────────────────────────────────────────────────────

    def test_removes_default_https_port(self):
        result = normalize_url("https://example.com:443/page")
        assert ":443" not in result

    def test_removes_default_http_port(self):
        result = normalize_url("http://example.com:80/page")
        assert ":80" not in result

    def test_preserves_non_default_port(self):
        result = normalize_url("https://example.com:8080/page")
        assert ":8080" in result

    # ── Path ──────────────────────────────────────────────────────────────────

    def test_strips_trailing_slash(self):
        assert normalize_url("https://example.com/path/") == "https://example.com/path"

    def test_strips_multiple_trailing_slashes(self):
        assert normalize_url("https://example.com/path///") == "https://example.com/path"

    def test_root_path_kept_as_slash(self):
        assert normalize_url("https://example.com") == "https://example.com/"

    def test_root_path_with_slash(self):
        assert normalize_url("https://example.com/") == "https://example.com/"

    def test_preserves_deep_path(self):
        result = normalize_url("https://example.com/news/2025/sanctions/article")
        assert "/news/2025/sanctions/article" in result

    # ── Query parameters ──────────────────────────────────────────────────────

    def test_strips_utm_source(self):
        url = "https://example.com/article?utm_source=twitter"
        assert normalize_url(url) == "https://example.com/article"

    def test_strips_utm_medium(self):
        url = "https://example.com/article?utm_medium=social"
        assert normalize_url(url) == "https://example.com/article"

    def test_strips_all_utm_prefixed_params(self):
        url = "https://example.com/article?utm_source=x&utm_medium=y&utm_campaign=z&utm_custom_field=w"
        assert normalize_url(url) == "https://example.com/article"

    def test_strips_fbclid(self):
        url = "https://example.com/article?fbclid=IwAR3abc123"
        assert normalize_url(url) == "https://example.com/article"

    def test_strips_gclid(self):
        url = "https://example.com/article?gclid=xyz"
        assert normalize_url(url) == "https://example.com/article"

    def test_strips_ref(self):
        url = "https://example.com/article?ref=newsletter"
        assert normalize_url(url) == "https://example.com/article"

    def test_preserves_meaningful_params(self):
        url = "https://example.com/search?q=tariffs&page=2"
        result = normalize_url(url)
        assert "q=tariffs" in result
        assert "page=2" in result

    def test_strips_tracking_but_keeps_meaningful(self):
        """Core example from the prompt spec."""
        url = "https://example.com/article?utm_source=twitter&id=123"
        assert normalize_url(url) == "https://example.com/article?id=123"

    def test_sorts_query_params_for_stable_comparison(self):
        url_a = "https://example.com/?b=2&a=1"
        url_b = "https://example.com/?a=1&b=2"
        assert normalize_url(url_a) == normalize_url(url_b)

    def test_empty_query_string(self):
        assert normalize_url("https://example.com/page?") == "https://example.com/page"

    # ── Fragments ─────────────────────────────────────────────────────────────

    def test_strips_all_fragments(self):
        assert "#" not in normalize_url("https://example.com/article#section-2")

    def test_strips_navigation_fragment(self):
        assert "#" not in normalize_url("https://example.com/article#top")

    def test_strips_content_id_fragment(self):
        assert "#" not in normalize_url("https://example.com/article#comment-42")

    def test_strips_empty_fragment(self):
        result = normalize_url("https://example.com/article#")
        assert result == "https://example.com/article"

    # ── Combined transformations ───────────────────────────────────────────────

    def test_full_normalization(self):
        messy = "http://www.Reuters.COM/business/?utm_source=rss&fbclid=abc#top"
        assert normalize_url(messy) == "https://reuters.com/business"

    def test_idempotent(self):
        url = "https://example.com/article?id=123"
        assert normalize_url(normalize_url(url)) == normalize_url(url)

    def test_whitespace_stripped_from_url(self):
        assert normalize_url("  https://example.com/page  ") == "https://example.com/page"


class TestUrlsAreEquivalent:
    def test_same_url(self):
        assert urls_are_equivalent("https://example.com/a", "https://example.com/a")

    def test_tracking_params_equivalent(self):
        a = "https://example.com/a?utm_source=x"
        b = "https://example.com/a"
        assert urls_are_equivalent(a, b)

    def test_http_and_https_equivalent(self):
        assert urls_are_equivalent("http://example.com/a", "https://example.com/a")

    def test_www_and_no_www_equivalent(self):
        assert urls_are_equivalent("https://www.example.com/a", "https://example.com/a")

    def test_trailing_slash_equivalent(self):
        assert urls_are_equivalent("https://example.com/a/", "https://example.com/a")

    def test_different_paths_not_equivalent(self):
        assert not urls_are_equivalent("https://example.com/a", "https://example.com/b")

    def test_different_query_params_not_equivalent(self):
        assert not urls_are_equivalent(
            "https://example.com/a?id=1",
            "https://example.com/a?id=2",
        )

    def test_fragment_difference_is_equivalent(self):
        assert urls_are_equivalent(
            "https://example.com/a#section1",
            "https://example.com/a#section2",
        )
