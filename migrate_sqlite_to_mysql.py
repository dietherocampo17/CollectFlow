import argparse
import sqlite3
from pathlib import Path

from server import get_connection


def migrate(source_path):
    source_path = Path(source_path)
    if not source_path.is_file():
        raise FileNotFoundError(f"SQLite source database not found: {source_path}")

    source = sqlite3.connect(source_path)
    source.row_factory = sqlite3.Row
    target = get_connection()
    imported = {"clients": 0, "accounts": 0, "promises": 0, "orphanPromisesSkipped": 0, "activities": 0}
    try:
        for row in source.execute("SELECT name, industry, created_at FROM clients"):
            cursor = target.execute(
            "INSERT IGNORE INTO clients (name, industry, created_at) VALUES (?, ?, ?)",
            (row["name"], row["industry"], row["created_at"]),
            )
            imported["clients"] += cursor.rowcount

        account_numbers = []
        for row in source.execute(
            "SELECT account_number, client, balance, days_past_due, collector, status, created_at FROM accounts"
        ):
            account_numbers.append(row["account_number"])
            target.execute(
                "INSERT IGNORE INTO clients (name, industry) VALUES (?, 'Imported')",
                (row["client"],),
            )
            cursor = target.execute(
                "INSERT IGNORE INTO accounts (account_number, client, balance, days_past_due, collector, status, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                tuple(row),
            )
            imported["accounts"] += cursor.rowcount

        for row in source.execute(
            "SELECT account_number, amount, due_date, status, created_at FROM promises"
        ):
            account_exists = target.execute(
                "SELECT account_number FROM accounts WHERE account_number = ?",
                (row["account_number"],),
            ).fetchone()
            if account_exists is None:
                imported["orphanPromisesSkipped"] += 1
                continue
            existing = target.execute(
                "SELECT id FROM promises WHERE account_number = ? AND amount = ? AND due_date = ? AND status = ? LIMIT 1",
                (row["account_number"], row["amount"], row["due_date"], row["status"]),
            ).fetchone()
            if existing is None:
                target.execute(
                    "INSERT INTO promises (account_number, amount, due_date, status, created_at) VALUES (?, ?, ?, ?, ?)",
                    tuple(row),
                )
                imported["promises"] += 1

        for row in source.execute("SELECT title, detail, created_at FROM activities"):
            existing = target.execute(
                "SELECT id FROM activities WHERE title = ? AND detail = ? LIMIT 1",
                (row["title"], row["detail"]),
            ).fetchone()
            if existing is not None:
                continue
            text = f"{row['title']} {row['detail']}"
            related_account = next((number for number in account_numbers if number in text), None)
            target.execute(
                "INSERT INTO activities (account_number, title, detail, created_at) VALUES (?, ?, ?, ?)",
                (related_account, row["title"], row["detail"], row["created_at"]),
            )
            imported["activities"] += 1

        target.commit()
        return imported
    except Exception:
        target.connection.rollback()
        raise
    finally:
        source.close()
        target.close()


def main():
    parser = argparse.ArgumentParser(description="Import legacy CollectFlow business records into MySQL")
    parser.add_argument(
        "--source",
        default=str(Path(__file__).resolve().parent / "collectflow.db"),
        help="Path to the legacy SQLite collectflow.db file",
    )
    args = parser.parse_args()
    result = migrate(args.source)
    for entity, count in result.items():
        print(f"Imported {count} {entity} records")
    print("Legacy user credentials were not imported. Create replacement accounts in User Administration.")


if __name__ == "__main__":
    main()