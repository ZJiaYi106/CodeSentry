"""Tests for utils module."""

from utils import calculate_average, format_name


def test_calculate_average():
    assert calculate_average([1, 2, 3]) == 2.0
    assert calculate_average([]) == 0


def test_format_name():
    assert format_name("Alice", "Smith") == "Alice Smith"
