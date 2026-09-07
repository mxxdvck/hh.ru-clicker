"""Durable two-phase ledger for outbound HH applications.

The ledger is intentionally separate from legacy applied_vacancies.json.
It protects every new send path against duplicate/in-flight submissions and
keeps crash state explicit instead of blindly retrying a POST after restart.
"""

from __future__ import annotations

import sqlite3
import threading
import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app import storage


_SCHEMA_LOCK = threading.Lock()
_SCHEMA_READY: set[str] = set()
PROCESS_RUN_ID = uuid.uuid4().hex


def new_run_id() -> str:
    return uuid.uuid4().hex


def _db_path():
    return storage.DATA_DIR / "applications.sqlite3"


def _connect() -> sqlite3.Connection:
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=10, isolation_level=None)
    conn.row_factory = sqlite3.Row
    return conn

def _ensure_schema(conn: sqlite3.Connection) -> None:
    key = str(_db_path())
    if key in _SCHEMA_READY:
        return
    with _SCHEMA_LOCK:
        if key in _SCHEMA_READY:
            return
        conn.execute("""
            CREATE TABLE IF NOT EXISTS applications (
                account_name TEXT NOT NULL,
                vacancy_id TEXT NOT NULL,
                resume_id TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT '',
                run_id TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                attempted_at TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL,
                applied_at TEXT NOT NULL DEFAULT '',
                detail TEXT NOT NULL DEFAULT '',
                PRIMARY KEY (account_name, vacancy_id, resume_id)
            )
        """)
        columns = {row[1] for row in conn.execute('PRAGMA table_info(applications)').fetchall()}
        if 'run_id' not in columns:
            conn.execute("ALTER TABLE applications ADD COLUMN run_id TEXT NOT NULL DEFAULT ''")
        if 'attempted_at' not in columns:
            conn.execute("ALTER TABLE applications ADD COLUMN attempted_at TEXT NOT NULL DEFAULT ''")
            conn.execute("UPDATE applications SET attempted_at=created_at WHERE attempted_at=''")
        if 'applied_at' not in columns:
            conn.execute("ALTER TABLE applications ADD COLUMN applied_at TEXT NOT NULL DEFAULT ''")
            conn.execute("UPDATE applications SET applied_at=updated_at WHERE status='applied' AND applied_at=''")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_applications_account_status "
            "ON applications(account_name, status, applied_at, updated_at)"
        )
        _SCHEMA_READY.add(key)


def _now() -> str:
    """Return quota timestamps in Moscow time, independent of host timezone."""
    try:
        now = datetime.now(ZoneInfo("Europe/Moscow"))
    except Exception:
        now = datetime.now(timezone(timedelta(hours=3)))
    return now.isoformat(timespec="seconds")

