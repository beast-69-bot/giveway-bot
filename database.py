import sqlite3
from config import DB_PATH


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Create tables if they don't exist."""
    with get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS giveaways (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                prize         TEXT    NOT NULL,
                repo_url      TEXT    NOT NULL,
                winners_count INTEGER NOT NULL DEFAULT 1,
                status        TEXT    NOT NULL DEFAULT 'active',  -- active | ended | cancelled
                created_at    TEXT    NOT NULL,
                end_time      TEXT    NOT NULL
            );

            CREATE TABLE IF NOT EXISTS entries (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                giveaway_id      INTEGER NOT NULL,
                user_id          INTEGER NOT NULL,
                telegram_username TEXT,
                github_username  TEXT    NOT NULL,
                photo_file_id    TEXT    NOT NULL,
                status           TEXT    NOT NULL DEFAULT 'pending',  -- pending | approved | rejected
                submitted_at     TEXT    NOT NULL,
                UNIQUE(giveaway_id, user_id),
                UNIQUE(giveaway_id, github_username),
                FOREIGN KEY(giveaway_id) REFERENCES giveaways(id)
            );
        """)


# ── Giveaway helpers ─────────────────────────

def create_giveaway(prize, repo_url, winners_count, created_at, end_time) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO giveaways (prize, repo_url, winners_count, created_at, end_time) "
            "VALUES (?, ?, ?, ?, ?)",
            (prize, repo_url, winners_count, created_at, end_time)
        )
        return cur.lastrowid


def get_active_giveaway():
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM giveaways WHERE status = 'active' ORDER BY id DESC LIMIT 1"
        ).fetchone()


def get_giveaway(giveaway_id: int):
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM giveaways WHERE id = ?", (giveaway_id,)
        ).fetchone()


def end_giveaway(giveaway_id: int):
    with get_conn() as conn:
        conn.execute(
            "UPDATE giveaways SET status = 'ended' WHERE id = ?", (giveaway_id,)
        )


def cancel_giveaway(giveaway_id: int):
    with get_conn() as conn:
        conn.execute(
            "UPDATE giveaways SET status = 'cancelled' WHERE id = ?", (giveaway_id,)
        )


# ── Entry helpers ────────────────────────────

def add_entry(giveaway_id, user_id, telegram_username, github_username, photo_file_id, submitted_at) -> bool:
    """Returns True if inserted, False if duplicate."""
    try:
        with get_conn() as conn:
            conn.execute(
                "INSERT INTO entries "
                "(giveaway_id, user_id, telegram_username, github_username, photo_file_id, submitted_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (giveaway_id, user_id, telegram_username, github_username, photo_file_id, submitted_at)
            )
        return True
    except sqlite3.IntegrityError:
        return False


def get_entry_by_user(giveaway_id: int, user_id: int):
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM entries WHERE giveaway_id = ? AND user_id = ?",
            (giveaway_id, user_id)
        ).fetchone()


def get_entry_by_id(entry_id: int):
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM entries WHERE id = ?", (entry_id,)
        ).fetchone()


def update_entry_status(entry_id: int, status: str):
    with get_conn() as conn:
        conn.execute(
            "UPDATE entries SET status = ? WHERE id = ?", (status, entry_id)
        )


def get_approved_entries(giveaway_id: int):
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM entries WHERE giveaway_id = ? AND status = 'approved'",
            (giveaway_id,)
        ).fetchall()


def get_all_entries(giveaway_id: int):
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM entries WHERE giveaway_id = ?", (giveaway_id,)
        ).fetchall()


def count_approved(giveaway_id: int) -> int:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM entries WHERE giveaway_id = ? AND status = 'approved'",
            (giveaway_id,)
        ).fetchone()
        return row["cnt"] if row else 0
