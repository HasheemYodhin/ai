"""Copy Dabba's SQLite databases into an empty PostgreSQL database."""

import argparse
import re
import sqlite3
from contextlib import closing
from pathlib import Path

from dabba.platform.core import SCHEMA, PlatformStore
from dabba.platform.postgres import (
    PostgresConnection,
    database_url,
    initialize_postgres_conversations,
)


PLATFORM_TABLES = tuple(re.findall(r"CREATE TABLE IF NOT EXISTS (\w+)", SCHEMA))
CONVERSATION_TABLES = (
    "conversations",
    "conversation_deletions",
    "saved_messages",
    "chat_shares",
)
IDENTITY_TABLES = ("task_events", "audit_logs", "cowork_activity")


def _open_snapshot(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(path.resolve().as_uri() + "?mode=ro")


def migrate(platform_path: Path, conversations_path: Path, url: str) -> dict[str, int]:
    """Copy rows in foreign-key order and rebuild the conversation message index."""
    counts = {}
    with (
        closing(_open_snapshot(platform_path)) as platform,
        closing(_open_snapshot(conversations_path)) as conversations,
    ):
        for source, required_table in (
            (platform, "users"),
            (conversations, "conversations"),
        ):
            if not source.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                (required_table,),
            ).fetchone():
                raise ValueError(
                    f"SQLite snapshot is missing the {required_table} table"
                )

        PlatformStore(postgres_url=url)
        initialize_postgres_conversations(url)
        with closing(PostgresConnection(url)) as target, target:
            target.begin_write()
            for table in (*PLATFORM_TABLES, *CONVERSATION_TABLES, "messages"):
                if target.execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone():
                    raise ValueError(
                        "PostgreSQL destination contains Dabba data. Use an empty database."
                    )
            for source, tables in (
                (platform, PLATFORM_TABLES),
                (conversations, CONVERSATION_TABLES),
            ):
                for table in tables:
                    names = [
                        row[1] for row in source.execute(f"PRAGMA table_info({table})")
                    ]
                    if not names:
                        continue
                    if not all(
                        re.fullmatch(r"[a-z_][a-z0-9_]*", name) for name in names
                    ):
                        raise ValueError(
                            f"Unexpected column name in SQLite table {table}"
                        )
                    columns = ", ".join(f'"{name}"' for name in names)
                    placeholders = ", ".join("?" for _ in names)
                    rows = source.execute(f"SELECT {columns} FROM {table}")
                    counts[table] = 0
                    while batch := rows.fetchmany(200):
                        target.executemany(
                            f"INSERT INTO {table} ({columns}) VALUES ({placeholders})",
                            batch,
                        )
                        counts[table] += len(batch)
            for table in IDENTITY_TABLES:
                target.execute(
                    f"""SELECT setval(pg_get_serial_sequence(?, 'id'),
                        COALESCE(MAX(id), 1), COUNT(*) > 0) FROM {table}""",
                    (table,),
                )
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "snapshot_dir", type=Path, help="Directory containing both SQLite snapshots"
    )
    args = parser.parse_args()
    url = database_url()
    if not url:
        parser.error("Set DATABASE_URL to the empty PostgreSQL database")
    try:
        counts = migrate(
            args.snapshot_dir / "platform.db",
            args.snapshot_dir / "conversations.db",
            url,
        )
    except (OSError, ValueError, sqlite3.Error) as error:
        parser.exit(1, f"Import failed: {error}\n")
    except Exception as error:
        parser.exit(
            1,
            f"Import failed ({type(error).__name__}). Check the database connection and schema.\n",
        )
    for table, count in counts.items():
        print(f"{table}: {count}")


if __name__ == "__main__":
    main()
