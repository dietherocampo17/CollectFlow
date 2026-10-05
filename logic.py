ROLE_PERMISSIONS = {
    "admin": {
        "dashboard",
        "accounts",
        "promises",
        "payments",
        "activities",
        "tasks",
        "reports",
        "queue",
        "clients",
        "users",
        "audit",
        "strategy",
    },
    "supervisor": {
        "dashboard",
        "accounts",
        "promises",
        "payments",
        "activities",
        "tasks",
        "reports",
        "clients",
        "queue",
        "strategy",
    },
    "collector": {
        "dashboard",
        "accounts",
        "promises",
        "payments",
        "activities",
        "tasks",
        "reports",
        "queue",
    },
    "client": {"dashboard", "reports", "portfolio"},
    "management": {"dashboard", "reports", "strategy", "analytics"},
}


def get_priority(days_past_due):
    if days_past_due >= 60:
        return "High"
    if days_past_due >= 30:
        return "Medium"
    return "Low"


def calculate_recovery_rate(accounts):
    total = sum(account["balance"] for account in accounts)
    if total == 0:
        return 0
    overdue = sum(
        account["balance"] for account in accounts if account["days_past_due"] > 30
    )
    return round((overdue / total) * 100)


def calculate_workload(accounts):
    workload = {}
    for account in accounts:
        collector = account["collector"]
        workload[collector] = workload.get(collector, 0) + 1
    return workload


def role_can_access(role, module):
    normalized_role = (role or "").strip().lower()
    normalized_module = (module or "").strip().lower()
    if not normalized_role or not normalized_module:
        return False

    permissions = ROLE_PERMISSIONS.get(normalized_role, set())
    return normalized_module in permissions
