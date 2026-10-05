import hashlib
import hmac
import json
import os
import secrets
import time
from datetime import date, datetime, timedelta
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

try:
    import mysql.connector
    from mysql.connector import IntegrityError
except ImportError:
    mysql = None

    class IntegrityError(Exception):
        pass

from logic import ROLE_PERMISSIONS, calculate_recovery_rate, role_can_access

PORT = int(os.getenv("PORT", "8001"))
SESSION_COOKIE = "collectflow_session"
SESSION_HOURS = 12
PASSWORD_ITERATIONS = 310000
ROLE_LABELS = {
    "admin": "System Administrator",
    "supervisor": "Collection Supervisor",
    "collector": "Collector",
    "client": "Client",
    "management": "Management",
}


class DatabaseConnection:
    def __init__(self, connection):
        self.connection = connection

    def execute(self, query, params=()):
        cursor = self.connection.cursor(dictionary=True)
        cursor.execute(query.replace("?", "%s"), params)
        return cursor

    def executemany(self, query, params):
        cursor = self.connection.cursor()
        cursor.executemany(query.replace("?", "%s"), params)
        return cursor

    def commit(self):
        self.connection.commit()

    def close(self):
        self.connection.close()


def get_connection():
    if mysql is None:
        raise RuntimeError("MySQL support is missing; install dependencies from requirements.txt")
    return DatabaseConnection(
        mysql.connector.connect(
            host=os.getenv("MYSQL_HOST", "127.0.0.1"),
            port=int(os.getenv("MYSQL_PORT", "3306")),
            user=os.getenv("MYSQL_USER", "collectflow"),
            password=os.getenv("MYSQL_PASSWORD", "collectflow-dev-password"),
            database=os.getenv("MYSQL_DATABASE", "collectflow"),
            connection_timeout=5,
        )
    )


def hash_password(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt), PASSWORD_ITERATIONS
    ).hex()
    return f"pbkdf2_sha256${salt}${digest}"


def verify_password(password, encoded):
    try:
        algorithm, salt, expected = encoded.split("$", 2)
        if algorithm != "pbkdf2_sha256":
            return False
        actual = hash_password(password, salt).split("$", 2)[2]
        return hmac.compare_digest(actual, expected)
    except (AttributeError, ValueError):
        return False


def create_audit_entry(conn, actor, action, details):
    conn.execute(
        "INSERT INTO audit_logs (actor_user_id, actor_username, action, details) VALUES (?, ?, ?, ?)",
        (
            actor.get("id") if actor else None,
            actor.get("username", "system") if actor else "system",
            action,
            details,
        ),
    )


def init_db():
    conn = get_connection()
    try:
        schemas = [
            """CREATE TABLE IF NOT EXISTS clients (
                id BIGINT PRIMARY KEY AUTO_INCREMENT,
                name VARCHAR(180) NOT NULL UNIQUE,
                industry VARCHAR(120) NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )""",
            """CREATE TABLE IF NOT EXISTS accounts (
                id BIGINT PRIMARY KEY AUTO_INCREMENT,
                account_number VARCHAR(64) NOT NULL UNIQUE,
                client VARCHAR(180) NOT NULL,
                balance DECIMAL(14, 2) NOT NULL,
                days_past_due INTEGER NOT NULL,
                collector VARCHAR(180) NOT NULL,
                status VARCHAR(40) NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_accounts_client (client),
                INDEX idx_accounts_collector (collector)
            )""",
            """CREATE TABLE IF NOT EXISTS account_number_sequence (
                id BIGINT PRIMARY KEY AUTO_INCREMENT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )""",
            """CREATE TABLE IF NOT EXISTS promises (
                id BIGINT PRIMARY KEY AUTO_INCREMENT,
                account_number VARCHAR(64) NOT NULL,
                amount DECIMAL(14, 2) NOT NULL,
                due_date DATE NOT NULL,
                payment_method VARCHAR(80) NOT NULL DEFAULT 'Unspecified',
                status VARCHAR(40) NOT NULL DEFAULT 'Pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_promises_due (due_date),
                CONSTRAINT fk_promises_account FOREIGN KEY (account_number)
                    REFERENCES accounts(account_number) ON DELETE CASCADE
            )""",
            """CREATE TABLE IF NOT EXISTS follow_up_tasks (
                id BIGINT PRIMARY KEY AUTO_INCREMENT,
                account_number VARCHAR(64) NOT NULL,
                promise_id BIGINT NULL,
                assigned_to VARCHAR(180) NOT NULL,
                title VARCHAR(180) NOT NULL,
                due_date DATE NOT NULL,
                status VARCHAR(40) NOT NULL DEFAULT 'Open',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE KEY uq_follow_up_promise (promise_id),
                INDEX idx_tasks_owner_status (assigned_to, status),
                CONSTRAINT fk_tasks_account FOREIGN KEY (account_number)
                    REFERENCES accounts(account_number) ON DELETE CASCADE,
                CONSTRAINT fk_tasks_promise FOREIGN KEY (promise_id)
                    REFERENCES promises(id) ON DELETE SET NULL
            )""",
            """CREATE TABLE IF NOT EXISTS payments (
                id BIGINT PRIMARY KEY AUTO_INCREMENT,
                account_number VARCHAR(64) NOT NULL,
                promise_id BIGINT NULL,
                amount DECIMAL(14, 2) NOT NULL,
                payment_method VARCHAR(80) NOT NULL,
                reference VARCHAR(120) NULL,
                paid_at DATETIME NOT NULL,
                recorded_by BIGINT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_payments_paid (paid_at),
                CONSTRAINT fk_payments_account FOREIGN KEY (account_number)
                    REFERENCES accounts(account_number) ON DELETE CASCADE,
                CONSTRAINT fk_payments_promise FOREIGN KEY (promise_id)
                    REFERENCES promises(id) ON DELETE SET NULL
            )""",
            """CREATE TABLE IF NOT EXISTS activities (
                id BIGINT PRIMARY KEY AUTO_INCREMENT,
                account_number VARCHAR(64) NULL,
                title VARCHAR(180) NOT NULL,
                detail TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_activity_account (account_number),
                CONSTRAINT fk_activities_account FOREIGN KEY (account_number)
                    REFERENCES accounts(account_number) ON DELETE SET NULL
            )""",
            """CREATE TABLE IF NOT EXISTS users (
                id BIGINT PRIMARY KEY AUTO_INCREMENT,
                username VARCHAR(100) NOT NULL UNIQUE,
                password VARCHAR(255) NOT NULL,
                full_name VARCHAR(180) NOT NULL,
                role VARCHAR(32) NOT NULL,
                client_name VARCHAR(180) NULL,
                is_active BOOLEAN NOT NULL DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_users_role (role)
            )""",
            """CREATE TABLE IF NOT EXISTS sessions (
                id BIGINT PRIMARY KEY AUTO_INCREMENT,
                token_hash CHAR(64) NOT NULL UNIQUE,
                user_id BIGINT NOT NULL,
                expires_at DATETIME NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_sessions_expiry (expires_at),
                CONSTRAINT fk_sessions_user FOREIGN KEY (user_id)
                    REFERENCES users(id) ON DELETE CASCADE
            )""",
            """CREATE TABLE IF NOT EXISTS audit_logs (
                id BIGINT PRIMARY KEY AUTO_INCREMENT,
                actor_user_id BIGINT NULL,
                actor_username VARCHAR(100) NOT NULL,
                action VARCHAR(120) NOT NULL,
                details TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_audit_created (created_at),
                INDEX idx_audit_actor (actor_user_id),
                CONSTRAINT fk_audit_user FOREIGN KEY (actor_user_id)
                    REFERENCES users(id) ON DELETE SET NULL
            )""",
        ]
        for statement in schemas:
            conn.execute(statement)
        promise_columns = conn.execute(
            "SHOW COLUMNS FROM promises LIKE 'payment_method'"
        ).fetchone()
        if promise_columns is None:
            conn.execute(
                "ALTER TABLE promises ADD COLUMN payment_method VARCHAR(80) NOT NULL DEFAULT 'Unspecified'"
            )
        conn.commit()
        if os.getenv("COLLECTFLOW_SEED_DEMO_DATA", "false").lower() == "true":
            seed_data(conn)
        seed_admin(conn)
        conn.commit()
    finally:
        conn.close()


