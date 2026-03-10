# 🎉 Telegram Giveaway Bot — Setup Guide

## 📁 Files
```
giveaway_bot/
├── bot.py           ← Main bot
├── database.py      ← SQLite layer
├── config.py        ← Token & Admin ID
├── requirements.txt
└── README.md
```

---

## ⚙️ Setup Steps

### 1. Bot Token Lo
- Telegram mein @BotFather ko message karo
- `/newbot` command do → naam aur username choose karo
- Token copy karo

### 2. Apna Telegram ID Lo
- @userinfobot ko message karo Telegram mein
- Wo tumhara numeric ID batayega

### 3. config.py Edit Karo
```python
BOT_TOKEN = "1234567890:ABCdef..."   # BotFather wala token
ADMIN_ID  = 987654321                # Tumhara Telegram ID
```

### 4. Install karo
```bash
pip install -r requirements.txt
```

### 5. Run karo
```bash
python bot.py
```

---

## 🤖 Commands

### Admin Commands
| Command | Kaam |
|---|---|
| `/newgiveaway` | Naya giveaway create karo (prize, repo, winners, duration) |
| `/participants` | Sabki entry status dekho |
| `/draw` | Random winner nikalo |
| `/cancelgiveaway` | Active giveaway cancel karo |

### User Commands
| Command | Kaam |
|---|---|
| `/start` | Bot se milna |
| `/join` | Giveaway mein participate karo (private chat mein) |

---

## 🔄 Full Flow

```
Admin → /newgiveaway → prize/repo/winners/duration set karo
      → Bot ek shareable announcement deta hai

User  → Bot ko private mein /join bhejo
      → Repo star karo
      → Screenshot + GitHub username (caption mein) bhejo

Admin → Proof review panel aata hai with [✅ Approve] [❌ Reject]
      → Approve karo → User count mein aa jaata hai
      → Reject karo → User ko reason bata ke dobara try karne ka mauka

Admin → /draw → Random winner announce + winner ko DM
```

---

## 🗄️ Database
SQLite file `giveaway.db` automatically ban jaati hai. Backup ke liye copy kar lo.

---

## ⚠️ Notes
- Ek user ek GitHub username se sirf ek baar enter ho sakta hai
- `/join` sirf private chat mein kaam karta hai
- Bot ko group mein admin banana zaroori nahi, sirf DM channel ke liye use hoga
