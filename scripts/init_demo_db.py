"""Create the included demo SQLite database and populate realistic sample rows."""
from __future__ import annotations

import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "demo.db"
DDL_PATH = ROOT / "examples" / "schema.sql"


def main() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    if DB_PATH.exists():
        DB_PATH.unlink()
    connection = sqlite3.connect(DB_PATH)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript(DDL_PATH.read_text(encoding="utf-8"))
        connection.executemany(
            "INSERT INTO customers VALUES (?, ?, ?, ?, ?, ?)",
            [
                (1, "Aarav Patel", "aarav@example.com", "Ahmedabad", "Gujarat", "2024-11-03"),
                (2, "Diya Shah", "diya@example.com", "Vadodara", "Gujarat", "2025-01-14"),
                (3, "Kabir Mehta", "kabir@example.com", "Mumbai", "Maharashtra", "2025-02-20"),
                (4, "Anaya Desai", "anaya@example.com", "Surat", "Gujarat", "2025-04-02"),
                (5, "Ishaan Rao", "ishaan@example.com", "Pune", "Maharashtra", "2025-05-16"),
                (6, "Mira Joshi", "mira@example.com", "Rajkot", "Gujarat", "2025-07-09"),
            ],
        )
        connection.executemany(
            "INSERT INTO categories VALUES (?, ?)",
            [(1, "Electronics"), (2, "Home & Kitchen"), (3, "Books")],
        )
        connection.executemany(
            "INSERT INTO products VALUES (?, ?, ?, ?, ?)",
            [
                (1, "Wireless Headphones", 1, 2499.00, 35),
                (2, "Mechanical Keyboard", 1, 3999.00, 18),
                (3, "USB-C Hub", 1, 1799.00, 42),
                (4, "Coffee Maker", 2, 3299.00, 12),
                (5, "Desk Lamp", 2, 899.00, 60),
                (6, "Clean Code", 3, 650.00, 25),
                (7, "Design Patterns", 3, 850.00, 16),
            ],
        )
        connection.executemany(
            "INSERT INTO orders VALUES (?, ?, ?, ?)",
            [
                (1001, 1, "2025-01-05", "delivered"),
                (1002, 2, "2025-02-12", "delivered"),
                (1003, 1, "2025-03-22", "delivered"),
                (1004, 3, "2025-06-02", "shipped"),
                (1005, 4, "2025-08-17", "delivered"),
                (1006, 2, "2025-10-11", "delivered"),
                (1007, 5, "2026-01-09", "delivered"),
            ],
        )
        connection.executemany(
            "INSERT INTO order_items VALUES (?, ?, ?, ?, ?)",
            [
                (1, 1001, 1, 1, 2499.00),
                (2, 1001, 6, 1, 650.00),
                (3, 1002, 2, 1, 3999.00),
                (4, 1002, 3, 2, 1799.00),
                (5, 1003, 4, 1, 3299.00),
                (6, 1003, 5, 2, 899.00),
                (7, 1004, 1, 2, 2499.00),
                (8, 1004, 7, 1, 850.00),
                (9, 1005, 6, 2, 650.00),
                (10, 1006, 3, 1, 1799.00),
                (11, 1006, 5, 1, 899.00),
                (12, 1007, 2, 1, 3999.00),
            ],
        )
        connection.executemany(
            "INSERT INTO reviews VALUES (?, ?, ?, ?, ?, ?)",
            [
                (1, 1, 1, 5, "Great sound", "2025-01-10"),
                (2, 2, 2, 4, "Good keyboard", "2025-02-20"),
                (3, 3, 4, 5, "Works well", "2025-06-08"),
                (4, 4, 6, 5, "Very useful", "2025-08-25"),
            ],
        )
        connection.commit()
        print(f"Demo database created: {DB_PATH}")
    finally:
        connection.close()


if __name__ == "__main__":
    main()
