# 🛡️ Guard Bot — Professional Edition v2.1

Multi-tenant Telegram group protection bot.
Owner → Premium Users → Their Groups — All independent.

**Storage:** MongoDB Atlas (Free) — data never wiped.
**Hosting:** Render.com (Free Web Service) + UptimeRobot

---

## 🔥 What's Fixed in v2.1

| Fix | Detail |
|-----|--------|
| 🔄 Webhook mode | Replaces polling — survives Render restarts (no more 1.5-day crashes) |
| 💓 Self keep-alive | Bot self-pings every 4 minutes (extra safety on top of UptimeRobot) |
| 🔓 Unban Fixed | One-click "Unban Now" works + sends user the **rejoin link you set** with `/setrejoinlink` (set once per group) |
| 🎯 Appeals → Group Owner | Ban alerts & appeals go to the **premium user** (group owner), not the bot owner |
| 🔁 No Duplicate Messages | Strong deduplication: same user can't trigger two ban alerts within 60 sec |
| 🔧 `/transferowner` | Bot owner can re-assign legacy groups to the correct premium user |
| ⚙️ render.yaml fix | `bot:web_app` (was wrongly `bot:web`) + added `RENDER_EXTERNAL_URL` |

---

## What's New in v2.0

| Feature | Detail |
|---------|--------|
| 📢 Log Channel | Every ban/unban logged to your private channel |
| 📋 Whitelist | Exempt specific users from auto-ban |
| 📅 Auto Schedule | Bot auto-checks members every X hours |
| 📩 Ban Appeal | Banned users can submit appeals — you decide via buttons |
| 👥 Member Tracking | Bot tracks joins/leaves for accurate checkall |
| ⚠️ Member Alert | Get notified when group drops below X members |
| 🎛️ Inline Menu | `/menu` — full control panel with tap buttons |
| 🌐 English UI | Professional interface with consistent emoji styling |

---

## BotFather Command Menu

