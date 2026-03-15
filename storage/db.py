"""
SQLite-хранилище для истории прогонов и результатов.
Создаётся автоматически при первом запуске.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "history.db"


def _ensure_dir():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)


@contextmanager
def get_conn():
    _ensure_dir()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    """Создаёт таблицы, если ещё не существуют."""
    with get_conn() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS runs (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id      TEXT UNIQUE NOT NULL,
            source      TEXT,          -- 'manual' | 'teamcity'
            ingested_at TEXT NOT NULL,
            total       INTEGER DEFAULT 0,
            failed      INTEGER DEFAULT 0,
            broken      INTEGER DEFAULT 0,
            passed      INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS test_results (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id        TEXT NOT NULL,
            uid           TEXT NOT NULL,
            name          TEXT NOT NULL,
            full_name     TEXT NOT NULL,
            status        TEXT NOT NULL,   -- passed/failed/broken/skipped
            duration_ms   INTEGER,
            error_message TEXT,
            stack_trace   TEXT,
            labels_json   TEXT,
            steps_json    TEXT,
            FOREIGN KEY (run_id) REFERENCES runs(run_id)
        );

        CREATE TABLE IF NOT EXISTS analyses (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id        TEXT NOT NULL,
            analyzed_at   TEXT NOT NULL,
            result_json   TEXT NOT NULL,   -- полный JSON-ответ от LLM
            FOREIGN KEY (run_id) REFERENCES runs(run_id)
        );

        CREATE INDEX IF NOT EXISTS idx_tr_full_name ON test_results(full_name);
        CREATE INDEX IF NOT EXISTS idx_tr_run_id    ON test_results(run_id);
        CREATE INDEX IF NOT EXISTS idx_tr_status    ON test_results(status);
        """)
    print(f"[DB] База инициализирована: {DB_PATH}")


def save_run(run_id: str, results: list, source: str = "manual"):
    """Сохраняет прогон и все его тест-результаты."""
    total   = len(results)
    failed  = sum(1 for r in results if r.status == "failed")
    broken  = sum(1 for r in results if r.status == "broken")
    passed  = sum(1 for r in results if r.status == "passed")

    with get_conn() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO runs
               (run_id, source, ingested_at, total, failed, broken, passed)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (run_id, source, datetime.utcnow().isoformat(), total, failed, broken, passed),
        )
        for r in results:
            conn.execute(
                """INSERT OR REPLACE INTO test_results
                   (run_id, uid, name, full_name, status, duration_ms,
                    error_message, stack_trace, labels_json, steps_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    run_id, r.uid, r.name, r.full_name, r.status,
                    r.duration_ms, r.error_message, r.stack_trace,
                    json.dumps(r.labels, ensure_ascii=False),
                    json.dumps([{"name": s.name, "status": s.status} for s in r.steps],
                               ensure_ascii=False),
                ),
            )
    print(f"[DB] Сохранён прогон {run_id}: {total} тестов, {failed} failed, {broken} broken")


def get_test_history(full_name: str, limit: int = 20) -> list[dict]:
    """Возвращает последние N результатов для конкретного теста."""
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT tr.status, tr.error_message, r.ingested_at
               FROM test_results tr
               JOIN runs r ON tr.run_id = r.run_id
               WHERE tr.full_name = ?
               ORDER BY r.ingested_at DESC
               LIMIT ?""",
            (full_name, limit),
        ).fetchall()
    return [dict(row) for row in rows]


def save_analysis(run_id: str, analysis_json: str):
    """Сохраняет JSON-ответ анализа для прогона."""
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO analyses (run_id, analyzed_at, result_json)
               VALUES (?, ?, ?)""",
            (run_id, datetime.utcnow().isoformat(), analysis_json),
        )
    print(f"[DB] Анализ сохранён для прогона {run_id}")


def list_runs(limit: int = 10) -> list[dict]:
    """Возвращает последние N прогонов."""
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT run_id, source, ingested_at, total, failed, broken, passed
               FROM runs ORDER BY ingested_at DESC LIMIT ?""",
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]
