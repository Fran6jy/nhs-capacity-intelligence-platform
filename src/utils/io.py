"""I/O helpers: read/write parquet and CSV consistently."""
from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path

import duckdb
import pandas as pd

from src.utils.logging import get_logger

log = get_logger("io")


def write_parquet(df: pd.DataFrame, path: Path, partition_cols: Iterable[str] | None = None) -> None:
    """Write a DataFrame to parquet, creating parent dirs as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False, partition_cols=partition_cols)
    log.info("write_parquet", path=str(path), rows=len(df))


def read_parquet(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Parquet file not found: {path}")
    return pd.read_parquet(path)


def list_parquet_files(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*.parquet") if p.is_file())


# --------------------------------------------------------------------------- #
# SQL helpers — split multi-statement scripts safely, ignoring comments.
# --------------------------------------------------------------------------- #

_LINE_COMMENT_RE = re.compile(r"--[^\n]*")


def _strip_line_comments(sql: str) -> str:
    """Remove `--` line comments but preserve string literals."""
    out, i, n = [], 0, len(sql)
    while i < n:
        c = sql[i]
        if c == "'":
            # copy through single-quoted string literal, honour escaped quotes
            j = i + 1
            while j < n:
                if sql[j] == "'":
                    if j + 1 < n and sql[j + 1] == "'":
                        j += 2  # escaped quote
                        continue
                    j += 1
                    break
                j += 1
            out.append(sql[i:j])
            i = j
        elif c == "-" and i + 1 < n and sql[i + 1] == "-":
            # skip to end of line
            nl = sql.find("\n", i)
            i = nl + 1 if nl != -1 else n
        else:
            out.append(c)
            i += 1
    return "".join(out)


def split_sql_statements(sql: str) -> list[str]:
    """Split a SQL script into non-empty, non-comment-only statements.

    Strips ``--`` line comments first so that statements preceded by a comment
    header (e.g. ``-- FACT TABLE\\nCREATE TABLE ...``) are not skipped.
    """
    cleaned = _strip_line_comments(sql)
    return [s.strip() for s in cleaned.split(";") if s.strip()]


def execute_sql_script(con: duckdb.DuckDBPyConnection, sql: str) -> int:
    """Execute every statement in a multi-statement script. Returns the count."""
    count = 0
    for stmt in split_sql_statements(sql):
        try:
            con.execute(stmt)
            count += 1
        except duckdb.Error as exc:
            log.error("sql.statement_failed", stmt=stmt[:80], error=str(exc))
            raise
    return count
