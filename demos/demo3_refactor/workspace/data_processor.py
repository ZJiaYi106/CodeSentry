"""Data processor — a long function that should be refactored."""


def process_user_data(users):
    """Process a list of user dictionaries and return statistics."""
    total_age = 0
    active_count = 0
    admin_count = 0
    names = []

    for user in users:
        # Validate user data
        if "name" not in user or "age" not in user:
            continue
        if not isinstance(user["age"], (int, float)) or user["age"] < 0:
            continue

        # Collect names
        names.append(user["name"])

        # Calculate age statistics
        total_age += user["age"]

        # Count active users
        if user.get("active", False):
            active_count += 1

        # Count admins
        if user.get("role") == "admin":
            admin_count += 1

    # Calculate averages
    user_count = len(names)
    avg_age = total_age / user_count if user_count > 0 else 0

    # Build result
    return {
        "total_users": user_count,
        "average_age": round(avg_age, 1),
        "active_users": active_count,
        "admin_users": admin_count,
        "names": sorted(names),
        "active_ratio": round(active_count / user_count, 2) if user_count > 0 else 0,
    }
