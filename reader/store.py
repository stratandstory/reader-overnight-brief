"""Local SQLite store: collected items, fetch log, calendar, story memory, runs, usage."""

from __future__ import annotations

import json
import re
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL,
    publisher TEXT NOT NULL,
    section TEXT,
    kind TEXT NOT NULL,
    tier INTEGER NOT NULL,
    owner TEXT,
    title TEXT NOT NULL,
    summary TEXT,
    url TEXT NOT NULL,
    published_utc TEXT NOT NULL,
    first_seen_utc TEXT NOT NULL,
    last_seen_utc TEXT NOT NULL,
    model_ok INTEGER NOT NULL DEFAULT 1,
    extra TEXT
);
CREATE INDEX IF NOT EXISTS items_published ON items(published_utc);

CREATE TABLE IF NOT EXISTS fetch_log (
    fetched_utc TEXT, source_id TEXT, status TEXT, entries INTEGER, new_items INTEGER, kept INTEGER,
    oldest_utc TEXT, newest_utc TEXT, gap INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS calendar (
    id TEXT PRIMARY KEY,
    event_date TEXT NOT NULL,
    title TEXT NOT NULL,
    source_id TEXT,
    publisher TEXT,
    url TEXT,
    origin TEXT,
    added_utc TEXT
);

CREATE TABLE IF NOT EXISTS stories (
    id TEXT PRIMARY KEY,
    title TEXT,
    category TEXT,
    first_seen_utc TEXT,
    last_updated_utc TEXT,
    last_state TEXT,
    status TEXT DEFAULT 'open',
    times_reported INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS story_updates (
    story_id TEXT, run_id TEXT, created_utc TEXT, text TEXT, claim_ids TEXT
);

CREATE TABLE IF NOT EXISTS claims (
    id TEXT PRIMARY KEY,
    run_id TEXT,
    story_key TEXT,
    text TEXT,
    verdict TEXT,
    status TEXT,
    item_ids TEXT,
    quotes TEXT,
    note TEXT
);

CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    started_utc TEXT,
    finished_utc TEXT,
    window_start_utc TEXT,
    window_end_utc TEXT,
    status TEXT,
    cost_usd REAL,
    brief_path TEXT,
    summary TEXT,
    stats TEXT
);

CREATE TABLE IF NOT EXISTS usage (
    run_id TEXT, stage TEXT, model TEXT, calls INTEGER, input_tokens INTEGER,
    output_tokens INTEGER, cache_read INTEGER, cache_write INTEGER, cost_usd REAL
);
"""


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def parse_iso(s: str) -> datetime:
    return datetime.fromisoformat(s)


_LOWER_WORD = re.compile(r"(?<![A-Za-z0-9.'’-])[a-z][a-z'’-]*[a-z]")


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.lock = threading.Lock()
        with self.lock:
            self.db.executescript(SCHEMA)
            # Columns added after the first databases were created.
            have = {r[1] for r in self.db.execute("PRAGMA table_info(fetch_log)")}
            for column, kind in [("oldest_utc", "TEXT"), ("newest_utc", "TEXT"), ("gap", "INTEGER DEFAULT 0")]:
                if column not in have:
                    self.db.execute(f"ALTER TABLE fetch_log ADD COLUMN {column} {kind}")
            self.db.commit()

    def _exec(self, sql: str, params: tuple | list = ()) -> sqlite3.Cursor:
        with self.lock:
            cur = self.db.execute(sql, params)
            self.db.commit()
            return cur

    def _all(self, sql: str, params: tuple | list = ()) -> list[dict]:
        with self.lock:
            return [dict(r) for r in self.db.execute(sql, params).fetchall()]

    # ---------------------------------------------------------------- items
    def upsert_item(self, item: dict) -> bool:
        """Insert a new item or refresh last_seen/title/summary. Returns True if new.

        An empty summary never overwrites a stored one: a news sitemap lists the same release
        as the publisher's RSS feed, without the summary.
        """
        now = iso(utcnow())
        with self.lock:
            row = self.db.execute("SELECT id FROM items WHERE id = ?", (item["id"],)).fetchone()
            if row:
                self.db.execute(
                    """UPDATE items SET last_seen_utc = ?, title = ?,
                       summary = CASE WHEN ? = '' THEN summary ELSE ? END WHERE id = ?""",
                    (now, item["title"], item["summary"], item["summary"], item["id"]),
                )
                self.db.commit()
                return False
            self.db.execute(
                """INSERT INTO items (id, source_id, publisher, section, kind, tier, owner, title, summary,
                   url, published_utc, first_seen_utc, last_seen_utc, model_ok, extra)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    item["id"], item["source_id"], item["publisher"], item["section"], item["kind"],
                    item["tier"], item["owner"], item["title"], item["summary"], item["url"],
                    item["published_utc"], now, now, int(item.get("model_ok", True)),
                    json.dumps(item.get("extra") or {}),
                ),
            )
            self.db.commit()
            return True

    def items_in_window(self, start: datetime, end: datetime) -> list[dict]:
        return self._all(
            "SELECT * FROM items WHERE published_utc >= ? AND published_utc <= ? ORDER BY published_utc DESC",
            (iso(start), iso(end)),
        )

    def items_by_ids(self, ids: list[str]) -> dict[str, dict]:
        if not ids:
            return {}
        marks = ",".join("?" * len(ids))
        return {r["id"]: r for r in self._all(f"SELECT * FROM items WHERE id IN ({marks})", ids)}

    # ---------------------------------------------------------------- fetch log
    def log_fetch(self, source_id: str, status: str, entries: int, new_items: int, kept: int,
                  oldest: datetime | None = None, newest: datetime | None = None, gap: bool = False) -> None:
        self._exec(
            """INSERT INTO fetch_log (fetched_utc, source_id, status, entries, new_items, kept,
               oldest_utc, newest_utc, gap) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (iso(utcnow()), source_id, status, entries, new_items, kept,
             iso(oldest) if oldest else None, iso(newest) if newest else None, int(gap)),
        )

    def last_span(self, source_id: str) -> dict | None:
        """The most recent successful check that recorded its entries' publication times."""
        rows = self._all(
            """SELECT fetched_utc, oldest_utc, newest_utc FROM fetch_log
               WHERE source_id = ? AND newest_utc IS NOT NULL ORDER BY fetched_utc DESC LIMIT 1""",
            (source_id,),
        )
        return rows[0] if rows else None

    def gaps_since(self, since: datetime) -> list[dict]:
        return self._all(
            "SELECT fetched_utc, source_id FROM fetch_log WHERE gap = 1 AND fetched_utc >= ? ORDER BY fetched_utc",
            (iso(since),),
        )

    def gaps_between(self, start: datetime, end: datetime) -> list[dict]:
        return self._all(
            "SELECT fetched_utc, source_id FROM fetch_log WHERE gap = 1 AND fetched_utc >= ? AND fetched_utc <= ? "
            "ORDER BY fetched_utc",
            (iso(start), iso(end)),
        )

    def latest_fetches(self, before: datetime | None = None) -> dict[str, dict]:
        """Each source's most recent check, or its most recent check at or before `before`."""
        cutoff = iso(before) if before else "9999"
        rows = self._all(
            """SELECT f.* FROM fetch_log f JOIN (
                   SELECT source_id, MAX(fetched_utc) AS m FROM fetch_log WHERE fetched_utc <= ? GROUP BY source_id
               ) last ON f.source_id = last.source_id AND f.fetched_utc = last.m""",
            (cutoff,),
        )
        return {r["source_id"]: r for r in rows}

    def ordinary_words(self, min_items: int = 2) -> set[str]:
        """Words the collected news prints in lower case in at least `min_items` items: ordinary words,
        whatever capitalisation they get at the start of a sentence. Names almost never appear this way."""
        counts: dict[str, int] = {}
        for r in self._all("SELECT title, summary FROM items"):
            for w in set(_LOWER_WORD.findall(f"{r['title']} {r['summary'] or ''}")):
                counts[w] = counts.get(w, 0) + 1
        return {w for w, n in counts.items() if n >= min_items}

    def fetches_since(self, since: datetime) -> list[dict]:
        return self._all("SELECT * FROM fetch_log WHERE fetched_utc >= ?", (iso(since),))

    # ---------------------------------------------------------------- calendar
    def upsert_calendar(self, event: dict) -> None:
        self._exec(
            """INSERT INTO calendar (id, event_date, title, source_id, publisher, url, origin, added_utc)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET event_date = excluded.event_date, title = excluded.title,
                   url = excluded.url""",
            (
                event["id"], event["event_date"], event["title"], event.get("source_id"),
                event.get("publisher"), event.get("url"), event.get("origin", "schedule"), iso(utcnow()),
            ),
        )

    def calendar_between(self, first: str, last: str) -> list[dict]:
        return self._all(
            "SELECT * FROM calendar WHERE event_date >= ? AND event_date <= ? ORDER BY event_date, title",
            (first, last),
        )

    # ---------------------------------------------------------------- stories
    def open_stories(self, since: datetime, limit: int = 25) -> list[dict]:
        return self._all(
            """SELECT * FROM stories WHERE status = 'open' AND last_updated_utc >= ?
               ORDER BY last_updated_utc DESC LIMIT ?""",
            (iso(since), limit),
        )

    def tracked_before(self, cutoff: datetime, since: datetime, limit: int = 25) -> list[dict]:
        """Open stories as they stood before `cutoff` (the start of today), so reruns don't count as coverage."""
        return self._all(
            """SELECT s.id, s.title, s.category, u.text AS last_state, u.created_utc AS last_updated_utc
               FROM stories s JOIN story_updates u ON u.story_id = s.id
               WHERE s.status = 'open'
                 AND u.created_utc = (SELECT MAX(created_utc) FROM story_updates
                                      WHERE story_id = s.id AND created_utc < ?)
                 AND u.created_utc >= ?
               ORDER BY u.created_utc DESC LIMIT ?""",
            (iso(cutoff), iso(since), limit),
        )

    def forget_same_day(self, day_start: datetime, run_id: str) -> None:
        """A rerun replaces the day's earlier briefs in story memory."""
        with self.lock:
            self.db.execute("DELETE FROM story_updates WHERE created_utc >= ? AND run_id != ?", (iso(day_start), run_id))
            self.db.execute("DELETE FROM stories WHERE id NOT IN (SELECT DISTINCT story_id FROM story_updates)")
            self.db.execute(
                """UPDATE stories SET
                     last_state = (SELECT text FROM story_updates u WHERE u.story_id = stories.id
                                   ORDER BY created_utc DESC LIMIT 1),
                     last_updated_utc = (SELECT created_utc FROM story_updates u WHERE u.story_id = stories.id
                                         ORDER BY created_utc DESC LIMIT 1),
                     times_reported = (SELECT COUNT(*) FROM story_updates u WHERE u.story_id = stories.id)"""
            )
            self.db.commit()

    def story(self, story_id: str) -> dict | None:
        rows = self._all("SELECT * FROM stories WHERE id = ?", (story_id,))
        return rows[0] if rows else None

    def record_story(self, story_id: str, title: str, category: str, state: str, run_id: str, claim_ids: list[str]) -> None:
        now = iso(utcnow())
        with self.lock:
            exists = self.db.execute("SELECT id FROM stories WHERE id = ?", (story_id,)).fetchone()
            if exists:
                self.db.execute(
                    """UPDATE stories SET title = ?, category = ?, last_updated_utc = ?, last_state = ?,
                       times_reported = times_reported + 1, status = 'open' WHERE id = ?""",
                    (title, category, now, state, story_id),
                )
            else:
                self.db.execute(
                    """INSERT INTO stories (id, title, category, first_seen_utc, last_updated_utc, last_state,
                       status, times_reported) VALUES (?, ?, ?, ?, ?, ?, 'open', 1)""",
                    (story_id, title, category, now, now, state),
                )
            self.db.execute(
                "INSERT INTO story_updates VALUES (?, ?, ?, ?, ?)",
                (story_id, run_id, now, state, json.dumps(claim_ids)),
            )
            self.db.commit()

    def close_stale_stories(self, before: datetime) -> None:
        self._exec("UPDATE stories SET status = 'closed' WHERE status = 'open' AND last_updated_utc < ?", (iso(before),))

    # ---------------------------------------------------------------- runs, claims, usage
    def start_run(self, run_id: str, window_start: datetime, window_end: datetime) -> None:
        self._exec(
            "INSERT INTO runs (id, started_utc, window_start_utc, window_end_utc, status) VALUES (?, ?, ?, ?, 'running')",
            (run_id, iso(utcnow()), iso(window_start), iso(window_end)),
        )

    def finish_run(self, run_id: str, status: str, cost: float, brief_path: str | None, summary: str | None, stats: dict) -> None:
        self._exec(
            """UPDATE runs SET finished_utc = ?, status = ?, cost_usd = ?, brief_path = ?, summary = ?, stats = ?
               WHERE id = ?""",
            (iso(utcnow()), status, cost, brief_path, summary, json.dumps(stats), run_id),
        )

    def save_claims(self, run_id: str, claims: list[dict]) -> None:
        with self.lock:
            for c in claims:
                self.db.execute(
                    """INSERT OR REPLACE INTO claims (id, run_id, story_key, text, verdict, status, item_ids, quotes, note)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        c["id"], run_id, c["story_key"], c["text"], c["verdict"], c.get("status"),
                        json.dumps(c["item_ids"]), json.dumps(c.get("quotes", [])), c.get("note", ""),
                    ),
                )
            self.db.commit()

    def save_usage(self, run_id: str, rows: list[dict]) -> None:
        with self.lock:
            for r in rows:
                self.db.execute(
                    "INSERT INTO usage VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (run_id, r["stage"], r["model"], r["calls"], r["input"], r["output"], r["cache_read"], r["cache_write"], r["cost"]),
                )
            self.db.commit()

    def recent_runs(self, limit: int = 10) -> list[dict]:
        return self._all("SELECT * FROM runs ORDER BY started_utc DESC LIMIT ?", (limit,))