def reserve_application(
    account_name: str,
    vacancy_id: str,
    resume_id: str = "",
    source: str = "",
    run_id: str = "",
    *,
    date_prefix: str = "",
    external_daily_used: int = 0,
    daily_limit: int = 0,
    hh_limit: int = 0,
    run_limit: int = 0,
) -> tuple[bool, str, int, int]:
    """Atomically enforce ledger quotas and reserve one application.

    SQLite ``BEGIN IMMEDIATE`` makes the quota check + reservation one critical
    section across threads and even separate processes sharing the same data dir.
    External counters (legacy history / HH server count) are passed in and merged
    conservatively with durable ledger counts.
    """
    account_name = str(account_name or "").strip()
    vacancy_id = str(vacancy_id or "").strip()
    resume_id = str(resume_id or "").strip()
    run_id = str(run_id or PROCESS_RUN_ID)
    if not account_name or not vacancy_id:
        return False, "invalid_key", 0, 0

    now = _now()
    date_prefix = str(date_prefix or now[:10])
    external_daily_used = max(int(external_daily_used or 0), 0)
    daily_limit = max(int(daily_limit or 0), 0)
    hh_limit = max(int(hh_limit or 0), 0)
    run_limit = max(int(run_limit or 0), 0)
    conn = _connect()
    try:
        _ensure_schema(conn)
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT status FROM applications WHERE account_name=? AND vacancy_id=? AND resume_id=?",
            (account_name, vacancy_id, resume_id),
        ).fetchone()
        if row and row["status"] in {
            "applying", "applied", "already", "interrupted", "failed_permanent"
        }:
            conn.execute("ROLLBACK")
            return False, str(row["status"]), 0, 0

        applied_row = conn.execute(
            "SELECT COUNT(*) AS n FROM applications WHERE account_name=? "
            "AND status='applied' AND applied_at LIKE ?",
            (account_name, f"{date_prefix}%"),
        ).fetchone()
        inflight_row = conn.execute(
            "SELECT COUNT(*) AS n FROM applications WHERE account_name=? "
            "AND status='applying' AND attempted_at LIKE ?",
            (account_name, f"{date_prefix}%"),
        ).fetchone()
        run_row = conn.execute(
            "SELECT COUNT(*) AS n FROM applications WHERE account_name=? AND run_id=? "
            "AND status IN ('applying','applied')",
            (account_name, run_id),
        ).fetchone()
        ledger_applied = int(applied_row["n"] if applied_row else 0)
        inflight = int(inflight_row["n"] if inflight_row else 0)
        run_used = int(run_row["n"] if run_row else 0)
        daily_used = max(external_daily_used, ledger_applied) + inflight

        if daily_limit and daily_used >= daily_limit:
            conn.execute("ROLLBACK")
            return False, "daily_limit", daily_used, run_used
        if hh_limit and daily_used >= hh_limit:
            conn.execute("ROLLBACK")
            return False, "hh_limit", daily_used, run_used
        if run_limit and run_used >= run_limit:
            conn.execute("ROLLBACK")
            return False, "run_limit", daily_used, run_used

        if row:
            conn.execute(
                "UPDATE applications SET status='applying', source=?, run_id=?, attempted_at=?, updated_at=?, applied_at='', detail='' "
                "WHERE account_name=? AND vacancy_id=? AND resume_id=?",
                (source, run_id, now, now, account_name, vacancy_id, resume_id),
            )
        else:
            conn.execute(
                "INSERT INTO applications(account_name,vacancy_id,resume_id,status,source,run_id,created_at,attempted_at,updated_at) "
                "VALUES(?,?,?,'applying',?,?,?,?,?)",
                (account_name, vacancy_id, resume_id, source, run_id, now, now, now),
            )
        conn.execute("COMMIT")
        return True, "reserved", daily_used, run_used
    except Exception:
        try:
            conn.execute("ROLLBACK")
        except Exception:
            pass
        raise
    finally:
        conn.close()

def mark_application(account_name: str, vacancy_id: str, resume_id: str = "",
                     status: str = "failed_transient", detail: str = "",
                     applied_at: str = "") -> None:
    """Finalize/release a reserved application after a network result.

    ``applied_at`` is separate from ``updated_at`` so retries/reconciliation on
    another day cannot move an old application into today's quota.
    """
    now = _now()
    status = str(status)
    resolved_applied_at = str(applied_at or now) if status == "applied" else ""
    conn = _connect()
    try:
        _ensure_schema(conn)
        conn.execute(
            "UPDATE applications SET status=?, updated_at=?, applied_at=?, detail=? "
            "WHERE account_name=? AND vacancy_id=? AND resume_id=?",
            (status, now, resolved_applied_at, str(detail or "")[:1000],
             str(account_name or ""), str(vacancy_id or ""), str(resume_id or "")),
        )
    finally:
        conn.close()


def mark_interrupted_startup() -> int:
    """Fail closed after restart: unresolved sends become interrupted, never retried blindly."""
    conn = _connect()
    try:
        _ensure_schema(conn)
        now = _now()
        cur = conn.execute(
            "UPDATE applications SET status='interrupted', updated_at=?, "
            "detail='process restarted before send result was recorded' WHERE status='applying'",
            (now,),
        )
        return int(cur.rowcount or 0)
    finally:
        conn.close()


