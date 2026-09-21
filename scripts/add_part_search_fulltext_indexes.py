"""
Create FULLTEXT indexes used by /vehiculo/searchPartesPaginator.

Run from repo root with MySQL env in .env:
  python scripts/add_part_search_fulltext_indexes.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text

from app.config.database import mysql_engine


INDEXES = (
    (
        "tiposparte",
        "ft_tiposparte_descripcion",
        "CREATE FULLTEXT INDEX ft_tiposparte_descripcion ON tiposparte (TipoParteDescripcion)",
    ),
    (
        "tipospartetag",
        "ft_tipospartetag_descripcion",
        "CREATE FULLTEXT INDEX ft_tipospartetag_descripcion ON tipospartetag (TipoParteTagDescripcion)",
    ),
)


def _index_exists(conn, table_name: str, index_name: str) -> bool:
    row = conn.execute(
        text(
            """
            SELECT 1
            FROM information_schema.STATISTICS
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME = :table_name
              AND INDEX_NAME = :index_name
            LIMIT 1
            """
        ),
        {"table_name": table_name, "index_name": index_name},
    ).first()
    return row is not None


def main() -> None:
    if mysql_engine is None:
        raise SystemExit("MySQL is not connected")

    with mysql_engine.begin() as conn:
        for table_name, index_name, ddl in INDEXES:
            if _index_exists(conn, table_name, index_name):
                print(f"{index_name} already exists on {table_name}")
                continue
            print(f"Creating {index_name} on {table_name}...")
            conn.execute(text(ddl))
            print(f"Created {index_name}")


if __name__ == "__main__":
    main()
