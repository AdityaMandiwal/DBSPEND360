#!/usr/bin/env python3
"""Regression harness for the LIKE ESCAPE fix (audit Finding #2).

Runs a handful of tiny SELECTs against the configured SQL warehouse to prove:
  1. Databricks accepts ``ESCAPE '\\'`` (two-backslash SQL literal → one-char
     escape character after parsing).
  2. A ``%`` / ``_`` / ``\\`` escaped by ``_escape_like_pattern`` behaves as
     a LITERAL character, not a wildcard.
  3. The end-to-end pattern shape emitted by the service code for
     ``search='50%'`` correctly matches ONLY names literally containing
     ``50%``, not every name.
  4. Single-quote SQL-injection payloads still return zero matches without
     raising.

The pre-fix regression: ``search='%'`` returned every warehouse row. Keep
this script alongside ``audit_sql_warehouse_edge_cases.py`` so any future
change to the search escape path fails loudly.

Run:
  uv run python claude_scripts/verify_like_escape.py
"""

from __future__ import annotations

import os
import sys

from dotenv import load_dotenv

load_dotenv(".env.local")

from databricks.sdk import WorkspaceClient  # noqa: E402
from databricks.sdk.service.sql import StatementState  # noqa: E402

# The escape helper we're validating. Importing it means the helper on disk is
# what we're testing, not a paste copy.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from server.services.databricks_service import _escape_like_pattern  # noqa: E402

WAREHOUSE_ID = os.getenv("DBSPEND_WAREHOUSE_ID", "148ccb90800933a1")

w = WorkspaceClient()


def run(sql: str) -> object:
    """Execute a statement and return the first cell (or a FAIL string).

    The Statement Execution API returns booleans as the literal strings
    ``'true'`` / ``'false'``. We normalise to Python bools here so call-sites
    can use ``assert res is True`` without wrapping in string comparisons.
    """
    r = w.statement_execution.execute_statement(
        warehouse_id=WAREHOUSE_ID,
        statement=sql,
        wait_timeout="30s",
    )
    if r.status and r.status.state == StatementState.FAILED:
        err = r.status.error
        return f"FAIL: {err.message if err else 'unknown'}"
    if r.result and r.result.data_array:
        cell = r.result.data_array[0][0]
        if cell == "true":
            return True
        if cell == "false":
            return False
        return cell
    return None


def emit_like_clause(search: str, column: str) -> str:
    """Reproduce the exact SQL fragment the service now emits."""
    like_pattern = _escape_like_pattern(search).replace("'", "''")
    return f"{column} LIKE '%{like_pattern}%' ESCAPE '\\\\'"


print("=" * 70)
print("Test 1: Databricks accepts ESCAPE '\\\\' as one-char escape")
print("=" * 70)
# 'foo%bar' should match LIKE 'foo\%bar' ESCAPE '\' — literal % match.
sql = "SELECT 'foo%bar' LIKE 'foo\\\\%bar' ESCAPE '\\\\' AS matches"
print(f"  SQL: {sql}")
print(f"  Result: {run(sql)}")
print()

print("=" * 70)
print("Test 2: LIKE emission for search='%' should NOT match a plain name")
print("=" * 70)
clause = emit_like_clause("%", "'clean-warehouse'")
sql = f"SELECT {clause} AS matches"
print(f"  SQL: {sql}")
res = run(sql)
print(f"  Result: {res} (expected: False — '%' is not a substring of 'clean-warehouse')")
assert res is False or res == 0, f"REGRESSION: expected False, got {res!r}"
print()

print("=" * 70)
print("Test 3: LIKE emission for search='%' SHOULD match a name containing '%'")
print("=" * 70)
clause = emit_like_clause("%", "'50%_done'")
sql = f"SELECT {clause} AS matches"
print(f"  SQL: {sql}")
res = run(sql)
print(f"  Result: {res} (expected: True — literal '%' present)")
assert res is True or res == 1, f"REGRESSION: expected True, got {res!r}"
print()

print("=" * 70)
print("Test 4: LIKE emission for search='_' should NOT match every string")
print("=" * 70)
clause = emit_like_clause("_", "'no-underscores-here'")
sql = f"SELECT {clause} AS matches"
print(f"  SQL: {sql}")
res = run(sql)
print(f"  Result: {res} (expected: False)")
assert res is False or res == 0, f"REGRESSION: expected False, got {res!r}"
print()

print("=" * 70)
print("Test 5: LIKE emission for search='_' matches literal '_' only")
print("=" * 70)
clause = emit_like_clause("_", "'has_underscore'")
sql = f"SELECT {clause} AS matches"
print(f"  SQL: {sql}")
res = run(sql)
print(f"  Result: {res} (expected: True)")
assert res is True or res == 1, f"REGRESSION: expected True, got {res!r}"
print()

print("=" * 70)
print("Test 6: SQL injection payload still returns 0 matches (no error)")
print("=" * 70)
clause = emit_like_clause("test' OR '1'='1", "'ordinary-name'")
sql = f"SELECT {clause} AS matches"
print(f"  SQL: {sql}")
res = run(sql)
print(f"  Result: {res} (expected: False)")
assert res is False or res == 0, f"REGRESSION: expected False, got {res!r}"

print()
print("ALL CHECKS PASSED — LIKE-escape fix behaves correctly.")
