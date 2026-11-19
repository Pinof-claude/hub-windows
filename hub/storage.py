"""Stockage local SQLite.

Les classes *Repo sont la seule couche qui touche la base : une future
synchro cloud pourra fournir une autre implémentation de la même interface.
"""
from __future__ import annotations

import os
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS folders (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    parent_id INTEGER REFERENCES folders(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS notes (
    id INTEGER PRIMARY KEY,
    folder_id INTEGER REFERENCES folders(id) ON DELETE SET NULL,
    title TEXT NOT NULL DEFAULT '',
    html TEXT NOT NULL DEFAULT '',
    plain TEXT NOT NULL DEFAULT '',
    tags TEXT NOT NULL DEFAULT '',
    pinned INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS transcripts (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL DEFAULT '',
    audio_path TEXT NOT NULL DEFAULT '',
    text TEXT NOT NULL DEFAULT '',
    language TEXT NOT NULL DEFAULT '',
    duration REAL NOT NULL DEFAULT 0,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
"""


def data_dir() -> Path:
    base = os.environ.get("HUB_DATA_DIR") or os.path.join(
        os.environ.get("APPDATA") or os.path.expanduser("~"), "HubWindows"
    )
    p = Path(base)
    p.mkdir(parents=True, exist_ok=True)
    return p


def connect(path: Path | str | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path or data_dir() / "hub.db"))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.executescript(SCHEMA)
    return conn


def norm_tags(tags: str) -> str:
    seen: list[str] = []
    for t in tags.replace(";", ",").split(","):
        t = t.strip().lower()
        if t and t not in seen:
            seen.append(t)
    return ", ".join(seen)


@dataclass
class Note:
    id: int
    folder_id: int | None
    title: str
    html: str
    plain: str
    tags: str
    pinned: bool
    created_at: float
    updated_at: float


class NotesRepo:
    def __init__(self, conn: sqlite3.Connection):
        self.c = conn

    # Dossiers
    def folders(self) -> list[sqlite3.Row]:
        return self.c.execute("SELECT * FROM folders ORDER BY name COLLATE NOCASE").fetchall()

    def add_folder(self, name: str, parent_id: int | None = None) -> int:
        cur = self.c.execute("INSERT INTO folders(name, parent_id) VALUES (?, ?)", (name, parent_id))
        self.c.commit()
        return cur.lastrowid

    def rename_folder(self, fid: int, name: str) -> None:
        self.c.execute("UPDATE folders SET name=? WHERE id=?", (name, fid))
        self.c.commit()

    def delete_folder(self, fid: int) -> None:
        self.c.execute("DELETE FROM folders WHERE id=?", (fid,))
        self.c.commit()

    # Notes
    def create(self, folder_id: int | None = None, title: str = "Sans titre") -> int:
        now = time.time()
        cur = self.c.execute(
            "INSERT INTO notes(folder_id, title, created_at, updated_at) VALUES (?,?,?,?)",
            (folder_id, title, now, now),
        )
        self.c.commit()
        return cur.lastrowid

    def get(self, nid: int) -> Note | None:
        r = self.c.execute("SELECT * FROM notes WHERE id=?", (nid,)).fetchone()
        return Note(**{**dict(r), "pinned": bool(r["pinned"])}) if r else None

    def save(self, nid: int, title: str, html: str, plain: str) -> None:
        self.c.execute(
            "UPDATE notes SET title=?, html=?, plain=?, updated_at=? WHERE id=?",
            (title, html, plain, time.time(), nid),
        )
        self.c.commit()

    def set_tags(self, nid: int, tags: str) -> None:
        self.c.execute("UPDATE notes SET tags=? WHERE id=?", (norm_tags(tags), nid))
        self.c.commit()

    def set_pinned(self, nid: int, pinned: bool) -> None:
        self.c.execute("UPDATE notes SET pinned=? WHERE id=?", (int(pinned), nid))
        self.c.commit()

    def move(self, nid: int, folder_id: int | None) -> None:
        self.c.execute("UPDATE notes SET folder_id=? WHERE id=?", (folder_id, nid))
        self.c.commit()

    def delete(self, nid: int) -> None:
        self.c.execute("DELETE FROM notes WHERE id=?", (nid,))
        self.c.commit()

    def all_tags(self) -> list[str]:
        tags: set[str] = set()
        for (t,) in self.c.execute("SELECT tags FROM notes WHERE tags != ''"):
            tags.update(x.strip() for x in t.split(",") if x.strip())
        return sorted(tags)

    def search(self, query: str = "", folder_id: int | None = None, all_folders: bool = True,
               tag: str | None = None, sort: str = "updated") -> list[sqlite3.Row]:
        sql = "SELECT id, title, tags, pinned, updated_at, folder_id FROM notes WHERE 1=1"
        args: list = []
        if not all_folders:
            if folder_id is None:
                sql += " AND folder_id IS NULL"
            else:
                sql += " AND folder_id=?"
                args.append(folder_id)
        for word in query.split():
            sql += " AND (title LIKE ? OR plain LIKE ? OR tags LIKE ?)"
            args += [f"%{word}%"] * 3
        if tag:
            sql += " AND (', ' || tags || ',') LIKE ?"
            args.append(f"%, {tag},%")
        order = {"updated": "updated_at DESC", "created": "created_at DESC",
                 "title": "title COLLATE NOCASE"}.get(sort, "updated_at DESC")
        sql += f" ORDER BY pinned DESC, {order}"
        return self.c.execute(sql, args).fetchall()


class TranscriptsRepo:
    def __init__(self, conn: sqlite3.Connection):
        self.c = conn

    def create(self, title: str, audio_path: str, duration: float) -> int:
        now = time.time()
        cur = self.c.execute(
            "INSERT INTO transcripts(title, audio_path, duration, created_at, updated_at)"
            " VALUES (?,?,?,?,?)",
            (title, audio_path, duration, now, now),
        )
        self.c.commit()
        return cur.lastrowid

    def list(self, query: str = "") -> list[sqlite3.Row]:
        q = f"%{query}%"
        return self.c.execute(
            "SELECT * FROM transcripts WHERE title LIKE ? OR text LIKE ? ORDER BY created_at DESC",
            (q, q),
        ).fetchall()

    def get(self, tid: int) -> sqlite3.Row | None:
        return self.c.execute("SELECT * FROM transcripts WHERE id=?", (tid,)).fetchone()

    def update(self, tid: int, **fields) -> None:
        allowed = {"title", "text", "language"}
        keys = [k for k in fields if k in allowed]
        if not keys:
            return
        sets = ", ".join(f"{k}=?" for k in keys)
        self.c.execute(
            f"UPDATE transcripts SET {sets}, updated_at=? WHERE id=?",
            [fields[k] for k in keys] + [time.time(), tid],
        )
        self.c.commit()

    def delete(self, tid: int) -> None:
        r = self.get(tid)
        if r and r["audio_path"]:
            try:
                Path(r["audio_path"]).unlink(missing_ok=True)
            except OSError:
                pass
        self.c.execute("DELETE FROM transcripts WHERE id=?", (tid,))
        self.c.commit()