def seed_data(conn):
    clients = [
        ("ABC Finance", "Banking"),
        ("City Lending", "Finance"),
        ("Prime Credit", "Retail"),
        ("Metro Capital", "Telecom"),
    ]
    for name, industry in clients:
        conn.execute(
            "INSERT IGNORE INTO clients (name, industry) VALUES (?, ?)",
            (name, industry),
        )

    accounts = [
        ("ACC-2026-001245", "ABC Finance", 85000, 74, "Juan Dela Cruz", "Active"),
        ("ACC-2026-001867", "City Lending", 62000, 46, "Maria Santos", "Follow-up"),
        ("ACC-2026-002341", "Prime Credit", 41000, 18, "Liam Reyes", "Review"),
        ("ACC-2026-003110", "Metro Capital", 96000, 91, "Nina Cruz", "Escalated"),
    ]
    for account in accounts:
        conn.execute(
            "INSERT IGNORE INTO accounts (account_number, client, balance, days_past_due, collector, status) VALUES (?, ?, ?, ?, ?, ?)",
            account,
        )

    promises = [
        ("ACC-2026-001245", 18000, "2026-10-10", "Pending"),
        ("ACC-2026-002341", 9500, "2026-10-12", "Pending"),
    ]
    for promise in promises:
        exists = conn.execute(
            "SELECT id FROM promises WHERE account_number = ? AND due_date = ?",
            promise[:1] + promise[2:3],
        ).fetchone()
        if exists is None:
            conn.execute(
                "INSERT INTO promises (account_number, amount, due_date, status) VALUES (?, ?, ?, ?)",
                promise,
            )

    activity_count = conn.execute(
        "SELECT COUNT(*) AS total FROM activities"
    ).fetchone()["total"]
    if activity_count == 0:
        conn.executemany(
            "INSERT INTO activities (account_number, title, detail) VALUES (?, ?, ?)",
            [
                ("ACC-2026-001245", "New assignment approved", "ABC Finance queue updated for field follow-up."),
                ("ACC-2026-002341", "Promise to pay recorded", "Due date updated for ACC-2026-002341."),
                ("ACC-2026-003110", "Escalation triggered", "Metro Capital account reached high-priority threshold."),
            ],
        )


def seed_admin(conn):
    username = os.getenv("COLLECTFLOW_ADMIN_USERNAME", "admin")
    password = os.getenv("COLLECTFLOW_ADMIN_PASSWORD")
    if not password or len(password) < 10:
        raise RuntimeError("Set COLLECTFLOW_ADMIN_PASSWORD to at least 10 characters")
    existing = conn.execute("SELECT id FROM users LIMIT 1").fetchone()
    if existing is None:
        conn.execute(
            "INSERT INTO users (username, password, full_name, role) VALUES (?, ?, ?, 'admin')",
            (username, hash_password(password), os.getenv("COLLECTFLOW_ADMIN_NAME", "System Administrator")),
        )


def public_user(row):
    return {
        "id": row["id"],
        "username": row["username"],
        "fullName": row["full_name"],
        "role": row["role"],
        "clientName": row.get("client_name"),
        "permissions": sorted(ROLE_PERMISSIONS.get(row["role"], set())),
    }


def login_user(payload):
    username = (payload.get("username") or "").strip()
    password = payload.get("password") or ""
    if not username or not password:
        raise ValueError("Username and password are required")

    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT id, username, password, full_name, role, client_name, is_active FROM users WHERE username = ?",
            (username,),
        ).fetchone()
        if row is None or not row["is_active"] or not verify_password(password, row["password"]):
            raise ValueError("Invalid username or password")

        user = public_user(row)
        token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        conn.execute(
            "INSERT INTO sessions (token_hash, user_id, expires_at) VALUES (?, ?, ?)",
            (token_hash, user["id"], datetime.utcnow() + timedelta(hours=SESSION_HOURS)),
        )
        conn.execute("DELETE FROM sessions WHERE expires_at < ?", (datetime.utcnow(),))
        create_audit_entry(conn, user, "auth.login", "Successful login")
        conn.commit()
        return user, token
    finally:
        conn.close()


def get_session_user(token):
    if not token:
        return None
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT u.id, u.username, u.full_name, u.role, u.client_name FROM sessions s "
            "JOIN users u ON u.id = s.user_id WHERE s.token_hash = ? AND s.expires_at > ? AND u.is_active = TRUE",
            (token_hash, datetime.utcnow()),
        ).fetchone()
        return public_user(row) if row else None
    finally:
        conn.close()


