"""
🎉 Telegram Proof-Based Giveaway Bot
=====================================
Flow:
  Admin  → /newgiveaway  → prize, repo URL, winners, duration set karo
  User   → /join (private chat) → repo star karo, screenshot + GitHub username bhejo
  Admin  → proof review panel → ✅ Approve / ❌ Reject
  Approved users → giveaway pool mein count
  Admin  → /draw → random winner announce
"""

import secrets
import logging
from datetime import datetime, timedelta

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)

import database as db
from config import BOT_TOKEN, ADMIN_ID

logging.basicConfig(
    format="%(asctime)s — %(levelname)s — %(message)s",
    level=logging.INFO,
)
log = logging.getLogger(__name__)

# ── Conversation states ──────────────────────
(
    ASK_PRIZE,
    ASK_REPO,
    ASK_WINNERS,
    ASK_DURATION,
) = range(4)

# user_id → {"photo_file_id": ..., "step": "photo"|"username"}
pending_proofs: dict = {}


# ─────────────────────────────────────────────
#  Utility
# ─────────────────────────────────────────────

def is_admin(user_id: int) -> bool:
    return user_id == ADMIN_ID


def fmt_user(user) -> str:
    name = user.full_name or "Unknown"
    uname = f" (@{user.username})" if user.username else ""
    return f"{name}{uname}"


# ─────────────────────────────────────────────
#  /start
# ─────────────────────────────────────────────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 *Giveaway Bot mein swagat hai!*\n\n"
        "🎁 Giveaway mein participate karne ke liye `/join` bhejo.\n\n"
        "_(Admin commands: /newgiveaway, /draw, /participants, /cancelgiveaway)_",
        parse_mode="Markdown",
    )


# ─────────────────────────────────────────────
#  /newgiveaway — Admin only  (ConversationHandler)
# ─────────────────────────────────────────────

async def new_giveaway_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Sirf admin ye command use kar sakta hai.")
        return ConversationHandler.END

    active = db.get_active_giveaway()
    if active:
        await update.message.reply_text(
            f"⚠️ Pehle se ek active giveaway chal raha hai (ID: #{active['id']}).\n"
            "Pehle /cancelgiveaway karo ya /draw karo."
        )
        return ConversationHandler.END

    await update.message.reply_text("🎁 *Prize ka naam kya hai?*\n_(e.g. ₹500 Amazon Gift Card)_",
                                    parse_mode="Markdown")
    return ASK_PRIZE


