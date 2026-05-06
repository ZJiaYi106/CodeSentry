"""Tests for data_processor module."""

from data_processor import process_user_data


def test_empty_list():
    result = process_user_data([])
    assert result["total_users"] == 0


def test_single_user():
    users = [{"name": "Alice", "age": 30, "active": True, "role": "admin"}]
    result = process_user_data(users)
    assert result["total_users"] == 1
    assert result["average_age"] == 30.0
    assert result["active_users"] == 1
    assert result["admin_users"] == 1


def test_multiple_users():
    users = [
        {"name": "Bob", "age": 25, "active": False, "role": "user"},
        {"name": "Carol", "age": 35, "active": True, "role": "admin"},
        {"name": "Dave", "age": 40, "active": True, "role": "user"},
    ]
    result = process_user_data(users)
    assert result["total_users"] == 3
    assert result["average_age"] == pytest.approx(33.3, 0.1)
    assert result["active_users"] == 2
    assert result["admin_users"] == 1


def test_invalid_user_skipped():
    users = [
        {"name": "Valid", "age": 20},
        {"name": "NoAge"},  # missing age
        {"age": 30},  # missing name
        {"name": "Negative", "age": -5},  # negative age
    ]
    result = process_user_data(users)
    assert result["total_users"] == 1


import pytest
