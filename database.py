"""
🗄️  Giveaway Bot V2 — Database Layer
Tables: giveaways, entries, referrals, banned_users
"""

import sqlite3
from config import DB_PATH


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    with get_conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS giveaways (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            prize           TEXT    NOT NULL,
            repo_url        TEXT    NOT NULL,
            winners_count   INTEGER NOT NULL DEFAULT 1,
            min_threshold   INTEGER NOT NULL DEFAULT 0,
            secret_prize    TEXT,
            tutorial_link   TEXT,
            status          TEXT    NOT NULL DEFAULT 'active',
            created_at      TEXT    NOT NULL,
            end_time        TEXT    NOT NULL
        );

        CREATE TABLE IF NOT EXISTS entries (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            giveaway_id      INTEGER NOT NULL,
            user_id          INTEGER NOT NULL,
            telegram_username TEXT,
            github_username  TEXT    NOT NULL,
            photo_file_id    TEXT    NOT NULL,
            status           TEXT    NOT NULL DEFAULT 'pending',
            priority_boost   INTEGER NOT NULL DEFAULT 0,
            is_winner        INTEGER NOT NULL DEFAULT 0,
            submitted_at     TEXT    NOT NULL,
            UNIQUE(giveaway_id, user_id),
            UNIQUE(giveaway_id, github_username),
            FOREIGN KEY(giveaway_id) REFERENCES giveaways(id)
        );

        CREATE TABLE IF NOT EXISTS referrals (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            giveaway_id  INTEGER NOT NULL,
            referrer_id  INTEGER NOT NULL,
            referred_id  INTEGER NOT NULL,
            created_at   TEXT    NOT NULL,
            UNIQUE(giveaway_id, referred_id),
            FOREIGN KEY(giveaway_id) REFERENCES giveaways(id)
        );

        CREATE TABLE IF NOT EXISTS banned_users (
            user_id    INTEGER PRIMARY KEY,
            reason     TEXT,
            banned_at  TEXT NOT NULL
        );
        """)
        try:
            c.execute("ALTER TABLE entries ADD COLUMN is_winner INTEGER NOT NULL DEFAULT 0")
        except sqlite3.OperationalError:
            pass
        try:
            c.execute("ALTER TABLE giveaways ADD COLUMN tutorial_link TEXT")
        except sqlite3.OperationalError:
            pass


# ── Giveaways ────────────────────────────────

def create_giveaway(prize, repo_url, winners_count, min_threshold,
                    secret_prize, tutorial_link, created_at, end_time) -> int:
    with get_conn() as c:
        cursor = c.execute(
            """INSERT INTO giveaways 
               (prize, repo_url, winners_count, min_threshold, secret_prize, tutorial_link, created_at, end_time)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (prize, repo_url, winners_count, min_threshold, secret_prize, tutorial_link, created_at, end_time)
        )
        return cursor.lastrowid


def get_active_giveaway():
    with get_conn() as c:
        return c.execute(
            "SELECT * FROM giveaways WHERE status = 'active' ORDER BY id DESC LIMIT 1"
        ).fetchone()


def get_latest_giveaway():
    """Returns the most recent giveaway (any status)"""
    with get_conn() as c:
        return c.execute(
            "SELECT * FROM giveaways ORDER BY id DESC LIMIT 1"
        ).fetchone()

def update_giveaway_field(gid: int, field: str, value: str):
    allowed_fields = {"prize", "repo_url", "tutorial_link", "secret_prize"}
    if field not in allowed_fields:
        return
    with get_conn() as c:
        c.execute(f"UPDATE giveaways SET {field} = ? WHERE id = ?", (value, gid))


def get_giveaway(gid: int):
    with get_conn() as c:
        return c.execute("SELECT * FROM giveaways WHERE id = ?", (gid,)).fetchone()


def set_giveaway_status(gid: int, status: str):
    with get_conn() as c:
        c.execute("UPDATE giveaways SET status = ? WHERE id = ?", (status, gid))


def delete_campaign(gid: int):
    with get_conn() as c:
        c.execute("DELETE FROM referrals WHERE giveaway_id = ?", (gid,))
        c.execute("DELETE FROM entries WHERE giveaway_id = ?", (gid,))
        c.execute("DELETE FROM giveaways WHERE id = ?", (gid,))


# ── Entries ──────────────────────────────────

def add_entry(giveaway_id, user_id, telegram_username,
              github_username, photo_file_id, submitted_at) -> bool:
    try:
        with get_conn() as c:
            c.execute(
                "INSERT INTO entries "
                "(giveaway_id, user_id, telegram_username, github_username, photo_file_id, submitted_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (giveaway_id, user_id, telegram_username,
                 github_username, photo_file_id, submitted_at)
            )
        return True
    except sqlite3.IntegrityError:
        return False


def get_entry_by_user(gid: int, user_id: int):
    with get_conn() as c:
        return c.execute(
            "SELECT * FROM entries WHERE giveaway_id = ? AND user_id = ?",
            (gid, user_id)
        ).fetchone()


def get_entry_by_id(eid: int):
    with get_conn() as c:
        return c.execute("SELECT * FROM entries WHERE id = ?", (eid,)).fetchone()


def update_entry_status(eid: int, status: str):
    with get_conn() as c:
        c.execute("UPDATE entries SET status = ? WHERE id = ?", (status, eid))


