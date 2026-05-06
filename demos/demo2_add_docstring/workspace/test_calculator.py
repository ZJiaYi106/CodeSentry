"""Tests for calculator module."""

import pytest
from calculator import add, subtract, multiply, divide, power


def test_add():
    assert add(2, 3) == 5
    assert add(-1, 1) == 0


def test_subtract():
    assert subtract(5, 3) == 2


def test_multiply():
    assert multiply(4, 3) == 12


def test_divide():
    assert divide(10, 2) == 5
    with pytest.raises(ValueError):
        divide(1, 0)


def test_power():
    assert power(2, 3) == 8
    assert power(5, 0) == 1