def revoke_session(token, actor):
    if not token:
        return
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    conn = get_connection()
    try:
        conn.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash,))
        if actor:
            create_audit_entry(conn, actor, "auth.logout", "User logged out")
        conn.commit()
    finally:
        conn.close()


def account_scope(user, alias=""):
    prefix = f"{alias}." if alias else ""
    if user["role"] == "collector":
        return f" WHERE {prefix}collector = ?", (user["fullName"],)
    if user["role"] == "client":
        return f" WHERE {prefix}client = ?", (user.get("clientName") or "",)
    return "", ()


def get_accounts(user):
    conn = get_connection()
    try:
        clause, params = account_scope(user)
        rows = conn.execute(
            "SELECT id, account_number AS accountNumber, client, balance, days_past_due AS daysPastDue, "
            f"collector, status, created_at AS createdAt FROM accounts{clause} ORDER BY days_past_due DESC",
            params,
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def get_promises(user):
    refresh_promise_lifecycle()
    conn = get_connection()
    try:
        clause, params = account_scope(user, "a")
        rows = conn.execute(
            "SELECT p.id, p.account_number AS accountNumber, p.amount, p.due_date AS dueDate, "
            "p.payment_method AS paymentMethod, p.status "
            "FROM promises p JOIN accounts a ON a.account_number = p.account_number "
            f"{clause} ORDER BY p.due_date ASC",
            params,
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def refresh_promise_lifecycle():
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE promises SET status = 'Broken' "
            "WHERE status IN ('Pending', 'Upcoming', 'Due') AND due_date < CURRENT_DATE"
        )
        conn.execute(
            "UPDATE promises SET status = 'Due' "
            "WHERE status IN ('Pending', 'Upcoming') AND due_date = CURRENT_DATE"
        )
        conn.execute(
            "UPDATE promises SET status = 'Upcoming' "
            "WHERE status = 'Pending' AND due_date > CURRENT_DATE"
        )
        conn.execute(
            "INSERT IGNORE INTO follow_up_tasks (account_number, promise_id, assigned_to, title, due_date) "
            "SELECT p.account_number, p.id, a.collector, 'Follow up on broken promise', CURRENT_DATE "
            "FROM promises p JOIN accounts a ON a.account_number = p.account_number "
            "WHERE p.status = 'Broken'"
        )
        conn.commit()
    finally:
        conn.close()


def get_tasks(user):
    conn = get_connection()
    try:
        if user["role"] == "collector":
            rows = conn.execute(
                "SELECT t.id, t.account_number AS accountNumber, t.promise_id AS promiseId, "
                "t.assigned_to AS assignedTo, t.title, t.due_date AS dueDate, t.status "
                "FROM follow_up_tasks t WHERE t.assigned_to = ? ORDER BY t.due_date, t.id DESC",
                (user["fullName"],),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT t.id, t.account_number AS accountNumber, t.promise_id AS promiseId, "
                "t.assigned_to AS assignedTo, t.title, t.due_date AS dueDate, t.status "
                "FROM follow_up_tasks t ORDER BY t.due_date, t.id DESC"
            ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def add_task(payload, actor):
    account_number = (payload.get("accountNumber") or "").strip()
    title = (payload.get("title") or "Follow-up task").strip()
    due_date = (payload.get("dueDate") or date.today().isoformat()).strip()
    assigned_to = (payload.get("assignedTo") or actor["fullName"]).strip()
    if not account_number or not title:
        raise ValueError("Select an account and provide a task title")
    if actor["role"] == "collector":
        assigned_to = actor["fullName"]
    try:
        date.fromisoformat(due_date)
    except ValueError as exc:
        raise ValueError("Task due date must use YYYY-MM-DD format") from exc
    conn = get_connection()
    try:
        account = conn.execute(
            "SELECT collector FROM accounts WHERE account_number = ?", (account_number,)
        ).fetchone()
        if account is None:
            raise ValueError("Account not found")
        if actor["role"] == "collector" and account["collector"] != actor["fullName"]:
            raise ValueError("Collectors can only create tasks for assigned accounts")
        if actor["role"] != "collector" and conn.execute(
            "SELECT id FROM users WHERE role = 'collector' AND full_name = ? AND is_active = TRUE",
            (assigned_to,),
        ).fetchone() is None:
            raise ValueError("Select an active collector for this task")
        cursor = conn.execute(
            "INSERT INTO follow_up_tasks (account_number, assigned_to, title, due_date) VALUES (?, ?, ?, ?)",
            (account_number, assigned_to, title, due_date),
        )
        create_audit_entry(conn, actor, "task.created", f"{account_number}: {title}")
        conn.commit()
        return {"id": cursor.lastrowid, "accountNumber": account_number, "assignedTo": assigned_to, "title": title, "dueDate": due_date, "status": "Open"}
    finally:
        conn.close()


def get_payments(user):
    conn = get_connection()
    try:
        clause, params = account_scope(user, "a")
        rows = conn.execute(
            "SELECT p.id, p.account_number AS accountNumber, p.promise_id AS promiseId, p.amount, "
            "p.payment_method AS paymentMethod, p.reference, p.paid_at AS paidAt "
            "FROM payments p JOIN accounts a ON a.account_number = p.account_number "
            f"{clause} ORDER BY p.paid_at DESC LIMIT 300",
            params,
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def add_activity(payload, actor):
    account_number = (payload.get("accountNumber") or "").strip()
    detail = (payload.get("detail") or "").strip()
    title = (payload.get("title") or "Collection interaction").strip()
    if not account_number or not detail:
        raise ValueError("Select an account and enter the interaction details")
    if len(detail) > 5000 or len(title) > 180:
        raise ValueError("Activity details exceed the allowed length")
    conn = get_connection()
    try:
        account = conn.execute(
            "SELECT collector FROM accounts WHERE account_number = ?", (account_number,)
        ).fetchone()
        if account is None:
            raise ValueError("Account not found")
        if actor["role"] == "collector" and account["collector"] != actor["fullName"]:
            raise ValueError("Collectors can only record activity on their assigned accounts")
        conn.execute(
            "INSERT INTO activities (account_number, title, detail) VALUES (?, ?, ?)",
            (account_number, title, detail),
        )
        create_audit_entry(conn, actor, "activity.created", f"{account_number}: {title}")
        conn.commit()
        return {"accountNumber": account_number, "title": title, "detail": detail}
    finally:
        conn.close()


def update_account(account_id, payload, actor):
    conn = get_connection()
    try:
        account = conn.execute(
            "SELECT account_number, collector FROM accounts WHERE id = ?", (int(account_id),)
        ).fetchone()
        if account is None:
            raise ValueError("Account not found")
        if actor["role"] == "collector" and account["collector"] != actor["fullName"]:
            raise ValueError("Collectors can only update their assigned accounts")

        allowed = {"status"} if actor["role"] == "collector" else {
            "status", "collector", "balance", "daysPastDue", "client"
        }
        columns = {
            "status": "status",
            "collector": "collector",
            "balance": "balance",
            "daysPastDue": "days_past_due",
            "client": "client",
        }
        updates = [(columns[key], payload[key]) for key in columns if key in allowed and key in payload]
        if not updates:
            raise ValueError("No permitted account fields were provided")
        if any(column == "status" for column, _ in updates):
            status = next(value for column, value in updates if column == "status")
            if status not in {"Active", "Follow-up", "Escalated", "Paid", "Closed"}:
                raise ValueError("Invalid account status")
        if any(column == "client" for column, _ in updates):
            client_name = next(value for column, value in updates if column == "client")
            if conn.execute("SELECT id FROM clients WHERE name = ?", (client_name,)).fetchone() is None:
                raise ValueError("Selected client portfolio does not exist")
        if any(column == "collector" for column, _ in updates):
            collector_name = next(value for column, value in updates if column == "collector")
            if conn.execute(
                "SELECT id FROM users WHERE role = 'collector' AND full_name = ? AND is_active = TRUE",
                (collector_name,),
            ).fetchone() is None:
                raise ValueError("Select an active collector for this account")
        for column, value in updates:
            if column in ("balance", "days_past_due") and float(value) < 0:
                raise ValueError("Balance and days past due cannot be negative")
        assignments = ", ".join(f"{column} = ?" for column, _ in updates)
        values = [float(value) if column == "balance" else int(value) if column == "days_past_due" else value for column, value in updates]
        conn.execute(
            f"UPDATE accounts SET {assignments} WHERE id = ?", (*values, int(account_id))
        )
        create_audit_entry(conn, actor, "account.updated", account["account_number"])
        conn.commit()
        return account["account_number"]
    finally:
        conn.close()


def update_promise(promise_id, payload, actor):
    status = (payload.get("status") or "").strip().title()
    valid = {"Upcoming", "Due", "Fulfilled", "Broken"}
    if status not in valid:
        raise ValueError("Status must be Upcoming, Due, Fulfilled, or Broken")
    conn = get_connection()
    try:
        clause, scope_params = account_scope(actor, "a")
        promise = conn.execute(
            "SELECT p.id, p.account_number, p.status FROM promises p "
            "JOIN accounts a ON a.account_number = p.account_number "
            f"WHERE p.id = ?{(' AND ' + clause[7:]) if clause else ''}",
            (int(promise_id), *scope_params),
        ).fetchone()
        if promise is None:
            raise ValueError("Promise not found or not assigned to you")
        if promise["status"] == "Fulfilled" and status != "Fulfilled":
            raise ValueError("A fulfilled promise cannot be reopened")
        conn.execute("UPDATE promises SET status = ? WHERE id = ?", (status, int(promise_id)))
        if status == "Broken":
            conn.execute(
                "INSERT IGNORE INTO follow_up_tasks (account_number, promise_id, assigned_to, title, due_date) "
                "SELECT a.account_number, p.id, a.collector, 'Follow up on broken promise', CURRENT_DATE "
                "FROM promises p JOIN accounts a ON a.account_number = p.account_number WHERE p.id = ?",
                (int(promise_id),),
            )
        create_audit_entry(conn, actor, "promise.status_updated", f"{promise['account_number']}: {status}")
        conn.commit()
        return {"id": int(promise_id), "status": status}
    finally:
        conn.close()


def add_payment(payload, actor):
    account_number = (payload.get("accountNumber") or "").strip()
    amount = float(payload.get("amount") or 0)
    method = (payload.get("paymentMethod") or "").strip()
    promise_id = payload.get("promiseId") or None
    if not account_number or amount <= 0 or not method:
        raise ValueError("Account, positive payment amount, and payment method are required")
    conn = get_connection()
    try:
        account = conn.execute(
            "SELECT id, balance, collector FROM accounts WHERE account_number = ?", (account_number,)
        ).fetchone()
        if account is None:
            raise ValueError("Account not found")
        if actor["role"] == "collector" and account["collector"] != actor["fullName"]:
            raise ValueError("Collectors can only record payments on their assigned accounts")
        if promise_id:
            promise = conn.execute(
                "SELECT id FROM promises WHERE id = ? AND account_number = ?",
                (int(promise_id), account_number),
            ).fetchone()
            if promise is None:
                raise ValueError("Selected promise does not belong to this account")
        paid_at = payload.get("paidAt") or datetime.utcnow()
        cursor = conn.execute(
            "INSERT INTO payments (account_number, promise_id, amount, payment_method, reference, paid_at, recorded_by) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (account_number, promise_id, amount, method, (payload.get("reference") or "").strip() or None, paid_at, actor["id"]),
        )
        remaining = max(float(account["balance"]) - amount, 0)
        conn.execute(
            "UPDATE accounts SET balance = ?, status = IF(? = 0, 'Paid', status) WHERE id = ?",
            (remaining, remaining, account["id"]),
        )
        if promise_id:
            paid = conn.execute(
                "SELECT SUM(amount) AS total FROM payments WHERE promise_id = ?", (int(promise_id),)
            ).fetchone()["total"]
            promised = conn.execute(
                "SELECT amount FROM promises WHERE id = ?", (int(promise_id),)
            ).fetchone()["amount"]
            if float(paid or 0) >= float(promised):
                conn.execute(
                    "UPDATE promises SET status = 'Fulfilled' WHERE id = ?", (int(promise_id),)
                )
        conn.execute(
            "INSERT INTO activities (account_number, title, detail) VALUES (?, ?, ?)",
            (account_number, "Payment recorded", f"{amount:,.2f} received by {method}."),
        )
        create_audit_entry(conn, actor, "payment.recorded", f"{account_number}: {amount:,.2f}")
        conn.commit()
        return {"id": cursor.lastrowid, "accountNumber": account_number, "amount": amount}
    finally:
        conn.close()


def update_task(task_id, payload, actor):
    status = (payload.get("status") or "").strip().title()
    if status not in {"Open", "In Progress", "Completed"}:
        raise ValueError("Task status must be Open, In Progress, or Completed")
    conn = get_connection()
    try:
        task = conn.execute(
            "SELECT id, assigned_to, account_number FROM follow_up_tasks WHERE id = ?",
            (int(task_id),),
        ).fetchone()
        if task is None:
            raise ValueError("Task not found")
        if actor["role"] == "collector" and task["assigned_to"] != actor["fullName"]:
            raise ValueError("Collectors can only update their assigned follow-up tasks")
        conn.execute("UPDATE follow_up_tasks SET status = ? WHERE id = ?", (status, int(task_id)))
        create_audit_entry(conn, actor, "task.status_updated", f"Task {task_id}: {status}")
        conn.commit()
        return {"id": int(task_id), "status": status}
    finally:
        conn.close()


def get_activities(user):
    conn = get_connection()
    try:
        if user["role"] in ("collector", "client"):
            column = "collector" if user["role"] == "collector" else "client"
            owner = user["fullName"] if column == "collector" else user.get("clientName") or ""
            rows = conn.execute(
                "SELECT x.id, x.account_number AS accountNumber, x.title, x.detail, x.created_at AS createdAt FROM activities x "
                "JOIN accounts a ON a.account_number = x.account_number "
                f"WHERE a.{column} = ? ORDER BY x.created_at DESC LIMIT 8",
                (owner,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, account_number AS accountNumber, title, detail, created_at AS createdAt "
                "FROM activities ORDER BY created_at DESC LIMIT 300"
            ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def get_clients(user):
    conn = get_connection()
    try:
        where = " WHERE c.name = ?" if user["role"] == "client" else ""
        params = (user.get("clientName") or "",) if where else ()
        rows = conn.execute(
            "SELECT c.id, c.name, c.industry, COUNT(a.id) AS totalAccounts FROM clients c "
            "LEFT JOIN accounts a ON a.client = c.name"
            f"{where} GROUP BY c.id, c.name, c.industry ORDER BY c.name ASC",
            params,
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def get_metrics(user):
    conn = get_connection()
    try:
        clause, params = account_scope(user)
        rows = conn.execute(
            f"SELECT balance, days_past_due FROM accounts{clause}", params
        ).fetchall()
        accounts = [dict(row) for row in rows]
        total_balance = sum(float(row["balance"]) for row in accounts)
        overdue = sum(1 for row in accounts if row["days_past_due"] > 30)
        payment_clause, payment_params = account_scope(user, "a")
        payment_where = payment_clause + (" AND " if payment_clause else " WHERE ")
        collected = conn.execute(
            "SELECT COALESCE(SUM(p.amount), 0) AS total FROM payments p "
            "JOIN accounts a ON a.account_number = p.account_number "
            f"{payment_where}p.paid_at >= DATE_FORMAT(CURRENT_DATE, '%Y-%m-01')",
            payment_params,
        ).fetchone()["total"]
        promise_clause, promise_params = account_scope(user, "a")
        promise_where = promise_clause + (" AND " if promise_clause else " WHERE ")
        promise_counts = conn.execute(
            "SELECT SUM(p.status IN ('Pending', 'Upcoming', 'Due')) AS activePromises, "
            "SUM(p.status = 'Broken') AS brokenPromises FROM promises p "
            "JOIN accounts a ON a.account_number = p.account_number "
            f"{promise_where}1 = 1",
            promise_params,
        ).fetchone()
        return {
            "totalAccounts": len(accounts),
            "totalBalance": total_balance,
            "overdueCount": overdue,
            "recoveryRate": calculate_recovery_rate(accounts),
            "amountCollectedMonth": float(collected),
            "activePromises": int(promise_counts["activePromises"] or 0),
            "brokenPromises": int(promise_counts["brokenPromises"] or 0),
            "queueStatus": "Needs action" if overdue else "Stable",
        }
    finally:
        conn.close()


def get_users():
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT id, username, full_name AS fullName, role, client_name AS clientName, "
            "is_active AS isActive, created_at AS createdAt FROM users ORDER BY role, username"
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def get_collectors():
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT id, username, full_name AS fullName FROM users "
            "WHERE role = 'collector' AND is_active = TRUE ORDER BY full_name"
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def add_user(payload, actor):
    username = (payload.get("username") or "").strip()
    password = payload.get("password") or ""
    full_name = (payload.get("fullName") or "").strip()
    role = (payload.get("role") or "").strip().lower()
    client_name = (payload.get("clientName") or "").strip() or None
    if not username or not full_name or len(password) < 10:
        raise ValueError("Username, full name, and a password of at least 10 characters are required")
    if role not in ROLE_LABELS:
        raise ValueError("Select a valid role")
    if role == "client" and not client_name:
        raise ValueError("Client users must be assigned a client portfolio")

    conn = get_connection()
    try:
        if client_name and conn.execute(
            "SELECT id FROM clients WHERE name = ?", (client_name,)
        ).fetchone() is None:
            raise ValueError("Selected client portfolio does not exist")
        cursor = conn.execute(
            "INSERT INTO users (username, password, full_name, role, client_name) VALUES (?, ?, ?, ?, ?)",
            (username, hash_password(password), full_name, role, client_name),
        )
        create_audit_entry(conn, actor, "user.created", f"Created {role} user {username}")
        conn.commit()
        return {
            "id": cursor.lastrowid,
            "username": username,
            "fullName": full_name,
            "role": role,
            "clientName": client_name,
            "isActive": True,
        }
    finally:
        conn.close()


def set_user_active(user_id, is_active, actor):
    if int(user_id) == int(actor["id"]):
        raise ValueError("You cannot deactivate your own account")
    conn = get_connection()
    try:
        cursor = conn.execute(
            "UPDATE users SET is_active = ? WHERE id = ?",
            (bool(is_active), int(user_id)),
        )
        if cursor.rowcount == 0:
            raise ValueError("User not found")
        create_audit_entry(
            conn,
            actor,
            "user.activated" if is_active else "user.deactivated",
            f"Set user id {user_id} active={bool(is_active)}",
        )
        conn.commit()
    finally:
        conn.close()


def change_password(payload, actor, current_token):
    current_password = payload.get("currentPassword") or ""
    new_password = payload.get("newPassword") or ""
    if len(new_password) < 10:
        raise ValueError("New password must be at least 10 characters")
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT password FROM users WHERE id = ?", (actor["id"],)
        ).fetchone()
        if row is None or not verify_password(current_password, row["password"]):
            raise ValueError("Current password is incorrect")
        conn.execute(
            "UPDATE users SET password = ? WHERE id = ?",
            (hash_password(new_password), actor["id"]),
        )
        current_hash = hashlib.sha256(current_token.encode("utf-8")).hexdigest()
        conn.execute(
            "DELETE FROM sessions WHERE user_id = ? AND token_hash <> ?",
            (actor["id"], current_hash),
        )
        create_audit_entry(conn, actor, "auth.password_changed", "Password changed; other sessions revoked")
        conn.commit()
    finally:
        conn.close()


def get_audit_logs():
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT id, actor_username AS actorUsername, action, details, created_at AS createdAt "
            "FROM audit_logs ORDER BY created_at DESC, id DESC LIMIT 300"
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def add_account(payload):
    required = ("client", "balance", "daysPastDue", "collector", "status")
    if any(field not in payload or payload[field] in (None, "") for field in required):
        raise ValueError("All account fields are required")
    if float(payload["balance"]) < 0 or int(payload["daysPastDue"]) < 0:
        raise ValueError("Balance and days past due cannot be negative")
    conn = get_connection()
    try:
        account_number = generate_account_number(conn)
        client = conn.execute(
            "SELECT id FROM clients WHERE name = ?", (payload["client"],)
        ).fetchone()
        if client is None:
            raise ValueError("Select an existing client portfolio")
        collector = conn.execute(
            "SELECT id FROM users WHERE role = 'collector' AND full_name = ? AND is_active = TRUE",
            (payload["collector"],),
        ).fetchone()
        if collector is None:
            raise ValueError("Select an active collector for this account")
        conn.execute(
            "INSERT INTO accounts (account_number, client, balance, days_past_due, collector, status) VALUES (?, ?, ?, ?, ?, ?)",
            (account_number, payload["client"], float(payload["balance"]), int(payload["daysPastDue"]), payload["collector"], payload["status"]),
        )
        conn.execute(
            "INSERT INTO activities (account_number, title, detail) VALUES (?, ?, ?)",
            (account_number, "New account added", f"{account_number} added for {payload['client']}.")
        )
        conn.commit()
        return {
            "accountNumber": account_number,
            "client": payload["client"],
            "balance": float(payload["balance"]),
            "daysPastDue": int(payload["daysPastDue"]),
            "collector": payload["collector"],
            "status": payload["status"],
        }
    finally:
        conn.close()


def generate_account_number(conn):
    year = date.today().year
    while True:
        cursor = conn.execute("INSERT INTO account_number_sequence () VALUES ()")
        account_number = f"ACC-{year}-{cursor.lastrowid:06d}"
        exists = conn.execute(
            "SELECT id FROM accounts WHERE account_number = ?", (account_number,)
        ).fetchone()
        if exists is None:
            return account_number


def add_client(payload):
    name = (payload.get("name") or "").strip()
    industry = (payload.get("industry") or "").strip()
    if not name or not industry:
        raise ValueError("Client name and industry are required")
    conn = get_connection()
    try:
        conn.execute("INSERT INTO clients (name, industry) VALUES (?, ?)", (name, industry))
        conn.commit()
        return {"name": name, "industry": industry}
    finally:
        conn.close()


def add_promise(payload, actor):
    account_number = payload.get("accountNumber")
    due_date = payload.get("dueDate")
    amount = payload.get("amount")
    if not account_number or not due_date or amount is None or float(amount) <= 0:
        raise ValueError("Account, a positive amount, and due date are required")
    try:
        date.fromisoformat(due_date)
    except ValueError as exc:
        raise ValueError("Due date must use YYYY-MM-DD format") from exc
    conn = get_connection()
    try:
        account = conn.execute(
            "SELECT account_number, collector FROM accounts WHERE account_number = ?", (account_number,)
        ).fetchone()
        if account is None:
            raise ValueError("Account not found")
        if actor["role"] == "collector" and account["collector"] != actor["fullName"]:
            raise ValueError("Collectors can only create promises for assigned accounts")
        conn.execute(
            "INSERT INTO promises (account_number, amount, due_date, payment_method, status) "
            "VALUES (?, ?, ?, ?, 'Upcoming')",
            (account_number, float(amount), due_date, (payload.get("paymentMethod") or "Unspecified").strip()),
        )
        conn.execute(
            "INSERT INTO activities (account_number, title, detail) VALUES (?, ?, ?)",
            (account_number, "Promise to pay recorded", f"{account_number} promised {float(amount):,.0f} due {due_date}."),
        )
        conn.commit()
        return {"accountNumber": account_number, "amount": float(amount), "dueDate": due_date, "paymentMethod": (payload.get("paymentMethod") or "Unspecified"), "status": "Upcoming"}
    finally:
        conn.close()


def delete_record(kind, record_id, actor):
    if actor["role"] != "admin":
        raise PermissionError("Only administrators can delete records")
    conn = get_connection()
    try:
        if kind == "accounts":
            row = conn.execute(
                "SELECT account_number FROM accounts WHERE id = ?", (int(record_id),)
            ).fetchone()
            if row is None:
                raise ValueError("Account not found")
            conn.execute("DELETE FROM activities WHERE account_number = ?", (row["account_number"],))
            conn.execute("DELETE FROM accounts WHERE id = ?", (int(record_id),))
            details = row["account_number"]
        elif kind == "promises":
            row = conn.execute(
                "SELECT account_number FROM promises WHERE id = ?", (int(record_id),)
            ).fetchone()
            if row is None:
                raise ValueError("Promise not found")
            conn.execute("DELETE FROM promises WHERE id = ?", (int(record_id),))
            details = f"{row['account_number']} promise {record_id}"
        elif kind == "clients":
            row = conn.execute("SELECT name FROM clients WHERE id = ?", (int(record_id),)).fetchone()
            if row is None:
                raise ValueError("Client not found")
            account_count = conn.execute(
                "SELECT COUNT(*) AS total FROM accounts WHERE client = ?", (row["name"],)
            ).fetchone()["total"]
            if account_count:
                raise ValueError("Cannot delete a client portfolio while it still has accounts")
            conn.execute("DELETE FROM users WHERE client_name = ?", (row["name"],))
            conn.execute("DELETE FROM clients WHERE id = ?", (int(record_id),))
            details = row["name"]
        elif kind == "users":
            if int(record_id) == int(actor["id"]):
                raise ValueError("You cannot delete your own signed-in account")
            row = conn.execute(
                "SELECT username, role, is_active FROM users WHERE id = ?", (int(record_id),)
            ).fetchone()
            if row is None:
                raise ValueError("User not found")
            if row["role"] == "admin" and row["is_active"]:
                active_admins = conn.execute(
                    "SELECT COUNT(*) AS total FROM users WHERE role = 'admin' AND is_active = TRUE"
                ).fetchone()["total"]
                if active_admins <= 1:
                    raise ValueError("Cannot delete the last active administrator")
            conn.execute("DELETE FROM users WHERE id = ?", (int(record_id),))
            details = row["username"]
        elif kind == "payments":
            row = conn.execute(
                "SELECT account_number, promise_id, amount FROM payments WHERE id = ?",
                (int(record_id),),
            ).fetchone()
            if row is None:
                raise ValueError("Payment not found")
            conn.execute("DELETE FROM payments WHERE id = ?", (int(record_id),))
            conn.execute(
                "UPDATE accounts SET balance = balance + ?, status = IF(status = 'Paid', 'Active', status) WHERE account_number = ?",
                (row["amount"], row["account_number"]),
            )
            if row["promise_id"]:
                remaining = conn.execute(
                    "SELECT COALESCE(SUM(amount), 0) AS total FROM payments WHERE promise_id = ?",
                    (row["promise_id"],),
                ).fetchone()["total"]
                promise = conn.execute(
                    "SELECT amount, due_date, status FROM promises WHERE id = ?",
                    (row["promise_id"],),
                ).fetchone()
                if promise and promise["status"] == "Fulfilled" and float(remaining) < float(promise["amount"]):
                    status = "Broken" if promise["due_date"] < date.today() else "Due"
                    conn.execute("UPDATE promises SET status = ? WHERE id = ?", (status, row["promise_id"]))
            details = f"{row['account_number']} payment {record_id}"
        elif kind in {"activities", "tasks", "payments"}:
            table = {"activities": "activities", "tasks": "follow_up_tasks", "payments": "payments"}[kind]
            row = conn.execute(f"SELECT id FROM {table} WHERE id = ?", (int(record_id),)).fetchone()
            if row is None:
                raise ValueError(f"{kind[:-1].title()} not found")
            conn.execute(f"DELETE FROM {table} WHERE id = ?", (int(record_id),))
            details = f"{kind[:-1]} {record_id}"
        else:
            raise ValueError("Unsupported record type")
        create_audit_entry(conn, actor, f"{kind[:-1]}.deleted", details)
        conn.commit()
        return details
    finally:
        conn.close()


class CollectFlowHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            return self._serve_file("index.html")
        if path in ("/app.js", "/styles.css"):
            return self._serve_file(path.lstrip("/"))
        if path == "/health":
            conn = get_connection()
            try:
                conn.execute("SELECT 1")
                return self._send_json({"status": "ok", "database": "ok"})
            finally:
                conn.close()
        if path == "/api/session":
            return self._send_json({"user": self._current_user()})

        user = self._authorize(self._read_module(path))
        if user is None:
            return
        routes = {
            "/api/metrics": lambda: get_metrics(user),
            "/api/accounts": lambda: {"accounts": get_accounts(user)},
            "/api/promises": lambda: {"promises": get_promises(user)},
            "/api/activities": lambda: {"activities": get_activities(user)},
            "/api/tasks": lambda: {"tasks": get_tasks(user)},
            "/api/payments": lambda: {"payments": get_payments(user)},
            "/api/clients": lambda: {"clients": get_clients(user)},
            "/api/users": lambda: {"users": get_users()},
            "/api/collectors": lambda: {"collectors": get_collectors()},
            "/api/audit": lambda: {"auditLogs": get_audit_logs()},
        }
        if path not in routes:
            return self._send_json({"status": "error", "message": "Endpoint not found"}, 404)
        self._send_json(routes[path]())

    def do_POST(self):
        path = urlparse(self.path).path
        try:
            if path == "/api/login":
                user, token = login_user(self._read_json_body())
                return self._send_json(
                    {"status": "success", "user": user},
                    headers={"Set-Cookie": self._session_cookie(token)},
                )
            if path == "/api/logout":
                user = self._current_user()
                revoke_session(self._session_token(), user)
                return self._send_json(
                    {"status": "success"},
                    headers={"Set-Cookie": self._session_cookie("", clear=True)},
                )
            if path == "/api/password":
                actor = self._current_user()
                if actor is None:
                    return self._send_json({"status": "error", "message": "Authentication required"}, 401)
                change_password(self._read_json_body(), actor, self._session_token())
                return self._send_json({"status": "success"})

            module = self._write_module(path)
            user = self._authorize(module)
            if user is None:
                return
            payload = self._read_json_body()
            if path == "/api/users":
                result = add_user(payload, user)
                return self._send_json({"status": "success", "user": result}, 201)
            if path == "/api/accounts":
                result = add_account(payload)
                self._record_audit(user, "account.created", result["accountNumber"])
                return self._send_json({"status": "success", "account": result}, 201)
            if path == "/api/promises":
                result = add_promise(payload, user)
                self._record_audit(user, "promise.created", result["accountNumber"])
                return self._send_json({"status": "success", "promise": result}, 201)
            if path == "/api/activities":
                result = add_activity(payload, user)
                return self._send_json({"status": "success", "activity": result}, 201)
            if path == "/api/tasks":
                result = add_task(payload, user)
                return self._send_json({"status": "success", "task": result}, 201)
            if path == "/api/payments":
                result = add_payment(payload, user)
                return self._send_json({"status": "success", "payment": result}, 201)
            if path == "/api/clients":
                result = add_client(payload)
                self._record_audit(user, "client.created", result["name"])
                return self._send_json({"status": "success", "client": result}, 201)
            self._send_json({"status": "error", "message": "Endpoint not found"}, 404)
        except ValueError as exc:
            self._send_json({"status": "error", "message": str(exc)}, 400)
        except IntegrityError:
            self._send_json({"status": "error", "message": "That record already exists or violates a database constraint"}, 409)

    def do_PATCH(self):
        path = urlparse(self.path).path
        prefixes = ("/api/users/", "/api/accounts/", "/api/promises/", "/api/tasks/")
        if not path.startswith(prefixes):
            return self._send_json({"status": "error", "message": "Endpoint not found"}, 404)
        root = path.split("/")[2]
        module = {"users": "users", "accounts": "accounts", "promises": "promises", "tasks": "tasks"}[root]
        actor = self._authorize(module)
        if actor is None:
            return
        try:
            user_id = path.rsplit("/", 1)[1]
            payload = self._read_json_body()
            if module == "users":
                is_active = payload.get("isActive")
                if not isinstance(is_active, bool):
                    raise ValueError("isActive must be a boolean")
                set_user_active(user_id, is_active, actor)
            elif module == "accounts":
                account_number = update_account(user_id, payload, actor)
                self._record_audit(actor, "account.updated", account_number)
            elif module == "promises":
                result = update_promise(user_id, payload, actor)
                self._record_audit(actor, "promise.status_updated", f"{user_id}: {result['status']}")
            elif module == "tasks":
                update_task(user_id, payload, actor)
            self._send_json({"status": "success"})
        except (ValueError, TypeError, PermissionError) as exc:
            self._send_json({"status": "error", "message": str(exc)}, 400)

    def do_DELETE(self):
        path = urlparse(self.path).path
        parts = path.strip("/").split("/")
        if len(parts) != 3 or parts[0] != "api":
            return self._send_json({"status": "error", "message": "Endpoint not found"}, 404)
        kind = {"tasks": "tasks"}.get(parts[1], parts[1])
        if kind not in {"accounts", "promises", "clients", "users", "activities", "tasks", "payments"}:
            return self._send_json({"status": "error", "message": "Endpoint not found"}, 404)
        actor = self._authorize("delete")
        if actor is None:
            return
        try:
            details = delete_record(kind, parts[2], actor)
            self._send_json({"status": "success", "deleted": details})
        except (ValueError, PermissionError) as exc:
            self._send_json({"status": "error", "message": str(exc)}, 400)

    @staticmethod
    def _read_module(path):
        if path == "/api/metrics":
            return "dashboard"
        if path == "/api/activities":
            return "activities"
        if path == "/api/accounts":
            return "accounts"
        if path == "/api/promises":
            return "promises"
        if path == "/api/payments":
            return "payments"
        if path == "/api/tasks":
            return "tasks"
        if path == "/api/clients":
            return "clients"
        if path == "/api/users":
            return "users"
        if path == "/api/collectors":
            return "queue"
        if path == "/api/audit":
            return "audit"
        return "unknown"

    @staticmethod
    def _write_module(path):
        return {
            "/api/accounts": "accounts",
            "/api/promises": "promises",
            "/api/tasks": "tasks",
            "/api/clients": "clients",
            "/api/users": "users",
            "/api/activities": "activities",
            "/api/payments": "payments",
        }.get(path, "unknown")

    def _current_user(self):
        return get_session_user(self._session_token())

    def _session_token(self):
        for part in self.headers.get("Cookie", "").split(";"):
            name, separator, value = part.strip().partition("=")
            if separator and name == SESSION_COOKIE:
                return value
        return ""

    def _session_cookie(self, token, clear=False):
        max_age = 0 if clear else SESSION_HOURS * 3600
        secure = "; Secure" if os.getenv("SESSION_COOKIE_SECURE", "false").lower() == "true" else ""
        return f"{SESSION_COOKIE}={token}; Path=/; HttpOnly; SameSite=Lax; Max-Age={max_age}{secure}"

    def _authorize(self, module):
        user = self._current_user()
        if user is None:
            self._send_json({"status": "error", "message": "Authentication required"}, 401)
            return None
        if module == "delete":
            if user["role"] != "admin":
                self._send_json({"status": "error", "message": "Only administrators can delete records"}, 403)
                return None
            return user
        allowed_module = module
        role = user["role"]
        if role == "client" and module in ("accounts", "promises", "clients", "activities"):
            allowed_module = "portfolio"
        elif role == "management" and module in ("accounts", "promises", "clients"):
            allowed_module = "analytics"
        if not role_can_access(role, allowed_module):
            self._send_json({"status": "error", "message": "Permission denied"}, 403)
            return None
        if self.command == "POST":
            writers = {
                "accounts": {"admin", "supervisor"},
                "promises": {"admin", "supervisor", "collector"},
                "payments": {"admin", "supervisor", "collector"},
                "activities": {"admin", "supervisor", "collector"},
                "tasks": {"admin", "supervisor", "collector"},
                "clients": {"admin", "supervisor"},
                "users": {"admin"},
            }
            if role not in writers.get(module, set()):
                self._send_json({"status": "error", "message": "Permission denied"}, 403)
                return None
        elif self.command == "PATCH":
            writers = {
                "accounts": {"admin", "supervisor", "collector"},
                "promises": {"admin", "supervisor", "collector"},
                "tasks": {"admin", "supervisor", "collector"},
                "users": {"admin"},
            }
            if role not in writers.get(module, set()):
                self._send_json({"status": "error", "message": "Permission denied"}, 403)
                return None
        return user

    def _record_audit(self, actor, action, details):
        conn = get_connection()
        try:
            create_audit_entry(conn, actor, action, details)
            conn.commit()
        finally:
            conn.close()

    def _read_json_body(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length > 1024 * 1024:
            raise ValueError("Request body is too large")
        raw = self.rfile.read(length).decode("utf-8")
        if not raw:
            return {}
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError("JSON request body must be an object")
        return payload

    def _send_json(self, payload, status=200, headers=None):
        body = json.dumps(payload, default=self._json_default).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    @staticmethod
    def _json_default(value):
        if isinstance(value, (date, datetime)):
            return value.isoformat()
        if hasattr(value, "__float__"):
            return float(value)
        raise TypeError(f"Cannot serialize {type(value).__name__}")

    def _serve_file(self, filename):
        try:
            with open(filename, "rb") as file:
                data = file.read()
            content_type = {
                ".css": "text/css; charset=utf-8",
                ".js": "application/javascript; charset=utf-8",
            }.get(os.path.splitext(filename)[1], "text/html; charset=utf-8")
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except FileNotFoundError:
            self.send_error(404, "File not found")


def main():
    if mysql is None:
        raise RuntimeError("MySQL support is missing; install dependencies from requirements.txt")
    for attempt in range(30):
        try:
            init_db()
            break
        except mysql.connector.Error:
            if attempt == 29:
                raise
            time.sleep(2)
    server = ThreadingHTTPServer(("0.0.0.0", PORT), CollectFlowHandler)
    print(f"CollectFlow running on http://0.0.0.0:{PORT}")
    server.serve_forever()


if __name__ == "__main__":
    main()