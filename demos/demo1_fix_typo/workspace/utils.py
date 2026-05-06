"""Utility functions for the demo project."""


def calculate_average(numbers):
    """Return the average of a list of numbers."""
    if not numbers:
        return 0
    total = sum(numbers)
    # BUG: typo — variable name mismatch
    return total / len(numers)


def format_name(first, last):
    """Format a full name from first and last name."""
    return f"{fist} {last}"