def set_priority_boost(gid: int, user_id: int, boost: int):
    with get_conn() as c:
        c.execute(
            "UPDATE entries SET priority_boost = ? WHERE giveaway_id = ? AND user_id = ?",
            (boost, gid, user_id)
        )


def get_approved_entries(gid: int):
    with get_conn() as c:
        return c.execute(
            "SELECT * FROM entries WHERE giveaway_id = ? AND status = 'approved'", (gid,)
        ).fetchall()


def get_all_entries(gid: int):
    with get_conn() as c:
        return c.execute(
            "SELECT * FROM entries WHERE giveaway_id = ?", (gid,)
        ).fetchall()


def count_by_status(gid: int, status: str) -> int:
    with get_conn() as c:
        r = c.execute(
            "SELECT COUNT(*) FROM entries WHERE giveaway_id = ? AND status = ?",
            (gid, status)
        ).fetchone()
        return r[0] if r else 0


def count_approved(gid: int) -> int:
    return count_by_status(gid, "approved")


def set_winner(gid: int, user_id: int):
    with get_conn() as c:
        c.execute(
            "UPDATE entries SET is_winner = 1 WHERE giveaway_id = ? AND user_id = ?",
            (gid, user_id)
        )


def get_winners(gid: int):
    with get_conn() as c:
        return c.execute(
            "SELECT * FROM entries WHERE giveaway_id = ? AND is_winner = 1",
            (gid,)
        ).fetchall()


# ── Referrals ────────────────────────────────

def add_referral(gid: int, referrer_id: int, referred_id: int, created_at: str) -> bool:
    if referrer_id == referred_id:
        return False
    try:
        with get_conn() as c:
            c.execute(
                "INSERT INTO referrals (giveaway_id, referrer_id, referred_id, created_at) "
                "VALUES (?, ?, ?, ?)",
                (gid, referrer_id, referred_id, created_at)
            )
        return True
    except sqlite3.IntegrityError:
        return False

def get_referrer(gid: int, referred_id: int):
    with get_conn() as c:
        r = c.execute(
            "SELECT referrer_id FROM referrals WHERE giveaway_id = ? AND referred_id = ?",
            (gid, referred_id)
        ).fetchone()
        return r["referrer_id"] if r else None

def count_referrals(gid: int, referrer_id: int) -> int:
    with get_conn() as c:
        r = c.execute(
            """SELECT COUNT(*) FROM referrals r
               JOIN entries e ON r.referred_id = e.user_id AND r.giveaway_id = e.giveaway_id
               WHERE r.giveaway_id = ? AND r.referrer_id = ? AND e.status = 'approved'""",
            (gid, referrer_id)
        ).fetchone()
        return r[0] if r else 0


def get_referral_leaderboard(gid: int, limit: int = 10):
    with get_conn() as c:
        return c.execute(
            """SELECT r.referrer_id,
                      COUNT(*) as ref_count,
                      (SELECT telegram_username FROM entries
                       WHERE giveaway_id = r.giveaway_id AND user_id = r.referrer_id) as uname
               FROM referrals r
               JOIN entries e ON r.referred_id = e.user_id AND r.giveaway_id = e.giveaway_id
               WHERE r.giveaway_id = ? AND e.status = 'approved'
               GROUP BY r.referrer_id
               ORDER BY ref_count DESC
               LIMIT ?""",
            (gid, limit)
        ).fetchall()


def get_secret_prize_eligible(gid: int, threshold: int):
    """Users with referrals >= threshold"""
    with get_conn() as c:
        return c.execute(
            """SELECT r.referrer_id, COUNT(*) as ref_count
               FROM referrals r
               JOIN entries e ON r.referred_id = e.user_id AND r.giveaway_id = e.giveaway_id
               WHERE r.giveaway_id = ? AND e.status = 'approved'
               GROUP BY r.referrer_id
               HAVING ref_count >= ?""",
            (gid, threshold)
        ).fetchall()


# ── Banned Users ─────────────────────────────

def ban_user(user_id: int, reason: str, banned_at: str):
    with get_conn() as c:
        c.execute(
            "INSERT OR REPLACE INTO banned_users (user_id, reason, banned_at) VALUES (?, ?, ?)",
            (user_id, reason, banned_at)
        )


def unban_user(user_id: int):
    with get_conn() as c:
        c.execute("DELETE FROM banned_users WHERE user_id = ?", (user_id,))


def is_banned(user_id: int) -> bool:
    with get_conn() as c:
        r = c.execute(
            "SELECT 1 FROM banned_users WHERE user_id = ?", (user_id,)
        ).fetchone()
        return r is not None


def get_all_banned():
    with get_conn() as c:
        return c.execute("SELECT * FROM banned_users").fetchall()


# ── Analytics ────────────────────────────────

def get_analytics(gid: int) -> dict:
    approved  = count_by_status(gid, "approved")
    pending   = count_by_status(gid, "pending")
    rejected  = count_by_status(gid, "rejected")
    with get_conn() as c:
        ref_total = c.execute(
            """SELECT COUNT(*) FROM referrals r
               JOIN entries e ON r.referred_id = e.user_id AND r.giveaway_id = e.giveaway_id
               WHERE r.giveaway_id = ? AND e.status = 'approved'""",
            (gid,)
        ).fetchone()[0]
    return {
        "approved":  approved,
        "pending":   pending,
        "rejected":  rejected,
        "total":     approved + pending + rejected,
        "referrals": ref_total,
    }
