"""
💠 Telegram Giveaway Bot V2 — Enterprise Edition
=================================================
Features:
  • Premium MarkdownV2 UI + Button-driven flow
  • /admin Dashboard (single control panel)
  • Interactive giveaway creation with presets, preview, confirmation
  • Participation Threshold (min goal) + auto-cancel
  • Duration up to 30 days
  • Referral ecosystem (unique links, tiers, leaderboard)
  • Live analytics
  • Broadcast to all participants
  • Ban / Unban system
  • CSV export
  • Auto winner announcement
  • Anti-cheat (duplicate GitHub, self-referral guard)
  • Auto-expiry
"""

import csv
import io
import secrets
import logging
import asyncio
from datetime import datetime, timedelta

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    BotCommand,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    filters,
    JobQueue,
)
from telegram.constants import ParseMode

import database as db
from config import (
    BOT_TOKEN, ADMIN_ID, DURATION_PRESETS,
    REFERRAL_PRIORITY_THRESHOLD, REFERRAL_SECRET_THRESHOLD,
)

logging.basicConfig(format="%(asctime)s | %(levelname)s | %(message)s", level=logging.INFO)
log = logging.getLogger(__name__)

# ── Conversation States ──────────────────────
(
    CRE_PRIZE,
    CRE_REPO,
    CRE_WINNERS,
    CRE_DURATION,
    CRE_CUSTOM_DURATION,
    CRE_THRESHOLD,
    CRE_SECRET,
    CRE_PREVIEW,
) = range(8)

BROADCAST_MSG  = 20
BAN_USER_INPUT = 21

# ── In-memory ────────────────────────────────
# user_id → {"giveaway_id": int, "step": str}
pending_proofs: dict = {}


# ══════════════════════════════════════════════
#  🛠️  HELPERS
# ══════════════════════════════════════════════

def esc(text) -> str:
    """Escape a string for MarkdownV2 (outside of code/links)."""
    special = r'\_*[]()~`>#+-=|{}.!'
    return ''.join(f'\\{c}' if c in special else c for c in str(text))


def code_esc(text) -> str:
    """Escape for inside backticks (MarkdownV2)."""
    return str(text).replace('\\', '\\\\').replace('`', '\\`')


def is_admin(uid: int) -> bool:
    return uid == ADMIN_ID


def utcnow() -> datetime:
    return datetime.utcnow()


def fmt_dt(dt: datetime) -> str:
    return dt.strftime("%d %b %Y %H:%M UTC")


def user_mention(user) -> str:
    name = esc(user.full_name or "Unknown")
    return f"[{name}](tg://user?id={user.id})"


def time_left(end_time_iso: str) -> str:
    delta = datetime.fromisoformat(end_time_iso) - utcnow()
    if delta.total_seconds() <= 0:
        return "Expired"
    days    = delta.days
    hours   = delta.seconds // 3600
    minutes = (delta.seconds % 3600) // 60
    parts = []
    if days:    parts.append(f"{days}d")
    if hours:   parts.append(f"{hours}h")
    if minutes: parts.append(f"{minutes}m")
    return " ".join(parts) or "< 1m"


# ══════════════════════════════════════════════
#  📊  KEYBOARDS
# ══════════════════════════════════════════════

def kb_admin_dashboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ New Campaign",      callback_data="admin:new"),
         InlineKeyboardButton("✏️ Edit Campaign",     callback_data="admin:edit")],
        [InlineKeyboardButton("📊 Live Analytics",   callback_data="admin:analytics"),
         InlineKeyboardButton("👥 Participants",     callback_data="admin:participants")],
        [InlineKeyboardButton("📣 Broadcast",        callback_data="admin:broadcast"),
         InlineKeyboardButton("🏆 Leaderboard",      callback_data="admin:leaderboard")],
        [InlineKeyboardButton("🎰 Draw Winners",     callback_data="admin:draw"),
         InlineKeyboardButton("📥 Export CSV",       callback_data="admin:export")],
        [InlineKeyboardButton("🚫 Ban User",         callback_data="admin:ban"),
         InlineKeyboardButton("✅ Unban User",       callback_data="admin:unban")],
        [InlineKeyboardButton("❌ Cancel Active",    callback_data="admin:cancel"),
         InlineKeyboardButton("🗑 Delete Campaign",  callback_data="admin:delete_prompt")],
    ])


def kb_duration_presets() -> InlineKeyboardMarkup:
    rows = []
    keys = list(DURATION_PRESETS.keys())
    for i in range(0, len(keys), 2):
        row = [InlineKeyboardButton(keys[i], callback_data=f"dur:{keys[i]}")]
        if i + 1 < len(keys):
            row.append(InlineKeyboardButton(keys[i+1], callback_data=f"dur:{keys[i+1]}"))
        rows.append(row)
    rows.append([InlineKeyboardButton("✏️ Custom (type minutes)", callback_data="dur:custom")])
    return InlineKeyboardMarkup(rows)


def kb_yes_no(yes_cb: str, no_cb: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Yes", callback_data=yes_cb),
        InlineKeyboardButton("❌ No",  callback_data=no_cb),
    ]])


def kb_approve_reject(entry_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Approve", callback_data=f"approve:{entry_id}"),
        InlineKeyboardButton("❌ Reject",  callback_data=f"reject:{entry_id}"),
    ]])


def kb_join_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎯 Join Campaign",       callback_data="user:join")],
        [InlineKeyboardButton("🏆 Leaderboard",         callback_data="user:leaderboard")],
        [InlineKeyboardButton("📊 My Stats",            callback_data="user:mystats")],
    ])


# ══════════════════════════════════════════════
#  💠  /start
# ══════════════════════════════════════════════

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = update.message.text or ""

    # Handle referral deep-link: /start ref_12345
    if ctx.args:
        arg = ctx.args[0]
        if arg.startswith("ref_"):
            try:
                referrer_id = int(arg[4:])
                active = db.get_active_giveaway()
                if active and referrer_id != user.id:
                    added = db.add_referral(
                        active["id"], referrer_id, user.id, utcnow().isoformat()
                    )
                    if added:
                        try:
                            await ctx.bot.send_message(
                                chat_id=referrer_id,
                                text=(
                                    f"👀 *Referral Link Clicked\\!*\n\n"
                                    f"👤 {esc(user.full_name)} ne tera link use kiya hai\\.\n"
                                    f"_Agar wo successfully campaign join karte hain, toh tera referral count badh jayega\\._"
                                ),
                                parse_mode=ParseMode.MARKDOWN_V2,
                            )
                        except Exception:
                            pass
            except ValueError:
                pass

    active = db.get_active_giveaway()
    status_line = (
        f"🟢 *Active Campaign:* {esc(active['prize'])} \\| "
        f"⏳ {esc(time_left(active['end_time']))} left"
        if active else "⚪ *No active campaign right now\\.*"
    )

    msg = (
        f"💠 *Welcome to Campaign Bot V2*\n\n"
        f"{status_line}\n\n"
        f"Use the buttons below to participate or check stats\\."
    )
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN_V2,
                                    reply_markup=kb_join_menu())