Go to [@BotFather](https://t.me/BotFather) → `/mybots` → Your Bot → Edit Bot → Edit Commands
Copy-paste this exactly:

Long commands have a shorter alias. Long form still works too.

```
start - Bot info and your panel
help - Help and commands
menu - Open interactive control panel
mycheck - Check your membership status
rules - View required chats
setup - Activate bot in your group (Premium)
addchat - Add a monitored chat (Premium)
rmchat - Remove a monitored chat (Premium)
listchats - List monitored chats (Premium)
whitelist - Whitelist a user (Premium)
unwlist - Remove user from whitelist (Premium)
setlog - Set a log channel (Premium)
setlink - Save fixed rejoin link (Premium)
setsched - Set auto-check interval (Premium)
setmin - Set min-members alert (Premium)
checkall - Check all members & ban offenders (Premium)
unban - Unban a user (Premium)
mystats - Group statistics (Premium)
addprem - Grant premium to user (Owner)
rmprem - Revoke premium (Owner)
listprem - List all premium users (Owner)
botstats - Full bot statistics (Owner)
broadcast - Broadcast to premium users (Owner)
transfer - Transfer group ownership (Owner)
```

---

## Deploy Guide

### Step 1 — MongoDB Atlas (Free)

1. Sign up at [mongodb.com/atlas](https://www.mongodb.com/atlas)
2. **Build a Database** → **M0 Free**
3. Create a username and password
4. **Network Access** → Add IP Address → **Allow Access from Anywhere** (`0.0.0.0/0`)
5. **Connect** → **Drivers** → Copy connection string
6. Add `/guard_bot` before the `?` in the string:

```
mongodb+srv://user:pass@cluster.mongodb.net/guard_bot?retryWrites=true&w=majority
```

This is your `MONGO_URI`.

---

### Step 2 — Get Your Info

| Item | How to Get |
|------|-----------|
| `BOT_TOKEN` | [@BotFather](https://t.me/BotFather) → `/newbot` |
| `OWNER_ID` | Message [@userinfobot](https://t.me/userinfobot) → copy the **Id** number |

---

### Step 3 — GitHub Repo

Create a new GitHub repo and upload:
- `bot.py`
- `requirements.txt`
- `render.yaml`

---

### Step 4 — Render Deploy

1. Sign up at [render.com](https://render.com)
2. **New +** → **Web Service** → Connect GitHub repo
3. Settings:
   - Environment: `Python 3`
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `python bot.py`
4. Add **Environment Variables**:

| Key | Value |
|-----|-------|
| `BOT_TOKEN` | Your bot token |
| `OWNER_ID` | Your Telegram user ID number |
| `MONGO_URI` | MongoDB Atlas connection string |
| `RENDER_EXTERNAL_URL` | Auto-filled by render.yaml — leave blank, Render fills it |

> ⚠️ If you do **NOT** use the included `render.yaml` (Blueprint deploy), then
> manually add `RENDER_EXTERNAL_URL = https://your-app.onrender.com`
> (no trailing slash) — this enables webhook mode and the keep-alive ping.

5. **Create Web Service** → Deploy!

---

### Step 5 — 24/7 Uptime (UptimeRobot Free)

1. Sign up at [uptimerobot.com](https://uptimerobot.com)
2. **New Monitor** → HTTP(s)
3. URL: `https://your-app.onrender.com`
4. Interval: **5 minutes** → Save

Bot will stay online 24/7.

---

## How to Use — Owner

After deploying, start the bot → you'll see the Owner Panel.

**Give premium to someone:**
```
/addpremium 123456789        ← Lifetime
/addpremium 123456789 30     ← 30 days
```

They'll get a DM with setup instructions automatically.

---

## How to Use — Premium User

After receiving premium, follow these steps:

```
1. Add the bot to your group
2. Make the bot Admin → enable "Ban Members" permission
3. Send /setup in your group
4. Add your channels: /addchat -100xxxxxxxxxx  (repeat for each)
5. Optional: /setlog <log_channel_id>
6. Optional: /setschedule 6  (auto-check every 6 hours)
7. Use /menu for the full control panel
```

---

## Ban Appeal Flow

When a user is banned, they receive a DM with a **"📩 Submit Appeal"** button.

1. User taps the button
2. Bot asks for their reason
3. User types their reason
4. **Owner receives this DM** with two buttons: **✅ Unban** / **❌ Reject**
5. Owner taps a button → action is taken, user is notified

---

## How to Find a Chat ID

**Method 1:** Add [@userinfobot](https://t.me/userinfobot) to the group/channel temporarily

**Method 2:** Forward a message from the chat to [@JsonDumpBot](https://t.me/JsonDumpBot) → look for `chat.id`

**Method 3:** Telegram Web → open group → the number in the URL (add `-100` prefix)

---

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `BOT_TOKEN` | ✅ Yes | Telegram bot token from BotFather |
| `OWNER_ID` | ✅ Yes | Your Telegram user ID (number) |
| `MONGO_URI` | ✅ Yes | MongoDB Atlas connection string |

---

## Local Testing

```bash
pip install -r requirements.txt
cp .env.example .env
# Fill in BOT_TOKEN, OWNER_ID, MONGO_URI in .env
python bot.py
```

---

## Commands Reference

### 👑 Owner Commands

| Command (alias)               | Description |
|-------------------------------|-------------|
| `/addpremium` · `/addprem`    | Grant premium (lifetime or N days) |
| `/removepremium` · `/rmprem`  | Revoke premium |
| `/listpremium` · `/listprem`  | List all premium users |
| `/botstats`                   | Full statistics |
| `/broadcast`                  | Message all premium users |
| `/transferowner` · `/transfer`| Re-assign a group to a premium user |
| `/menu`                       | Owner control panel |

### 💎 Premium Commands (use in group)

| Command (alias)               | Description |
|-------------------------------|-------------|
| `/setup`                      | Activate bot in this group |
| `/addchat`                    | Add a monitored chat |
| `/removechat` · `/rmchat`     | Remove a monitored chat |
| `/listchats`                  | List monitored chats |
| `/whitelist`                  | Exempt user from auto-ban |
| `/unwhitelist` · `/unwlist`   | Remove from whitelist |
| `/setlog`                     | Set log channel |
| `/setrejoinlink` · `/setlink` | Save a fixed rejoin invite link |
| `/setschedule` · `/setsched`  | Set auto-check interval |
| `/setminmembers` · `/setmin`  | Set member-count alert |
| `/checkall`                   | Manual check + ban |
| `/unbanuser` · `/unban`       | Unban a user |
| `/mystats`                    | Your statistics |
| `/menu`                       | Group control panel |

### 👤 Member Commands

| Command   | Description |
|-----------|-------------|
| `/mycheck`| Check your membership |
| `/rules`  | View required chats |
| `/start`  | Bot info |
| `/help`   | Help & commands |

> ℹ️ Long form aur alias dono kaam karte hain — jo aasaan lage use kar lo.
