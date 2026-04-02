"""Tests for the token counting utilities in src.utils.tokens."""

from __future__ import annotations

import pytest

from src.utils.tokens import estimate_tokens, fits_in_budget, truncate_to_budget


class TestEstimateTokens:
    def test_empty_string_returns_one(self):
        # Even an empty string should return minimum of 1
        assert estimate_tokens("") == 1

    def test_four_chars_is_one_token(self):
        assert estimate_tokens("abcd") == 1

    def test_eight_chars_is_two_tokens(self):
        assert estimate_tokens("abcdefgh") == 2

    def test_single_char_returns_one(self):
        assert estimate_tokens("x") == 1

    def test_large_text(self):
        text = "a" * 400
        assert estimate_tokens(text) == 100

    def test_unicode_counted_by_char_length(self):
        # Each emoji is typically multiple bytes but one char in Python
        text = "😀" * 4
        assert estimate_tokens(text) == 1

    def test_returns_int(self):
        assert isinstance(estimate_tokens("hello world"), int)


class TestFitsInBudget:
    def test_exact_fit(self):
        text = "a" * 40  # 10 tokens
        assert fits_in_budget(text, 10) is True

    def test_under_budget(self):
        text = "a" * 20  # 5 tokens
        assert fits_in_budget(text, 10) is True

    def test_over_budget(self):
        text = "a" * 44  # 11 tokens
        assert fits_in_budget(text, 10) is False

    def test_empty_string_fits_any_positive_budget(self):
        assert fits_in_budget("", 1) is True
        assert fits_in_budget("", 100) is True

    def test_returns_bool(self):
        result = fits_in_budget("hello", 10)
        assert isinstance(result, bool)


class TestTruncateTobudget:
    def test_short_text_unchanged(self):
        text = "hello"
        result = truncate_to_budget(text, 100)
        assert result == text

    def test_exact_length_unchanged(self):
        text = "a" * 40  # exactly 10 tokens (40 chars)
        result = truncate_to_budget(text, 10)
        assert result == text

    def test_truncation_adds_ellipsis(self):
        text = "a" * 100
        result = truncate_to_budget(text, 5)
        assert result.endswith("...")

    def test_truncated_result_fits_in_budget(self):
        text = "a" * 400  # 100 tokens
        result = truncate_to_budget(text, 10)
        assert fits_in_budget(result, 10)

    def test_truncated_length_is_correct(self):
        text = "a" * 400
        max_tokens = 10
        result = truncate_to_budget(text, max_tokens)
        assert len(result) == max_tokens * 4  # 40 chars (37 + 3 for "...")

    def test_empty_string_unchanged(self):
        result = truncate_to_budget("", 10)
        assert result == ""

    def test_returns_string(self):
        result = truncate_to_budget("hello world", 5)
        assert isinstance(result, str)

    def test_one_token_budget(self):
        text = "a" * 200
        result = truncate_to_budget(text, 1)
        assert result.endswith("...")
        assert len(result) == 4  # 1 * 4 = 4 chars (1 content char + "...")