# ══════════════════════════════════════════════
#  ⚙️  /admin — Dashboard
# ══════════════════════════════════════════════

async def cmd_admin(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Unauthorized\\.", parse_mode=ParseMode.MARKDOWN_V2)
        return

    active = db.get_active_giveaway()
    if active:
        stats = db.get_analytics(active["id"])
        status = (
            f"📌 *Active:* Campaign \\#{esc(active['id'])} — {esc(active['prize'])}\n"
            f"✅ Approved: `{stats['approved']}` \\| "
            f"⏳ Pending: `{stats['pending']}` \\| "
            f"❌ Rejected: `{stats['rejected']}`\n"
            f"🔗 Referrals: `{stats['referrals']}` \\| "
            f"⏱ Left: `{code_esc(time_left(active['end_time']))}`"
        )
    else:
        status = "⚪ *No active campaign\\.*"

    msg = (
        f"⚙️ *Admin Control Center*\n\n"
        f"{status}\n\n"
        f"_Select an action below:_"
    )
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN_V2,
                                    reply_markup=kb_admin_dashboard())


# ══════════════════════════════════════════════
#  Admin Dashboard Callbacks
# ══════════════════════════════════════════════

async def admin_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if not is_admin(query.from_user.id):
        await query.answer("⛔ Unauthorized", show_alert=True)
        return

    action = query.data.split(":")[1]

    # ── Analytics ──
    if action == "analytics":
        active = db.get_active_giveaway()
        if not active:
            await query.answer("No active giveaway.", show_alert=True)
            return
        stats = db.get_analytics(active["id"])
        threshold = active["min_threshold"]
        threshold_line = (
            f"🎯 Min Threshold: `{threshold}` \\| "
            + ("✅ Met\\!" if stats['approved'] >= threshold else f"⚠️ Need {threshold - stats['approved']} more")
        ) if threshold > 0 else ""

        msg = (
            f"📊 *Live Analytics — Campaign \\#{esc(active['id'])}*\n\n"
            f"🎁 Prize: {esc(active['prize'])}\n"
            f"🔗 Repo: {esc(active['repo_url'])}\n"
            f"⏳ Time Left: `{code_esc(time_left(active['end_time']))}`\n\n"
            f"✅ Approved: `{stats['approved']}`\n"
            f"⏳ Pending: `{stats['pending']}`\n"
            f"❌ Rejected: `{stats['rejected']}`\n"
            f"📦 Total Entries: `{stats['total']}`\n"
            f"🔗 Referrals Given: `{stats['referrals']}`\n"
            + (f"\n{threshold_line}" if threshold_line else "")
        )
        await query.edit_message_text(msg, parse_mode=ParseMode.MARKDOWN_V2,
                                      reply_markup=InlineKeyboardMarkup([[
                                          InlineKeyboardButton("🔙 Back", callback_data="admin:back")
                                      ]]))

    # ── Participants ──
    elif action == "participants":
        active = db.get_active_giveaway()
        if not active:
            await query.answer("No active giveaway.", show_alert=True)
            return
        entries = db.get_all_entries(active["id"])
        if not entries:
            await query.answer("Koi entry nahi abhi tak.", show_alert=True)
            return
        lines = [f"👥 *Participants — Campaign \\#{esc(active['id'])}*\n"]
        icons = {"pending": "⏳", "approved": "✅", "rejected": "❌"}
        for e in entries:
            tg = f"@{esc(e['telegram_username'])}" if e["telegram_username"] else f"ID:{esc(e['user_id'])}"
            ref_c = db.count_referrals(active["id"], e["user_id"])
            boost = "⚡" if e["priority_boost"] else ""
            lines.append(f"{icons.get(e['status'], '?')} {tg} \\| GH: `{code_esc(e['github_username'])}` {boost} refs:{ref_c}")
        await query.edit_message_text(
            "\n".join(lines),
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="admin:back")]])
        )

    # ── Leaderboard ──
    elif action == "leaderboard":
        active = db.get_active_giveaway()
        if not active:
            await query.answer("No active giveaway.", show_alert=True)
            return
        board = db.get_referral_leaderboard(active["id"])
        if not board:
            await query.answer("Koi referral nahi abhi tak.", show_alert=True)
            return
        lines = [f"🏆 *Referral Leaderboard — Campaign \\#{esc(active['id'])}*\n"]
        medals = ["🥇", "🥈", "🥉"]
        for i, row in enumerate(board):
            medal = medals[i] if i < 3 else f"{i+1}\\."
            uname = f"@{esc(row['uname'])}" if row["uname"] else f"ID:{esc(row['referrer_id'])}"
            secret = " 🏅" if row["ref_count"] >= REFERRAL_SECRET_THRESHOLD else ""
            boost  = " ⚡" if row["ref_count"] >= REFERRAL_PRIORITY_THRESHOLD else ""
            lines.append(f"{medal} {uname} — `{row['ref_count']}` referrals{boost}{secret}")
        lines.append(f"\n⚡ \\= Priority Boost \\| 🏅 \\= Secret Prize eligible")
        await query.edit_message_text(
            "\n".join(lines),
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="admin:back")]])
        )

    # ── Draw ──
    elif action == "draw":
        active = db.get_active_giveaway()
        if not active:
            await query.answer("No active campaign.", show_alert=True)
            return
        await query.edit_message_text(
            "🎰 *Draw karna chahte ho?*\n\nYe action campaign end kar dega\\.",
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=kb_yes_no("draw:confirm", "admin:back")
        )

    # ── Cancel ──
    elif action == "cancel":
        active = db.get_active_giveaway()
        if not active:
            await query.answer("No active campaign.", show_alert=True)
            return
        await query.edit_message_text(
            f"❌ *Campaign \\#{esc(active['id'])} cancel karna chahte ho?*",
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=kb_yes_no("cancel:confirm", "admin:back")
        )

    # ── Back ──
    elif action == "back":
        ctx.user_data.pop("awaiting_broadcast", None)
        ctx.user_data.pop("awaiting_ban", None)
        ctx.user_data.pop("awaiting_unban", None)
        ctx.user_data.pop("awaiting_edit", None)
        ctx.user_data.pop("awaiting_delete", None)
        active = db.get_active_giveaway()
        if active:
            stats = db.get_analytics(active["id"])
            status = (
                f"📌 *Active:* Campaign \\#{esc(active['id'])} — {esc(active['prize'])}\n"
                f"✅ `{stats['approved']}` \\| ⏳ `{stats['pending']}` \\| ❌ `{stats['rejected']}`"
            )
        else:
            status = "⚪ *No active campaign\\.*"
        await query.edit_message_text(
            f"⚙️ *Admin Control Center*\n\n{status}\n\n_Select an action:_",
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=kb_admin_dashboard()
        )

    # ── Broadcast (initiate) ──
    elif action == "broadcast":
        active = db.get_active_giveaway()
        if not active:
            await query.answer("No active giveaway.", show_alert=True)
            return
        ctx.user_data["broadcast_gid"] = active["id"]
        await query.edit_message_text(
            "📣 *Broadcast Message*\n\nWo message type karo jo saare approved participants ko bhejna hai\\.",
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🚫 Cancel", callback_data="admin:back")]])
        )
        ctx.user_data["awaiting_broadcast"] = True

    # ── Export CSV ──
    elif action == "export":
        active = db.get_active_giveaway()
        if not active:
            await query.answer("No active giveaway.", show_alert=True)
            return
        entries = db.get_all_entries(active["id"])
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["Entry ID", "Telegram ID", "Telegram Username",
                         "GitHub Username", "Status", "Priority Boost", "Submitted At"])
        for e in entries:
            writer.writerow([e["id"], e["user_id"], e["telegram_username"] or "",
                             e["github_username"], e["status"],
                             "Yes" if e["priority_boost"] else "No", e["submitted_at"]])
        output.seek(0)
        await ctx.bot.send_document(
            chat_id=ADMIN_ID,
            document=output.getvalue().encode("utf-8"),
            filename=f"giveaway_{active['id']}_participants.csv",
            caption=f"📥 Giveaway #{active['id']} — Export",
        )
        await query.answer("CSV sent!", show_alert=True)

    # ── Ban (initiate) ──
    elif action == "ban":
        ctx.user_data["awaiting_ban"] = True
        await query.edit_message_text(
            "🚫 *Ban User*\n\nUser ka Telegram ID bhejo \\(reason optional — `ID: reason` format\\)\\.",
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🚫 Cancel", callback_data="admin:back")]])
        )

    # ── Unban (initiate) ──
    elif action == "unban":
        ctx.user_data["awaiting_unban"] = True
        await query.edit_message_text(
            "✅ *Unban User*\n\nUser ka Telegram ID bhejo\\.",
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🚫 Cancel", callback_data="admin:back")]])
        )

    # ── Edit Campaign ──
    elif action == "edit":
        active = db.get_active_giveaway()
        if not active:
            await query.answer("No active campaign to edit.", show_alert=True)
            return
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🎁 Prize", callback_data="admin:edit_prize"),
             InlineKeyboardButton("🔗 Repo", callback_data="admin:edit_repo")],
            [InlineKeyboardButton("📹 Tutorial", callback_data="admin:edit_tut")],
            [InlineKeyboardButton("🔙 Back", callback_data="admin:back")]
        ])
        await query.edit_message_text(
            "✏️ *Edit Active Campaign*\n\nKya update karna chahte ho?",
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=kb
        )

    elif action.startswith("edit_"):
        field = action.split("_")[1]
        field_map = {"prize": "Prize", "repo": "Repo URL", "tut": "Tutorial Link"}
        db_col = {"prize": "prize", "repo": "repo_url", "tut": "tutorial_link"}
        
        ctx.user_data["awaiting_edit"] = db_col[field]
        await query.edit_message_text(
            f"✏️ *Editing {field_map[field]}*\n\nNaya text/link bhejo:",
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🚫 Cancel", callback_data="admin:back")]])
        )

    # ── Delete Campaign ──
    elif action == "delete_prompt":
        ctx.user_data["awaiting_delete"] = True
        await query.edit_message_text(
            "🗑 *Delete Campaign*\n\nKonse Campaign ko Hamesha ke liye Delete karna hai? Uski *ID* bhejo (e.g. 1):",
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🚫 Cancel", callback_data="admin:back")]])
        )

    # ── New giveaway (start conversation) ──
    elif action == "new":
        active = db.get_active_giveaway()
        if active:
            await query.answer(
                f"Pehle active campaign #{active['id']} end karo ya cancel karo.",
                show_alert=True
            )
            return
        await query.edit_message_text(
            "🎁 *New Campaign — Step 1/6*\n\n*Prize ka naam kya hai?*\n_e\\.g\\. ₹500 Amazon Gift Card_",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        ctx.user_data["cre"] = {}
        ctx.user_data["creating_giveaway"] = True


# ══════════════════════════════════════════════
#  Draw / Cancel Confirm Callbacks
# ══════════════════════════════════════════════

async def draw_cancel_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if not is_admin(query.from_user.id):
        return

    action = query.data

    if action == "draw:confirm":
        active = db.get_active_giveaway()
        if not active:
            await query.edit_message_text("No active giveaway.")
            return
        await _do_draw(query, ctx, active)

    elif action == "cancel:confirm":
        active = db.get_active_giveaway()
        if not active:
            await query.edit_message_text("No active campaign.")
            return
        db.set_giveaway_status(active["id"], "cancelled")
        await query.edit_message_text(
            f"🗑 *Campaign \\#{esc(active['id'])} cancel ho gaya\\.*",
            parse_mode=ParseMode.MARKDOWN_V2,
        )


async def _do_draw(query_or_msg, ctx: ContextTypes.DEFAULT_TYPE, active):
    """Core draw logic."""
    approved = db.get_approved_entries(active["id"])
    if not approved:
        if hasattr(query_or_msg, "edit_message_text"):
            await query_or_msg.edit_message_text("❌ Koi approved entry nahi hai abhi tak\\.", parse_mode=ParseMode.MARKDOWN_V2)
        return

    # Check threshold
    threshold = active["min_threshold"]
    if threshold > 0 and len(approved) < threshold:
        db.set_giveaway_status(active["id"], "cancelled")
        msg = (
            f"⚠️ *Giveaway Auto\\-Cancelled*\n\n"
            f"Min threshold: `{threshold}` \\| Got: `{len(approved)}`\n"
            f"Giveaway \\#{esc(active['id'])} cancelled\\."
        )
        if hasattr(query_or_msg, "edit_message_text"):
            await query_or_msg.edit_message_text(msg, parse_mode=ParseMode.MARKDOWN_V2)
        else:
            await ctx.bot.send_message(ADMIN_ID, msg, parse_mode=ParseMode.MARKDOWN_V2)
        return

    # Priority boost — boosted users appear twice in pool
    pool = []
    for e in approved:
        pool.append(e)
        if e["priority_boost"]:
            pool.append(e)  # double weight

    winners_count = min(active["winners_count"], len(approved))
    seen = set()
    winners = []
    shuffled = secrets.SystemRandom().sample(pool, k=len(pool))
    for entry in shuffled:
        if entry["user_id"] not in seen:
            winners.append(entry)
            seen.add(entry["user_id"])
        if len(winners) == winners_count:
            break

    db.set_giveaway_status(active["id"], "ended")
    for w in winners:
        db.set_winner(active["id"], w["user_id"])

    # Build winner announcement
    lines = [
        f"🎊 *CAMPAIGN \\#{esc(active['id'])} RESULTS\\!*\n",
        f"🎁 *Prize:* {esc(active['prize'])}",
        f"👥 *Total participants:* `{len(approved)}`\n",
        "🏆 *Winners:*\n",
    ]
    medals = ["🥇", "🥈", "🥉"]
    for i, w in enumerate(winners):
        medal = medals[i] if i < 3 else f"{i+1}\\."
        tg = f"@{esc(w['telegram_username'])}" if w["telegram_username"] else f"User `{code_esc(w['user_id'])}`"
        lines.append(f"{medal} {tg} \\| GH: `{code_esc(w['github_username'])}`")

    # Secret prize winners
    secret_eligible = db.get_secret_prize_eligible(active["id"], REFERRAL_SECRET_THRESHOLD)
    if secret_eligible and active["secret_prize"]:
        lines.append(f"\n🏅 *Secret Prize \\({esc(active['secret_prize'])}\\) eligible:*")
        for row in secret_eligible:
            uname_row = db.get_entry_by_user(active["id"], row["referrer_id"])
            un = f"@{esc(uname_row['telegram_username'])}" if uname_row and uname_row["telegram_username"] else f"ID:{esc(row['referrer_id'])}"
            lines.append(f"  🌟 {un} \\({esc(row['ref_count'])} referrals\\)")

    result_msg = "\n".join(lines)

    if hasattr(query_or_msg, "edit_message_text"):
        await query_or_msg.edit_message_text(result_msg, parse_mode=ParseMode.MARKDOWN_V2)
    else:
        await ctx.bot.send_message(ADMIN_ID, result_msg, parse_mode=ParseMode.MARKDOWN_V2)

    # DM winners
    for w in winners:
        try:
            await ctx.bot.send_message(
                chat_id=w["user_id"],
                text=(
                    f"🎊 *Congratulations\\! Tu Jeet Gaya\\!* 🎉\n\n"
                    f"🎁 Prize: {esc(active['prize'])}\n"
                    f"📌 Campaign: \\#{esc(active['id'])}\n\n"
                    f"Prize claim karne ke liye admin se contact karo\\! 🙌"
                ),
                parse_mode=ParseMode.MARKDOWN_V2,
            )
        except Exception:
            pass


# ══════════════════════════════════════════════
#  ➕ Campaign Creation Flow (text message steps)
# ══════════════════════════════════════════════

async def handle_admin_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Handles multi-step giveaway creation and broadcast/ban/unban inputs."""
    user = update.effective_user
    if not is_admin(user.id):
        return

    # ── Broadcast ──
    if ctx.user_data.get("awaiting_broadcast"):
        ctx.user_data.pop("awaiting_broadcast", None)
        gid = ctx.user_data.get("broadcast_gid")
        if not gid:
            await update.message.reply_text("❌ No active campaign to broadcast to.")
            return
        entries = db.get_approved_entries(gid)
        sent, failed = 0, 0
        broadcast_text = (
            f"📣 *Message from Admin*\n\n{esc(update.message.text)}"
        )
        for e in entries:
            try:
                await ctx.bot.send_message(e["user_id"], broadcast_text,
                                           parse_mode=ParseMode.MARKDOWN_V2)
                sent += 1
            except Exception:
                failed += 1
        await update.message.reply_text(
            f"📣 *Broadcast Complete*\n\n✅ Sent: `{sent}` \\| ❌ Failed: `{failed}`",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return

    # ── Ban ──
    if ctx.user_data.get("awaiting_ban"):
        ctx.user_data.pop("awaiting_ban", None)
        parts = update.message.text.split(":", 1)
        try:
            uid = int(parts[0].strip())
            reason = parts[1].strip() if len(parts) > 1 else "No reason given"
            db.ban_user(uid, reason, utcnow().isoformat())
            await update.message.reply_text(
                f"🚫 User `{code_esc(uid)}` ban ho gaya\\.\nReason: {esc(reason)}",
                parse_mode=ParseMode.MARKDOWN_V2,
            )
        except ValueError:
            await update.message.reply_text("❌ Valid Telegram ID bhejo\\.", parse_mode=ParseMode.MARKDOWN_V2)
        return

    # ── Unban ──
    if ctx.user_data.get("awaiting_unban"):
        ctx.user_data.pop("awaiting_unban", None)
        try:
            uid = int(update.message.text.strip())
            db.unban_user(uid)
            await update.message.reply_text(
                f"✅ User `{code_esc(uid)}` unban ho gaya\\.",
                parse_mode=ParseMode.MARKDOWN_V2,
            )
        except ValueError:
            await update.message.reply_text("❌ Valid Telegram ID bhejo\\.", parse_mode=ParseMode.MARKDOWN_V2)
        return

    # ── Edit Campaign Field ──
    edit_field = ctx.user_data.get("awaiting_edit")
    if edit_field:
        ctx.user_data.pop("awaiting_edit", None)
        active = db.get_active_giveaway()
        if active:
            val = update.message.text.strip()
            db.update_giveaway_field(active["id"], edit_field, val)
            await update.message.reply_text(
                f"✅ Campaign ka `{esc(edit_field)}` modify ho gaya\\.",
                parse_mode=ParseMode.MARKDOWN_V2,
            )
        return

    # ── Delete Campaign ──
    if ctx.user_data.get("awaiting_delete"):
        ctx.user_data.pop("awaiting_delete", None)
        try:
            cid = int(update.message.text.strip())
            c_check = db.get_giveaway(cid)
            if not c_check:
                await update.message.reply_text("❌ Ye campaign ID database mein nahi mili.", parse_mode=ParseMode.MARKDOWN_V2)
                return
            db.delete_campaign(cid)
            await update.message.reply_text(f"✅ Campaign `{cid}` permanently delete ho gaya hai.", parse_mode=ParseMode.MARKDOWN_V2)
        except ValueError:
            await update.message.reply_text("❌ Invalid ID.", parse_mode=ParseMode.MARKDOWN_V2)
        return

    # ── Campaign Creation ──
    if not ctx.user_data.get("creating_giveaway"):
        return

    cre = ctx.user_data.setdefault("cre", {})
    step = cre.get("step", "prize")

    if step == "prize":
        cre["prize"] = update.message.text.strip()
        cre["step"]  = "repo"
        await update.message.reply_text(
            "🔗 *Step 2/6 — Repo URL kya hai?*\n_e\\.g\\. https://github\\.com/user/repo_",
            parse_mode=ParseMode.MARKDOWN_V2,
        )

    elif step == "repo":
        cre["repo_url"] = update.message.text.strip()
        cre["step"]     = "tutorial"
        await update.message.reply_text(
            "📹 *Step 3/7 — Tutorial Link bhejo \\(kaise join karna hai?\\)*\n_Agar koi tutorial nahi hai toh `skip` type karo\\._",
            parse_mode=ParseMode.MARKDOWN_V2,
        )

    elif step == "tutorial":
        val = update.message.text.strip()
        cre["tutorial_link"] = None if val.lower() == "skip" else val
        cre["step"]          = "winners"
        await update.message.reply_text(
            "🏆 *Step 4/7 — Kitne winners chahiye?*\n_Number bhejo, e\\.g\\. 3_",
            parse_mode=ParseMode.MARKDOWN_V2,
        )

    elif step == "winners":
        text = update.message.text.strip()
        if not text.isdigit() or int(text) < 1:
            await update.message.reply_text("❌ Valid number daalo \\(1\\+\\)\\.", parse_mode=ParseMode.MARKDOWN_V2)
            return
        cre["winners_count"] = int(text)
        cre["step"]          = "duration"
        await update.message.reply_text(
            "⏱ *Step 5/7 — Duration select karo:*",
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=kb_duration_presets(),
        )

    elif step == "custom_duration":
        text = update.message.text.strip()
        if not text.isdigit() or int(text) < 1:
            await update.message.reply_text("❌ Valid minutes daalo\\.", parse_mode=ParseMode.MARKDOWN_V2)
            return
        cre["duration_minutes"] = int(text)
        cre["step"] = "threshold"
        await update.message.reply_text(
            "🎯 *Step 6/7 — Minimum participants threshold \\(0 \\= no limit\\):*\n"
            "_Agar itne log join nahi karte, giveaway auto\\-cancel ho jayega\\._",
            parse_mode=ParseMode.MARKDOWN_V2,
        )

    elif step == "threshold":
        text = update.message.text.strip()
        if not text.isdigit():
            await update.message.reply_text("❌ Valid number daalo \\(0 \\= no limit\\)\\.", parse_mode=ParseMode.MARKDOWN_V2)
            return
        cre["min_threshold"] = int(text)
        cre["step"] = "secret"
        await update.message.reply_text(
            "🏅 *Step 7/7 — Secret Prize \\(optional\\):*\n"
            "_10\\+ referrals wale users ke liye bonus prize \\(skip karne ke liye `none` type karo\\)_",
            parse_mode=ParseMode.MARKDOWN_V2,
        )

    elif step == "secret":
        val = update.message.text.strip()
        cre["secret_prize"] = None if val.lower() == "none" else val
        cre["step"] = "preview"
        await _show_preview(update, ctx, cre)


async def _show_preview(update_or_query, ctx, cre):
    """Show campaign preview before confirming."""
    if not cre or "prize" not in cre:
        msg = "❌ *Session expired\\.* Campaign creation dobara start karo\\."
        if hasattr(update_or_query, "message") and update_or_query.message:
             await update_or_query.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN_V2)
        else:
             await update_or_query.answer("Session expired", show_alert=True)
        return

    dur = cre.get("duration_minutes", 60)
    end_dt = utcnow() + timedelta(minutes=dur)
    days = dur // 1440
    hours = (dur % 1440) // 60
    mins = dur % 60
    dur_str = ""
    if days:  dur_str += f"{days}d "
    if hours: dur_str += f"{hours}h "
    if mins:  dur_str += f"{mins}m"

    secret_line = f"🏅 Secret Prize: {esc(cre['secret_prize'])}" if cre.get("secret_prize") else "🏅 Secret Prize: _none_"
    threshold_line = f"🎯 Min Threshold: `{cre['min_threshold']}`" if cre.get("min_threshold") else "🎯 Min Threshold: _none_"
    tut_line = f"📹 *Tutorial:* {esc(cre['tutorial_link'])}\n" if cre.get("tutorial_link") else ""

    preview = (
        f"👁 *Preview — Campaign Announcement*\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🎉 *CAMPAIGN LIVE HAI\\!*\n\n"
        f"🎁 *Prize:* {esc(cre['prize'])}\n"
        f"🏆 *Winners:* `{cre['winners_count']}`\n"
        f"⏳ *Duration:* `{code_esc(dur_str.strip())}`\n"
        f"📅 *Ends:* {esc(fmt_dt(end_dt))}\n"
        f"🔗 *Repo:* {esc(cre['repo_url'])}\n"
        f"{tut_line}"
        f"{threshold_line}\n"
        f"{secret_line}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"_Kya ye theek hai? Confirm karo:_"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🚀 Launch Campaign", callback_data="cre:confirm"),
         InlineKeyboardButton("✏️ Start Over",      callback_data="cre:restart")],
    ])
    if hasattr(update_or_query, "message"):
        await update_or_query.message.reply_text(preview, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=kb)
    else:
        await update_or_query.edit_message_text(preview, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=kb)


async def creation_confirm_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return

    action = query.data

    if action == "cre:confirm":
        cre = ctx.user_data.get("cre", {})
        if not cre or "prize" not in cre:
            await query.answer("❌ Error: Session data missing. Please start over.", show_alert=True)
            return

        dur = cre.get("duration_minutes", 60)
        now = utcnow()
        end_time = now + timedelta(minutes=dur)

        gid = db.create_giveaway(
            prize=cre["prize"],
            repo_url=cre["repo_url"],
            winners_count=cre["winners_count"],
            min_threshold=cre.get("min_threshold", 0),
            secret_prize=cre.get("secret_prize"),
            tutorial_link=cre.get("tutorial_link"),
            created_at=now.isoformat(),
            end_time=end_time.isoformat(),
        )
        ctx.user_data.pop("creating_giveaway", None)
        ctx.user_data.pop("cre", None)

        # Schedule auto-expiry job
        ctx.job_queue.run_once(
            auto_expire_job,
            when=timedelta(minutes=dur),
            data={"giveaway_id": gid},
            name=f"expire_{gid}",
        )

        g = db.get_giveaway(gid)
        try:
            tut_str = f"📹 *Kaise join karein? Watch Tutorial:*\n👉 {esc(g['tutorial_link'])}\n\n" if g["tutorial_link"] else ""
        except IndexError:
            tut_str = ""

        announcement = (
            f"🎉 *CAMPAIGN \\#{esc(gid)} LIVE HAI\\!*\n\n"
            f"🎁 *Prize:* {esc(g['prize'])}\n"
            f"🏆 *Winners:* `{g['winners_count']}`\n"
            f"⏳ *Ends:* {esc(fmt_dt(end_time))}\n\n"
            f"{tut_str}"
            f"*Participate kaise karein?*\n"
            f"1️⃣ Is repo ko ⭐ Star karo:\n"
            f"👉 {esc(g['repo_url'])}\n\n"
            f"2️⃣ Bot ko private mein `/join` bhejo\n"
            f"3️⃣ Screenshot \\+ GitHub username bhejo\n"
            f"4️⃣ Admin approve karega ✅\n\n"
            f"_Good luck\\! 🍀_"
        )
        await query.edit_message_text(
            f"✅ *Campaign \\#{esc(gid)} Live Hai\\!*\n\nNeeche announcement copy karo 👇",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        await ctx.bot.send_message(ADMIN_ID, announcement, parse_mode=ParseMode.MARKDOWN_V2)

    elif action == "cre:restart":
        ctx.user_data.pop("creating_giveaway", None)
        ctx.user_data.pop("cre", None)
        await query.edit_message_text(
            "🔄 Restart karo — /admin se New Campaign dobara try karo\\.",
            parse_mode=ParseMode.MARKDOWN_V2,
        )

    # Duration preset selected
    elif action.startswith("dur:"):
        preset = action[4:]
        cre = ctx.user_data.setdefault("cre", {})
        if preset == "custom":
            cre["step"] = "custom_duration"
            await query.edit_message_text(
                "✏️ *Custom Duration*\n\nKitne *minutes* chahiye? \\(e\\.g\\. 90 for 1\\.5 hours\\)",
                parse_mode=ParseMode.MARKDOWN_V2,
            )
        else:
            cre["duration_minutes"] = DURATION_PRESETS[preset]
            cre["step"] = "threshold"
            await query.edit_message_text(
                f"✅ Duration set: *{esc(preset)}*\n\n"
                "🎯 *Step 6/7 — Minimum participants threshold \\(0 \\= no limit\\):*\n"
                "_Number bhejo\\._",
                parse_mode=ParseMode.MARKDOWN_V2,
            )


# ══════════════════════════════════════════════
#  👤  User Flow — /join + proof
# ══════════════════════════════════════════════

async def _start_join_flow(user, chat, ctx: ContextTypes.DEFAULT_TYPE):
    """Helper to initiate the join process for a user."""
    if chat.type != "private":
        bot_info = await ctx.bot.get_me()
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("🚀 Join Campaign (Private)", url=f"https://t.me/{bot_info.username}?start=join")
        ]])
        await chat.send_message(
            f"📩 {user_mention(user)}, campaign join karne ke liye mujhe private mein message karo\\!",
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=kb
        )
        return

    if db.is_banned(user.id):
        await chat.send_message(
            "🚫 *Tu is campaign se disqualify ho gaya hai\\.*",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return

    active = db.get_active_giveaway()
    if not active:
        await chat.send_message(
            "😔 *Abhi koi active campaign nahi hai\\.*\nBaad mein try karo\\!",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return

    # Check expiry
    if datetime.fromisoformat(active["end_time"]) <= utcnow():
        await chat.send_message(
            "⏰ *Campaign ka time khatam ho gaya\\.*",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return

    existing = db.get_entry_by_user(active["id"], user.id)
    if existing:
        status_msgs = {
            "pending":  "⏳ *Tera proof pending review mein hai\\.*\nAdmin jaldi verify karega\\.",
            "approved": "✅ *Teri entry approved hai\\!* All the best 🍀",
            "rejected": "❌ *Teri entry reject hui thi\\.*\nSahi proof ke saath dobara bhejo\\.",
        }
        msg = status_msgs.get(existing["status"], "Already submitted\\.")
        await chat.send_message(msg, parse_mode=ParseMode.MARKDOWN_V2)
        if existing["status"] != "rejected":
            return

    pending_proofs[user.id] = {"step": "awaiting_proof", "giveaway_id": active["id"]}

    # Generate referral link
    bot_info = await ctx.bot.get_me()
    ref_link = f"https://t.me/{bot_info.username}?start=ref_{user.id}"
    ref_count = db.count_referrals(active["id"], user.id)
    try:
        tut_str = f"🆘 *Watch Tutorial \\(kaise join karein\\):*\n👉 {esc(active['tutorial_link'])}\n\n" if active["tutorial_link"] else ""
    except IndexError:
        tut_str = ""


    await chat.send_message(
        f"🎉 *Campaign \\#{esc(active['id'])} — Entry Instructions*\n\n"
        f"{tut_str}"
        f"*Step 1️⃣* — Is repo ko ⭐ Star karo:\n"
        f"👉 {esc(active['repo_url'])}\n\n"
        f"*Step 2️⃣* — Ek message bhejo jisme:\n"
        f"   📸 Star wala *screenshot \\(photo\\)*\n"
        f"   ✍️ Caption mein *GitHub username*\n\n"
        f"_Example caption: `myGitHubUser123`_\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🔗 *Tera Referral Link:*\n`{code_esc(ref_link)}`\n\n"
        f"📊 Referrals so far: `{ref_count}`\n"
        f"⚡ 5\\+ refs → Priority Boost\n"
        f"🏅 10\\+ refs → Secret Prize eligible\n"
        f"━━━━━━━━━━━━━━━━━━━━",
        parse_mode=ParseMode.MARKDOWN_V2,
    )


async def cmd_join(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await _start_join_flow(update.effective_user, update.effective_chat, ctx)


async def handle_photo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if update.effective_chat.type != "private":
        return

    if db.is_banned(user.id):
        return

    state = pending_proofs.get(user.id)
    if not state or state.get("step") != "awaiting_proof":
        return

    caption = (update.message.caption or "").strip()
    if not caption:
        await update.message.reply_text(
            "⚠️ *Caption mein GitHub username bhi likhna tha\\!*\n"
            "_Photo dubara bhejo aur caption mein sirf GitHub username likho\\._",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return

    giveaway_id   = state["giveaway_id"]
    github_username = caption
    photo_file_id = update.message.photo[-1].file_id
    now           = utcnow().isoformat()

    inserted = db.add_entry(
        giveaway_id=giveaway_id,
        user_id=user.id,
        telegram_username=user.username,
        github_username=github_username,
        photo_file_id=photo_file_id,
        submitted_at=now,
    )

    if not inserted:
        await update.message.reply_text(
            "⚠️ *Tu already submit kar chuka hai* ya ye GitHub username already use hua hai\\.",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        pending_proofs.pop(user.id, None)
        return

    entry = db.get_entry_by_user(giveaway_id, user.id)
    pending_proofs.pop(user.id, None)
    approved_count = db.count_approved(giveaway_id)

    await update.message.reply_text(
        f"✅ *Proof Submit Ho Gaya\\!*\n\n"
        f"🐙 GitHub: `{code_esc(github_username)}`\n"
        f"⏳ Admin verify karega — approve hone par entry count hogi\\.\n\n"
        f"_All the best\\! 🍀_",
        parse_mode=ParseMode.MARKDOWN_V2,
    )

    # Forward to admin
    tg_info = f"@{esc(user.username)}" if user.username else f"ID:`{user.id}`"
    caption_txt = (
        f"📥 *New Proof Submission*\n\n"
        f"👤 Name: {esc(user.full_name)}\n"
        f"🔖 Telegram: {tg_info}\n"
        f"🆔 ID: `{user.id}`\n"
        f"🐙 GitHub: `{code_esc(github_username)}`\n"
        f"🎁 Campaign: \\#{esc(giveaway_id)}\n"
        f"⏱ Time \\(UTC\\): `{now[:16]}`\n"
        f"📊 Approved so far: `{approved_count}`"
    )
    await ctx.bot.send_photo(
        chat_id=ADMIN_ID,
        photo=photo_file_id,
        caption=caption_txt,
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=kb_approve_reject(entry["id"]),
    )


# ══════════════════════════════════════════════
#  ✅ Approve / ❌ Reject
# ══════════════════════════════════════════════

async def handle_review(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if not is_admin(query.from_user.id):
        await query.answer("⛔ Unauthorized", show_alert=True)
        return

    action, eid_str = query.data.split(":")
    eid   = int(eid_str)
    entry = db.get_entry_by_id(eid)

    if not entry:
        await query.edit_message_caption("❓ Entry nahi mili\\.", parse_mode=ParseMode.MARKDOWN_V2)
        return

    if entry["status"] != "pending":
        await query.answer(f"Already {entry['status']}.", show_alert=True)
        return

    if action == "approve":
        db.update_entry_status(eid, "approved")
        approved_count = db.count_approved(entry["giveaway_id"])
        
        # Check if they were referred by someone
        referrer_id = db.get_referrer(entry["giveaway_id"], entry["user_id"])
        if referrer_id:
            ref_count = db.count_referrals(entry["giveaway_id"], referrer_id)
            if ref_count >= REFERRAL_PRIORITY_THRESHOLD:
                db.set_priority_boost(entry["giveaway_id"], referrer_id, 1)
            
            try:
                await ctx.bot.send_message(
                    chat_id=referrer_id,
                    text=(
                        f"🎉 *Successful Referral\\!*\n\n"
                        f"👤 {esc(entry.get('telegram_username') or 'Ek user')} ki entry approve ho gayi hai\\!\n"
                        f"📊 Total successful referrals: *{esc(ref_count)}*\n"
                        + (f"\n⚡ *Priority Boost activated\\!* \\(5\\+ referrals\\)" if ref_count == REFERRAL_PRIORITY_THRESHOLD else "")
                        + (f"\n🏆 *Secret Prize eligible\\!* \\(10\\+ referrals\\)" if ref_count == REFERRAL_SECRET_THRESHOLD else "")
                    ),
                    parse_mode=ParseMode.MARKDOWN_V2,
                )
            except Exception:
                pass

        # Update priority boost for the APPROVED user (if they also referred others)
        user_ref_count = db.count_referrals(entry["giveaway_id"], entry["user_id"])
        if user_ref_count >= REFERRAL_PRIORITY_THRESHOLD:
            db.set_priority_boost(entry["giveaway_id"], entry["user_id"], 1)

        try:
            await ctx.bot.send_message(
                chat_id=entry["user_id"],
                text=(
                    f"🎉 *Teri Entry Approve Ho Gayi\\!*\n\n"
                    f"🐙 GitHub: `{code_esc(entry['github_username'])}`\n"
                    f"📌 Campaign: \\#{esc(entry['giveaway_id'])}\n"
                    f"👥 Total approved: `{approved_count}`\n\n"
                    f"_All the best\\! 🍀_"
                ),
                parse_mode=ParseMode.MARKDOWN_V2,
            )
        except Exception:
            pass

        # Regenerate caption to ensure perfect formatting
        tg_info = f"@{esc(entry['telegram_username'])}" if entry["telegram_username"] else f"ID:`{entry['user_id']}`"
        new_cap = (
            f"📥 *Proof Submission Review*\n\n"
            f"👤 Telegram: {tg_info}\n"
            f"🆔 ID: `{entry['user_id']}`\n"
            f"🐙 GitHub: `{code_esc(entry['github_username'])}`\n"
            f"🎁 Campaign: \\#{esc(entry['giveaway_id'])}\n"
            f"⏱ Submitted: `{entry['submitted_at'][:16]}`\n\n"
            f"✅ *APPROVED* \\| Total: `{approved_count}`"
        )
        await query.edit_message_caption(new_cap, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=None)

    elif action == "reject":
        db.update_entry_status(eid, "rejected")
        try:
            await ctx.bot.send_message(
                chat_id=entry["user_id"],
                text=(
                    "❌ *Tera proof reject ho gaya\\.*\n\n"
                    "Possible reasons:\n"
                    "• Screenshot sahi nahi tha\n"
                    "• GitHub username match nahi kiya\n"
                    "• Star clearly visible nahi tha\n\n"
                    "Sahi proof ke saath dobara `/join` karo\\."
                ),
                parse_mode=ParseMode.MARKDOWN_V2,
            )
        except Exception:
            pass
            
        tg_info = f"@{esc(entry['telegram_username'])}" if entry["telegram_username"] else f"ID:`{entry['user_id']}`"
        new_cap = (
            f"📥 *Proof Submission Review*\n\n"
            f"👤 Telegram: {tg_info}\n"
            f"🆔 ID: `{entry['user_id']}`\n"
            f"🐙 GitHub: `{code_esc(entry['github_username'])}`\n"
            f"🎁 Campaign: \\#{esc(entry['giveaway_id'])}\n"
            f"⏱ Submitted: `{entry['submitted_at'][:16]}`\n\n"
            f"❌ *REJECTED*"
        )
        await query.edit_message_caption(new_cap, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=None)


# ══════════════════════════════════════════════
#  👤 User Inline Callbacks
# ══════════════════════════════════════════════

async def user_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user
    action = query.data.split(":")[1]

    if action == "join":
        if query.message.chat.type == "private":
            await _start_join_flow(user, query.message.chat, ctx)
        else:
            bot_info = await ctx.bot.get_me()
            await query.answer(
                f"Bot ko private mein open karo!",
                show_alert=True,
            )
            await query.message.reply_text(
                f"📩 {user_mention(user)}, campaign join karne ke liye mujhe private mein message karo\\!",
                parse_mode=ParseMode.MARKDOWN_V2,
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🚀 Open Private Chat", url=f"https://t.me/{bot_info.username}?start=join")
                ]])
            )

    elif action == "leaderboard":
        # Get the most recent campaign (active or ended)
        campaign = db.get_active_giveaway() or db.get_latest_giveaway()
        if not campaign:
            await query.answer("Abhi koi campaign nahi mila.", show_alert=True)
            return

        gid = campaign["id"]
        status_tag = "🟢 ACTIVE" if campaign["status"] == "active" else "🔴 CLOSED"
        stats = db.get_analytics(gid)
        board = db.get_referral_leaderboard(gid)
        
        header = (
            f"🏆 *Leaderboard — Campaign \\#{esc(gid)}*\n"
            f"🎁 Prize: {esc(campaign['prize'])}\n"
            f"📊 Status: {status_tag}\n"
            f"👥 Total Joined: `{stats['total']}`\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
        )
        
        lines = [header]
        if not board:
            lines.append("_Abhi koi referrals nahi hain\\._")
        else:
            medals = ["🥇", "🥈", "🥉"]
            for i, row in enumerate(board):
                medal = medals[i] if i < 3 else f"{i+1}\\."
                uname = f"@{esc(row['uname'])}" if row["uname"] else f"ID:{esc(row['referrer_id'])}"
                lines.append(f"{medal} {uname} — `{row['ref_count']}` refs")
        
        # If it's closed, show winners too
        if campaign["status"] != "active":
            winners = db.get_winners(gid)
            if winners:
                lines.append(f"\n🌟 *Winning Result:*")
                for w in winners:
                    un = f"@{esc(w['telegram_username'])}" if w["telegram_username"] else f"ID:{code_esc(w['user_id'])}"
                    lines.append(f"🏆 {un}")

        await query.edit_message_text(
            "\n".join(lines),
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="user:back")]])
        )

    elif action == "mystats":
        campaign = db.get_active_giveaway() or db.get_latest_giveaway()
        if not campaign:
            await query.answer("Koi campaign nahi mila.", show_alert=True)
            return
        
        gid   = campaign["id"]
        entry = db.get_entry_by_user(gid, user.id)
        ref_cnt = db.count_referrals(gid, user.id)
        bot_info = await ctx.bot.get_me()
        ref_link = f"https://t.me/{bot_info.username}?start=ref_{user.id}"
        
        status_label = entry["status"] if entry else "Not joined"
        status_icon = {"pending": "⏳", "approved": "✅", "rejected": "❌"}.get(status_label, "➖")
        
        winner_msg = ""
        is_winner = False
        if entry:
            try:
                is_winner = entry["is_winner"]
            except IndexError:
                pass

        if is_winner:
            winner_msg = "\n\n🎊 *CONGRATULATIONS\\! TU JEET GAYA HAI\\!* 🎉"
        elif campaign["status"] != "active" and entry:
            winner_msg = "\n\n😔 Iss baar luck nahi chala, try again next time\\!"

        msg = (
            f"📊 *My Stats — Campaign \\#{esc(gid)}*\n"
            f"🎁 Prize: {esc(campaign['prize'])}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"Status: {status_icon} {esc(status_label.upper())}\n"
            f"🔗 Referrals: `{ref_cnt}`\n"
            f"⚡ Priority Boost: {'Yes' if entry and entry['priority_boost'] else 'No'}\n"
            f"{winner_msg}\n\n"
            f"*Your Referral Link:*\n`{code_esc(ref_link)}`"
        )
        await query.edit_message_text(
            msg,
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="user:back")]])
        )

    elif action == "back":
        active = db.get_active_giveaway()
        status_line = (
            f"🟢 *Active Campaign:* {esc(active['prize'])} \\| ⏳ {esc(time_left(active['end_time']))} left"
            if active else "⚪ *No active campaign right now\\.*"
        )
        await query.edit_message_text(
            f"💠 *Welcome to Campaign Bot V2*\n\n{status_line}",
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=kb_join_menu(),
        )


# ══════════════════════════════════════════════
#  ⏰  Auto-Expiry Job
# ══════════════════════════════════════════════

async def auto_expire_job(ctx: ContextTypes.DEFAULT_TYPE):
    gid = ctx.job.data["giveaway_id"]
    g   = db.get_giveaway(gid)
    if not g or g["status"] != "active":
        return

    approved = db.get_approved_entries(gid)
    threshold = g["min_threshold"]

    if threshold > 0 and len(approved) < threshold:
        db.set_giveaway_status(gid, "cancelled")
        await ctx.bot.send_message(
            chat_id=ADMIN_ID,
            text=(
                f"⚠️ *Giveaway \\#{esc(gid)} Auto\\-Cancelled*\n\n"
                f"Min threshold: `{threshold}` \\| Got: `{len(approved)}`\n"
                f"Giveaway invalid — cancelled\\."
            ),
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return

    # Auto draw
    class FakeQuery:
        message = None
        async def edit_message_text(self, *a, **kw): pass

    await ctx.bot.send_message(
        ADMIN_ID,
        f"⏰ *Giveaway \\#{esc(gid)} expired — auto draw shuru\\!*",
        parse_mode=ParseMode.MARKDOWN_V2,
    )

    class DummyCtx:
        bot = ctx.bot

    await _do_draw(FakeQuery(), ctx, g)


# ══════════════════════════════════════════════
#  🚀  MAIN
# ══════════════════════════════════════════════

def main():
    db.init_db()
    log.info("✅ DB initialized.")

    app = Application.builder().token(BOT_TOKEN).build()

    # Commands
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("admin", cmd_admin))
    app.add_handler(CommandHandler("join",  cmd_join))

    # Admin dashboard callbacks
    app.add_handler(CallbackQueryHandler(admin_callback,          pattern=r"^admin:"))
    app.add_handler(CallbackQueryHandler(draw_cancel_callback,    pattern=r"^(draw|cancel):"))
    app.add_handler(CallbackQueryHandler(creation_confirm_callback, pattern=r"^(cre:|dur:)"))
    app.add_handler(CallbackQueryHandler(handle_review,           pattern=r"^(approve|reject):\d+$"))
    app.add_handler(CallbackQueryHandler(user_callback,           pattern=r"^user:"))

    # Messages
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, handle_admin_text
    ))
    app.add_handler(MessageHandler(
        filters.PHOTO & filters.ChatType.PRIVATE, handle_photo
    ))

    log.info("🚀 Giveaway Bot V2 chal raha hai...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
