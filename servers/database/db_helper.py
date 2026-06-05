# SPDX-License-Identifier: Apache-2.0
"""Helpers for creating a sample SQLite database."""

from __future__ import annotations

import sqlite3
from pathlib import Path


def create_sample_db(db_path: str | Path) -> Path:
    """Create a sample database with users, products, and orders tables.

    Args:
        db_path: Destination SQLite database path.

    Returns:
        The created database path.
    """
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            DROP TABLE IF EXISTS orders;
            DROP TABLE IF EXISTS products;
            DROP TABLE IF EXISTS users;

            CREATE TABLE users (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE
            );

            CREATE TABLE products (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                price REAL NOT NULL
            );

            CREATE TABLE orders (
                id INTEGER PRIMARY KEY,
                user_id INTEGER NOT NULL,
                product_id INTEGER NOT NULL,
                quantity INTEGER NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users (id),
                FOREIGN KEY (product_id) REFERENCES products (id)
            );
            """
        )
        connection.executemany(
            "INSERT INTO users (id, name, email) VALUES (?, ?, ?)",
            [
                (1, "Alice", "alice@example.com"),
                (2, "Bob", "bob@example.com"),
                (3, "Carol", "carol@example.com"),
            ],
        )
        connection.executemany(
            "INSERT INTO products (id, name, price) VALUES (?, ?, ?)",
            [
                (1, "Keyboard", 99.0),
                (2, "Mouse", 49.0),
                (3, "Monitor", 299.0),
            ],
        )
        connection.executemany(
            "INSERT INTO orders (id, user_id, product_id, quantity) VALUES (?, ?, ?, ?)",
            [
                (1, 1, 1, 1),
                (2, 1, 2, 2),
                (3, 2, 3, 1),
            ],
        )
        connection.commit()

    return path