def mark_run_interrupted(account_name: str, run_id: str, detail: str = "worker crashed before send result was recorded") -> int:
    """Move this run's unresolved sends to fail-closed crash-recovery state."""
    account_name = str(account_name or "").strip()
    run_id = str(run_id or "").strip()
    if not account_name or not run_id:
        return 0
    conn = _connect()
    try:
        _ensure_schema(conn)
        now = _now()
        cur = conn.execute(
            "UPDATE applications SET status='interrupted', updated_at=?, detail=? "
            "WHERE account_name=? AND run_id=? AND status='applying'",
            (now, str(detail or "")[:1000], account_name, run_id),
        )
        return int(cur.rowcount or 0)
    finally:
        conn.close()


def count_applied_today(account_name: str, date_prefix: str) -> int:
    conn = _connect()
    try:
        _ensure_schema(conn)
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM applications WHERE account_name=? "
            "AND status='applied' AND applied_at LIKE ?",
            (str(account_name or ""), f"{date_prefix}%"),
        ).fetchone()
        return int(row["n"] if row else 0)
    finally:
        conn.close()

def count_inflight_today(account_name: str, date_prefix: str) -> int:
    conn = _connect()
    try:
        _ensure_schema(conn)
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM applications WHERE account_name=? "
            "AND status='applying' AND attempted_at LIKE ?",
            (str(account_name or ""), f"{date_prefix}%"),
        ).fetchone()
        return int(row["n"] if row else 0)
    finally:
        conn.close()


def count_current_run(account_name: str, run_id: str = "") -> int:
    """Count successful plus currently reserved sends in one explicit bot run."""
    run_id = str(run_id or PROCESS_RUN_ID)
    conn = _connect()
    try:
        _ensure_schema(conn)
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM applications WHERE account_name=? AND run_id=? "
            "AND status IN ('applying','applied')",
            (str(account_name or ""), run_id),
        ).fetchone()
        return int(row["n"] if row else 0)
    finally:
        conn.close()


def get_status_counts(account_name: str) -> dict[str, int]:
    """Return durable per-status application counts for one account."""
    conn = _connect()
    try:
        _ensure_schema(conn)
        rows = conn.execute(
            "SELECT status, COUNT(*) AS n FROM applications WHERE account_name=? GROUP BY status",
            (str(account_name or ""),),
        ).fetchall()
        return {str(row["status"]): int(row["n"] or 0) for row in rows}
    finally:
        conn.close()


def list_interrupted(account_name: str, limit: int = 200) -> list[dict]:
    """Return unresolved previous-run sends for safe startup reconciliation."""
    conn = _connect()
    try:
        _ensure_schema(conn)
        rows = conn.execute(
            "SELECT account_name,vacancy_id,resume_id,status,source,run_id,created_at,attempted_at,updated_at,applied_at,detail "
            "FROM applications WHERE account_name=? AND status='interrupted' "
            "ORDER BY attempted_at DESC LIMIT ?",
            (str(account_name or ""), max(int(limit or 0), 1)),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def confirm_interrupted_applied(account_name: str, vacancy_id: str, resume_id: str = "") -> bool:
    """Confirm a crash-interrupted send only after HH shows the negotiation.

    The original ``attempted_at`` is preserved as ``applied_at`` so a restart
    after midnight cannot charge yesterday's send against today's quota.
    """
    conn = _connect()
    try:
        _ensure_schema(conn)
        row = conn.execute(
            "SELECT attempted_at,created_at FROM applications "
            "WHERE account_name=? AND vacancy_id=? AND resume_id=? AND status='interrupted'",
            (str(account_name or ""), str(vacancy_id or ""), str(resume_id or "")),
        ).fetchone()
        if not row:
            return False
        applied_at = str(row["attempted_at"] or row["created_at"] or _now())
        cur = conn.execute(
            "UPDATE applications SET status='applied', applied_at=?, updated_at=?, "
            "detail='confirmed by HH negotiations after interrupted send' "
            "WHERE account_name=? AND vacancy_id=? AND resume_id=? AND status='interrupted'",
            (applied_at, _now(), str(account_name or ""), str(vacancy_id or ""), str(resume_id or "")),
        )
        return int(cur.rowcount or 0) == 1
    finally:
        conn.close()