async def recv_prize(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["prize"] = update.message.text.strip()
    await update.message.reply_text(
        "🔗 *Repo ka URL kya hai?*\n_(e.g. https://github.com/user/repo)_",
        parse_mode="Markdown",
    )
    return ASK_REPO


async def recv_repo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["repo_url"] = update.message.text.strip()
    await update.message.reply_text("🏆 *Kitne winners chahiye?* _(number bhejo, e.g. 3)_",
                                    parse_mode="Markdown")
    return ASK_WINNERS


async def recv_winners(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if not text.isdigit() or int(text) < 1:
        await update.message.reply_text("❌ Valid number daalo (1 ya zyada).")
        return ASK_WINNERS
    ctx.user_data["winners_count"] = int(text)
    await update.message.reply_text("⏱ *Giveaway kitne minutes tak chalega?*\n_(e.g. 60 for 1 hour)_",
                                    parse_mode="Markdown")
    return ASK_DURATION


async def recv_duration(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if not text.isdigit() or int(text) < 1:
        await update.message.reply_text("❌ Valid minutes daalo (1 ya zyada).")
        return ASK_DURATION

    duration = int(text)
    now = datetime.utcnow()
    end_time = now + timedelta(minutes=duration)

    gid = db.create_giveaway(
        prize=ctx.user_data["prize"],
        repo_url=ctx.user_data["repo_url"],
        winners_count=ctx.user_data["winners_count"],
        created_at=now.isoformat(),
        end_time=end_time.isoformat(),
    )

    g = db.get_giveaway(gid)
    msg = (
        f"✅ *Giveaway #{gid} Create Ho Gaya!*\n\n"
        f"🎁 Prize: {g['prize']}\n"
        f"🔗 Repo: {g['repo_url']}\n"
        f"🏆 Winners: {g['winners_count']}\n"
        f"⏱ Duration: {duration} minutes\n"
        f"🕐 End Time (UTC): {end_time.strftime('%Y-%m-%d %H:%M')}\n\n"
        f"Users ko ye message share karo 👇"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")

    # Shareable announcement
    announcement = (
        f"🎉 *GIVEAWAY #{gid} LIVE HAI!*\n\n"
        f"🎁 *Prize:* {g['prize']}\n"
        f"🏆 *Winners:* {g['winners_count']}\n"
        f"⏳ *Ends:* {end_time.strftime('%d %b %Y %H:%M')} UTC\n\n"
        f"*Participate kaise karein?*\n"
        f"1️⃣ Is repo ko Star karo 👉 {g['repo_url']}\n"
        f"2️⃣ Bot ko message karo: @{ctx.bot.username}\n"
        f"3️⃣ `/join` command bhejo\n"
        f"4️⃣ Star ka screenshot + GitHub username bhejo\n\n"
        f"✅ Admin verify karega — approve hone par entry count hogi!\n"
        f"_Good luck! 🍀_"
    )
    await update.message.reply_text(announcement, parse_mode="Markdown")
    return ConversationHandler.END


async def cancel_conv(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Operation cancel kar diya.")
    return ConversationHandler.END


# ─────────────────────────────────────────────
#  /join — User proof submission (private chat)
# ─────────────────────────────────────────────

async def cmd_join(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat

    # Sirf private chat mein kaam kare
    if chat.type != "private":
        await update.message.reply_text(
            "📩 Please mujhe *private mein* message karo aur `/join` bhejo!",
            parse_mode="Markdown",
        )
        return

    active = db.get_active_giveaway()
    if not active:
        await update.message.reply_text("😔 Abhi koi active giveaway nahi hai. Baad mein try karo!")
        return

    # Check if already submitted
    existing = db.get_entry_by_user(active["id"], user.id)
    if existing:
        status_map = {
            "pending":  "⏳ Tera proof pending review mein hai. Admin approve karega jaldi.",
            "approved": "✅ Teri entry already approved hai! All the best 🍀",
            "rejected": "❌ Teri entry reject hui thi. Sahi proof ke saath dobara bhejo.",
        }
        await update.message.reply_text(status_map.get(existing["status"], "Already submitted."))
        if existing["status"] != "rejected":
            return

    # Invite to submit proof
    pending_proofs[user.id] = {"step": "awaiting_proof", "giveaway_id": active["id"]}
    await update.message.reply_text(
        f"🎉 *Giveaway #{active['id']} — Entry Instructions*\n\n"
        f"1️⃣ Pehle is repo ko Star karo:\n👉 {active['repo_url']}\n\n"
        f"2️⃣ Ab ek *single message* bhejo jisme:\n"
        f"   📸 Star wala screenshot (photo)\n"
        f"   ✍️ Caption mein apna *GitHub username*\n\n"
        f"_Example caption: `myGitHubUser123`_\n\n"
        f"⚠️ Photo ke saath caption zaroori hai!",
        parse_mode="Markdown",
    )


# ─────────────────────────────────────────────
#  Proof photo handler
# ─────────────────────────────────────────────

async def handle_photo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat

    if chat.type != "private":
        return

    state = pending_proofs.get(user.id)
    if not state or state.get("step") != "awaiting_proof":
        return

    caption = (update.message.caption or "").strip()
    if not caption:
        await update.message.reply_text(
            "⚠️ *Photo ke saath caption mein GitHub username bhi bhejo!*\n"
            "_Photo dubara bhejo aur caption mein sirf GitHub username likho._",
            parse_mode="Markdown",
        )
        return

    github_username = caption
    giveaway_id = state["giveaway_id"]
    photo_file_id = update.message.photo[-1].file_id
    now = datetime.utcnow().isoformat()

    # Save to DB
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
            "⚠️ Tujhe already submit kar diya hai ya ye GitHub username already use hua hai."
        )
        pending_proofs.pop(user.id, None)
        return

    # Get entry id
    entry = db.get_entry_by_user(giveaway_id, user.id)
    pending_proofs.pop(user.id, None)

    await update.message.reply_text(
        "✅ *Proof submit ho gaya!*\n\n"
        f"GitHub Username: `{github_username}`\n\n"
        "⏳ Admin verify karega. Approve hone par teri entry count hogi. 🍀",
        parse_mode="Markdown",
    )

    # ── Forward to admin for review ──
    tg_user_info = fmt_user(user)
    approve_btn = InlineKeyboardButton("✅ Approve", callback_data=f"approve:{entry['id']}")
    reject_btn  = InlineKeyboardButton("❌ Reject",  callback_data=f"reject:{entry['id']}")
    keyboard = InlineKeyboardMarkup([[approve_btn, reject_btn]])

    caption_text = (
        f"📥 *New Proof Submission*\n\n"
        f"👤 User: {tg_user_info}\n"
        f"🆔 Telegram ID: `{user.id}`\n"
        f"🐙 GitHub: `{github_username}`\n"
        f"🎁 Giveaway: #{giveaway_id}\n"
        f"🕐 Time (UTC): {now[:16]}"
    )

    await ctx.bot.send_photo(
        chat_id=ADMIN_ID,
        photo=photo_file_id,
        caption=caption_text,
        parse_mode="Markdown",
        reply_markup=keyboard,
    )


# ─────────────────────────────────────────────
#  Admin: Approve / Reject callback
# ─────────────────────────────────────────────

async def handle_review(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if not is_admin(query.from_user.id):
        await query.answer("⛔ Sirf admin ye action le sakta hai.", show_alert=True)
        return

    action, entry_id_str = query.data.split(":")
    entry_id = int(entry_id_str)
    entry = db.get_entry_by_id(entry_id)

    if not entry:
        await query.edit_message_caption("❓ Entry nahi mili.")
        return

    if entry["status"] != "pending":
        await query.answer(f"Ye entry pehle se {entry['status']} hai.", show_alert=True)
        return

    if action == "approve":
        db.update_entry_status(entry_id, "approved")
        approved_count = db.count_approved(entry["giveaway_id"])

        # Notify user
        await ctx.bot.send_message(
            chat_id=entry["user_id"],
            text=(
                f"🎉 *Teri entry Approve Ho Gayi!*\n\n"
                f"GitHub: `{entry['github_username']}`\n"
                f"Giveaway: #{entry['giveaway_id']}\n\n"
                f"Abhi *{approved_count}* log giveaway mein hain. All the best! 🍀"
            ),
            parse_mode="Markdown",
        )

        # Update admin message
        await query.edit_message_caption(
            query.message.caption + f"\n\n✅ *APPROVED* by admin | Total: {approved_count}",
            parse_mode="Markdown",
        )

    elif action == "reject":
        db.update_entry_status(entry_id, "rejected")

        await ctx.bot.send_message(
            chat_id=entry["user_id"],
            text=(
                "❌ *Tera proof reject ho gaya.*\n\n"
                "Reasons ho sakte hain:\n"
                "• Screenshot sahi nahi tha\n"
                "• GitHub username match nahi kiya\n"
                "• Star clearly visible nahi tha\n\n"
                "Sahi proof ke saath dobara `/join` karo."
            ),
            parse_mode="Markdown",
        )

        await query.edit_message_caption(
            query.message.caption + "\n\n❌ *REJECTED* by admin",
            parse_mode="Markdown",
        )


# ─────────────────────────────────────────────
#  /participants — Admin
# ─────────────────────────────────────────────

async def cmd_participants(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Sirf admin ye dekh sakta hai.")
        return

    active = db.get_active_giveaway()
    if not active:
        await update.message.reply_text("Koi active giveaway nahi hai.")
        return

    entries = db.get_all_entries(active["id"])
    if not entries:
        await update.message.reply_text("Abhi koi entry nahi aayi.")
        return

    lines = [f"📋 *Giveaway #{active['id']} — Entries*\n"]
    for e in entries:
        status_icon = {"pending": "⏳", "approved": "✅", "rejected": "❌"}.get(e["status"], "?")
        tg = f"@{e['telegram_username']}" if e["telegram_username"] else f"ID:{e['user_id']}"
        lines.append(f"{status_icon} {tg} | GH: `{e['github_username']}`")

    approved = sum(1 for e in entries if e["status"] == "approved")
    pending  = sum(1 for e in entries if e["status"] == "pending")
    rejected = sum(1 for e in entries if e["status"] == "rejected")
    lines.append(f"\n✅ Approved: {approved} | ⏳ Pending: {pending} | ❌ Rejected: {rejected}")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


# ─────────────────────────────────────────────
#  /draw — Admin
# ─────────────────────────────────────────────

async def cmd_draw(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Sirf admin draw kar sakta hai.")
        return

    active = db.get_active_giveaway()
    if not active:
        await update.message.reply_text("Koi active giveaway nahi hai.")
        return

    approved = db.get_approved_entries(active["id"])
    if not approved:
        await update.message.reply_text("❌ Koi approved entry nahi hai abhi tak.")
        return

    winners_count = min(active["winners_count"], len(approved))
    winners = secrets.SystemRandom().sample(list(approved), k=winners_count)

    db.end_giveaway(active["id"])

    lines = [f"🎉 *GIVEAWAY #{active['id']} RESULTS!*\n", f"🎁 Prize: {active['prize']}\n"]
    for i, w in enumerate(winners, 1):
        tg = f"@{w['telegram_username']}" if w["telegram_username"] else f"User ID: {w['user_id']}"
        lines.append(f"🏆 Winner #{i}: {tg} | GitHub: `{w['github_username']}`")

    lines.append(f"\n_Total participants: {len(approved)}_")
    result_msg = "\n".join(lines)

    await update.message.reply_text(result_msg, parse_mode="Markdown")

    # Notify winners
    for w in winners:
        try:
            await ctx.bot.send_message(
                chat_id=w["user_id"],
                text=(
                    f"🎊 *Congratulations! Tu Jeet Gaya!*\n\n"
                    f"🎁 Prize: {active['prize']}\n"
                    f"Giveaway: #{active['id']}\n\n"
                    f"Admin se contact karo prize claim karne ke liye! 🙌"
                ),
                parse_mode="Markdown",
            )
        except Exception:
            pass  # User ne bot block kiya hoga


# ─────────────────────────────────────────────
#  /cancelgiveaway — Admin
# ─────────────────────────────────────────────

async def cmd_cancel_giveaway(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Sirf admin cancel kar sakta hai.")
        return

    active = db.get_active_giveaway()
    if not active:
        await update.message.reply_text("Koi active giveaway nahi hai.")
        return

    db.cancel_giveaway(active["id"])
    await update.message.reply_text(f"🗑 Giveaway #{active['id']} cancel kar diya gaya.")


# ─────────────────────────────────────────────
#  Main
# ─────────────────────────────────────────────

def main():
    db.init_db()
    log.info("DB initialized.")

    app = Application.builder().token(BOT_TOKEN).build()

    # /newgiveaway conversation
    new_giveaway_conv = ConversationHandler(
        entry_points=[CommandHandler("newgiveaway", new_giveaway_start)],
        states={
            ASK_PRIZE:    [MessageHandler(filters.TEXT & ~filters.COMMAND, recv_prize)],
            ASK_REPO:     [MessageHandler(filters.TEXT & ~filters.COMMAND, recv_repo)],
            ASK_WINNERS:  [MessageHandler(filters.TEXT & ~filters.COMMAND, recv_winners)],
            ASK_DURATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, recv_duration)],
        },
        fallbacks=[CommandHandler("cancel", cancel_conv)],
    )

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(new_giveaway_conv)
    app.add_handler(CommandHandler("join", cmd_join))
    app.add_handler(CommandHandler("participants", cmd_participants))
    app.add_handler(CommandHandler("draw", cmd_draw))
    app.add_handler(CommandHandler("cancelgiveaway", cmd_cancel_giveaway))
    app.add_handler(CallbackQueryHandler(handle_review, pattern=r"^(approve|reject):\d+$"))
    app.add_handler(MessageHandler(filters.PHOTO & filters.ChatType.PRIVATE, handle_photo))

    log.info("Bot chal raha hai... Ctrl+C se rokein.")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
