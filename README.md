# 💠 Giveaway Bot V2 — Enterprise Edition

## 📁 Files
```
giveaway_v2/
├── bot.py           ← Main bot (all handlers)
├── database.py      ← SQLite — giveaways, entries, referrals, bans
├── config.py        ← Token, Admin ID, presets
├── requirements.txt
└── README.md
```

---

## ⚙️ Setup

### 1. BotFather se token lo
```
/newbot → naam → username → TOKEN copy karo
```

### 2. Apna Telegram ID lo
- @userinfobot ko message karo

### 3. config.py edit karo
```python
BOT_TOKEN = "YOUR_TOKEN"
ADMIN_ID  = 123456789
```

### 4. Install & Run
```bash
pip install -r requirements.txt
python bot.py
```

---

## 🤖 Commands

### Admin
| Command | Action |
|---|---|
| `/admin` | Full control dashboard (buttons se sab kuch) |

### User
| Command | Action |
|---|---|
| `/start` | Welcome + active giveaway status |
| `/join` | Giveaway mein participate (private chat) |

---

## 🔄 Full Flow

```
Admin  /admin → "New Giveaway"
       → Prize → Repo → Winners → Duration (preset/custom)
       → Min Threshold → Secret Prize → Preview → Confirm → LIVE!

User   /start → "Join Giveaway" → /join (private)
       → Repo star karo → Screenshot + GitHub username bhejo
       → Admin ko proof forward → [✅ Approve] [❌ Reject]
       → Approved → entry count + referral link mile

Admin  /admin → "Draw Winners"
       → Confirm → Auto draw (priority boost wale 2x chance)
       → Winners announce + DM
```

---

## ⭐ V2 Features

| Feature | Detail |
|---|---|
| 💠 Premium UI | MarkdownV2 + Inline buttons everywhere |
| ⚙️ Admin Dashboard | `/admin` — single control panel |
| 🎯 Min Threshold | Auto-cancel if not enough participants |
| ⏱ Duration | 1 hour se 1 month tak (presets + custom) |
| 👁 Preview | Giveaway live karne se pehle preview |
| 🔗 Referral Links | Unique link per user, auto-tracked |
| ⚡ Priority Boost | 5+ referrals → 2x winning chance |
| 🏅 Secret Prize | 10+ referrals → bonus prize eligible |
| 🏆 Leaderboard | Top referrers list |
| 📊 Live Analytics | Approved/Pending/Rejected + referral stats |
| 📣 Broadcast | Ek click mein sabko message |
| 🚫 Ban/Unban | Spammers disqualify |
| 📥 CSV Export | Full participant data download |
| ⏰ Auto-Expiry | Timer khatam → auto draw ya auto-cancel |
| 🛡 Anti-Cheat | Duplicate GitHub, self-referral blocked |

---

## 🗄️ Database Tables
- `giveaways` — prize, repo, threshold, secret prize, status
- `entries` — user proofs, status, priority boost
- `referrals` — who referred whom
- `banned_users` — disqualified users
