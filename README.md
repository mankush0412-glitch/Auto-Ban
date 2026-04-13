# 🛡️ Lecture Guard Bot

Telegram bot jo lecture group ke members ko monitor karta hai.
Agar koi member kisi bhi monitored group ya channel se leave kare, use lecture group se **automatically ban** kar diya jata hai.

---

## Kaise Kaam Karta Hai

1. Bot ko lecture group aur saare monitored groups/channels me admin banao
2. Bot ko `/setlecturegroup` command se lecture group set karo (sirf ek baar)
3. `/addchat` se kitne bhi groups/channels add karo monitor karne ke liye
4. Ab agar koi member kisi monitored chat se leave kare → **auto ban** from lecture group

---

## Setup Guide (Step by Step)

### Step 1: Bot Banana

1. Telegram pe [@BotFather](https://t.me/BotFather) open karo
2. `/newbot` likho
3. Bot ka naam aur username set karo
4. Jo **Token** mile usse copy karo — ye hi `BOT_TOKEN` hai

### Step 2: Bot Ko Sabhi Groups Me Add Karo + Admin Banao

**Lecture Group me:**
- Bot add karo
- Admin banao with permissions: ✅ Ban users, ✅ Read messages

**Har Monitored Group/Channel me bhi:**
- Bot add karo
- Admin banao (Read messages permission zaroori)

### Step 3: Render Pe Deploy (Free)

#### Option A — render.yaml se (Recommended)

1. [render.com](https://render.com) pe free account banao
2. GitHub pe ek **new repository** banao
3. Is folder ki saari files (`bot.py`, `requirements.txt`, `render.yaml`) us repo me upload karo
4. Render pe jao → **"New +"** → **"Blueprint"**
5. Apna GitHub repo connect karo
6. Environment variable set karo:
   - `BOT_TOKEN` = BotFather ka token
7. **Deploy!**

#### Option B — Manual Worker

1. Render pe **"New +"** → **"Background Worker"**
2. GitHub repo connect karo
3. Settings:
   - **Environment:** Python 3
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `python bot.py`
4. **Environment Variables** me sirf ek set karo:
   - `BOT_TOKEN` = aapka bot token
5. Deploy karo

### Step 4: Lecture Group Set Karo (Telegram Se)

Bot deploy hone ke baad:

1. Bot ko **private chat** me `/start` karo → aap owner ban jaoge
2. Apne **lecture group** me jao aur ye command do:
   ```
   /setlecturegroup
   ```
   Bot confirm karega ki lecture group set ho gaya!

### Step 5: Monitored Chats Add Karo

Lecture group ya private chat me:
```
/addchat -1001234567890
```
Jitne bhi groups/channels chahiye utne add karo.

**Group/Channel ID kaise pata kare:**
- [@userinfobot](https://t.me/userinfobot) ko group me add karo — woh ID bata dega
- Ya Telegram Web pe group open karo, URL me number dikhe usmein `-100` prefix lagao

---

## Commands

### Admin Commands (Sirf lecture group admins)

| Command | Kya Karta Hai |
|---------|---------------|
| `/setlecturegroup` | Is group ko lecture group set karo |
| `/setlecturegroup <id>` | Kisi specific group ID ko lecture group set karo |
| `/addchat <chat_id>` | Monitor me group/channel add karo |
| `/removechat <chat_id>` | Monitor se hatao |
| `/listchats` | Saare monitored chats dikhao |
| `/checkall` | Abhi saare members manually check karo + ban karo |
| `/status` | Bot status (lecture group, monitored chats, total bans) |
| `/unbanuser <user_id>` | Kisi ko unban karo |

### Member Commands (Sab use kar sakte hain)

| Command | Kya Karta Hai |
|---------|---------------|
| `/start` | Bot ki jankari |
| `/mycheck` | Apna membership status check karo |
| `/rules` | Group rules aur monitored chats dekho |

---

## Important Notes

- **Sirf ek env variable chahiye:** `BOT_TOKEN`
- Lecture group bhi Telegram commands se set hota hai — koi aur variable nahi
- Render free tier pe bot 24/7 chalta hai (Background Worker)
- Config aur monitored chats `data.json` me save hote hain
- Render restart pe `data.json` delete ho sakti hai — agar aisa ho toh `/setlecturegroup` aur `/addchat` dobara do
- Permanent storage ke liye Render Disk attach kar sakte ho (free plan me 1GB available)

---

## Local Testing

```bash
pip install -r requirements.txt
cp .env.example .env
# .env me BOT_TOKEN daalo
python bot.py
```
