# ══════════════════════════════════════════════
#  ⚙️  GIVEAWAY BOT V2 — CONFIG
# ══════════════════════════════════════════════

BOT_TOKEN   = "YOUR_BOT_TOKEN_HERE"   # @BotFather se lo
ADMIN_ID    = 123456789               # Apna Telegram numeric user ID

DB_PATH     = "giveaway_v2.db"

# Secret Prize threshold (referrals)
REFERRAL_PRIORITY_THRESHOLD = 5    # 5+ referrals → priority boost
REFERRAL_SECRET_THRESHOLD   = 10   # 10+ referrals → secret prize eligible

# Duration presets (label → minutes)
DURATION_PRESETS = {
    "1 Hour":   60,
    "6 Hours":  360,
    "12 Hours": 720,
    "1 Day":    1440,
    "3 Days":   4320,
    "1 Week":   10080,
    "2 Weeks":  20160,
    "1 Month":  43200,
}
