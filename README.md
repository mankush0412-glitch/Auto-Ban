# 🛡️ Guard Bot — Public Multi-Tenant Telegram Bot

Owner → Premium Users → Unke Apne Groups — Sab alag alag!

Storage: **MongoDB Atlas (Free)** — Data kabhi wipe nahi hoga.

---

## Features

| Feature | Detail |
|---------|--------|
| 👑 Owner System | Env se permanent owner — restart pe bhi safe |
| 💎 Premium System | Lifetime ya fixed days (30/60/90...) |
| 👥 Multi-Group | Ek bot token pe unlimited groups |
| 🚫 Auto Ban | Real-time — leave karte hi ban |
| 📩 Ban DM | User ko reason ke saath personal message |
| ✅ Unban DM | Unban hone par bhi DM |
| 📊 Stats | Premium users + group stats |
| 📢 Broadcast | Saare premium users ko ek saath message |
| 🔄 Auto Restart | Crash proof — 5 sec me restart |
| 🌐 Keep-Alive | Render pe 24/7 online |
| 🍃 MongoDB | Persistent storage — restart pe data safe |

---

## Deploy Guide — Step by Step

### Step 1 — MongoDB Atlas Setup (Free)

1. [mongodb.com/atlas](https://www.mongodb.com/atlas) pe free account banao
2. **"Build a Database"** → **M0 Free** select karo
3. Username aur password set karo (yaad rakhna!)
4. Network Access → **"Allow Access from Anywhere"** (`0.0.0.0/0`)
5. Connect → **"Drivers"** → Connection string copy karo

Connection string kuch aisa dikhega:
```
mongodb+srv://myuser:mypassword@cluster0.abc123.mongodb.net/?retryWrites=true&w=majority
```

6. Is string me database name add karo — `/?` se pehle `/guard_bot` lagao:
```
mongodb+srv://myuser:mypassword@cluster0.abc123.mongodb.net/guard_bot?retryWrites=true&w=majority
```

Ye teri `MONGO_URI` hai.

---

### Step 2 — Bot Token Banao

1. [@BotFather](https://t.me/BotFather) open karo → `/newbot`
2. Naam aur username set karo → Token copy karo

---

### Step 3 — Apna Telegram ID Pata Karo (OWNER_ID)

1. [@userinfobot](https://t.me/userinfobot) ko Telegram pe `/start` karo
2. Woh aapka User ID number bata dega (e.g. `987654321`)
3. Ye `OWNER_ID` hai — username nahi, **number** chahiye

---

### Step 4 — GitHub Repo Banao

1. [github.com](https://github.com) pe new repository banao
2. Ye teen files upload karo:
   - `bot.py`
   - `requirements.txt`
   - `render.yaml`

---

### Step 5 — Render Pe Deploy

1. [render.com](https://render.com) pe free account banao
2. **New +** → **Web Service**
3. GitHub repo connect karo
4. Settings:
   - Environment: `Python 3`
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `python bot.py`
5. **Environment Variables** me ye teen add karo:

| Key | Value |
|-----|-------|
| `BOT_TOKEN` | BotFather ka token |
| `OWNER_ID` | Aapka Telegram User ID number |
| `MONGO_URI` | MongoDB Atlas connection string |

6. **Create Web Service** → Deploy!

---

### Step 6 — 100% Uptime (Free UptimeRobot)

1. [uptimerobot.com](https://uptimerobot.com) pe free account
2. **New Monitor** → HTTP(s)
3. URL: `https://your-app-name.onrender.com`
4. Interval: 5 minutes → Save

Ab bot kabhi band nahi hoga.

---

## Aap (Owner) Kya Kare

Bot deploy hone ke baad bot ko `/start` karo → seedha Owner panel milega.

Premium users add karo:
```
/addpremium 123456789          ← Lifetime
/addpremium 123456789 30       ← 30 din ke liye
```

Unhe automatically message jayega — aage ka sab kuch woh khud kar lenge.

---

## Premium User Kya Kare

Premium milne par ek guide message milega. Short steps:

```
1. Bot ko apne group me add karo
2. Bot ko Admin banao (Ban users permission de)
3. Group me type karo: /setup
4. Monitored chats add karo: /addchat <chat_id>
```

Done! Bot ab automatically kaam karega.

---

## Commands

### 👑 Owner Commands

| Command | Kaam |
|---------|------|
| `/addpremium <id>` | Lifetime premium do |
| `/addpremium <id> 30` | 30 din ke liye premium |
| `/removepremium <id>` | Premium wapas lo |
| `/listpremium` | Saare premium users |
| `/botstats` | Full bot statistics |
| `/broadcast <msg>` | Saare premium users ko message |

### 💎 Premium Commands (Group Me Use Karo)

| Command | Kaam |
|---------|------|
| `/setup` | Group me bot activate karo |
| `/addchat <id>` | Monitored chat add karo |
| `/removechat <id>` | Chat hatao |
| `/listchats` | Saare monitored chats |
| `/checkall` | Manual check + ban |
| `/unbanuser <id>` | Kisi ko unban karo |
| `/mystats` | Apna stats |

### 👤 Member Commands (Sab Log)

| Command | Kaam |
|---------|------|
| `/start` | Bot info |
| `/mycheck` | Apna membership status |
| `/rules` | Group rules aur required chats |

---

## Ban + DM System

**Jab ban hota hai, user ko ye DM milta hai:**
```
🚫 Aapko ban kar diya gaya!

📌 Group: [Group Name]
❌ Reason: [Chat Name] se aapne leave kiya

Wapas join ke liye admin se contact karo.
Pehle saare required chats join karo.
```

**Jab unban hota hai:**
```
✅ Aapka ban hata liya gaya!
Wapas join kar sakte ho — pehle required chats join karo!
```

> ⚠️ DM tab jaata hai jab user ne bot ko pehle `/start` kiya ho.
> Group me pin karo: "Saare members ek baar bot ko start karo: @YourBot"

---

## Group/Channel ID Kaise Pata Kare

**Method 1:** [@userinfobot](https://t.me/userinfobot) group me add karo

**Method 2:** Telegram Web → group URL me number → `-100` prefix lagao

**Method 3:** Message ko [@JsonDumpBot](https://t.me/JsonDumpBot) pe forward karo → `chat.id`

---

## Local Testing

```bash
pip install -r requirements.txt
cp .env.example .env
# .env me BOT_TOKEN, OWNER_ID, MONGO_URI fill karo
python bot.py
```
