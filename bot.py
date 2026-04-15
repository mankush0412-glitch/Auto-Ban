"""
╔══════════════════════════════════════════════╗
║      GUARD BOT — Public Multi-Tenant Bot     ║
║  Owner → Premium Users → Their Own Groups    ║
║  Storage: MongoDB Atlas (Persistent)         ║
╚══════════════════════════════════════════════╝
"""

import os
import asyncio
import logging
import threading
import time
from datetime import datetime, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler

from pymongo import MongoClient
from pymongo.errors import PyMongoError

from telegram import Update, ChatMember
from telegram.ext import (
    Application,
    CommandHandler,
    ChatMemberHandler,
    ContextTypes,
)
from telegram.error import TelegramError

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

BOT_TOKEN  = os.environ.get("BOT_TOKEN", "")
OWNER_ID   = int(os.environ.get("OWNER_ID", "0"))
MONGO_URI  = os.environ.get("MONGO_URI", "")
PORT       = int(os.environ.get("PORT", 8080))


# ══════════════════════════════════════════════
# MONGODB SETUP
# ══════════════════════════════════════════════

def connect_mongo():
    if not MONGO_URI:
        logger.error("MONGO_URI set nahi hai!")
        raise RuntimeError("MONGO_URI missing")
    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=8000)
    client.admin.command("ping")
    logger.info("MongoDB connected!")
    return client


mongo_client = connect_mongo()
mongo_db     = mongo_client["guard_bot"]

col_config   = mongo_db["config"]         # single document {_id: "main", ...}
col_premium  = mongo_db["premium_users"]  # one doc per user {_id: user_id, ...}
col_groups   = mongo_db["groups"]         # one doc per group {_id: group_id, ...}
col_bans     = mongo_db["banned_log"]     # one doc per ban event


# ── Config (owner etc.) ──────────────────────

def get_config() -> dict:
    doc = col_config.find_one({"_id": "main"}) or {}
    return doc


def set_config_field(key: str, value):
    col_config.update_one({"_id": "main"}, {"$set": {key: value}}, upsert=True)


# ── Premium ──────────────────────────────────

def get_premium(uid: int) -> dict | None:
    return col_premium.find_one({"_id": uid})


def set_premium(uid: int, data: dict):
    col_premium.update_one({"_id": uid}, {"$set": data}, upsert=True)


def delete_premium(uid: int):
    col_premium.delete_one({"_id": uid})


def all_premium() -> list:
    return list(col_premium.find())


# ── Groups ───────────────────────────────────

def get_group(gid: int) -> dict | None:
    return col_groups.find_one({"_id": gid})


def set_group(gid: int, data: dict):
    col_groups.update_one({"_id": gid}, {"$set": data}, upsert=True)


def all_groups() -> list:
    return list(col_groups.find())


def increment_ban_count(gid: int):
    col_groups.update_one({"_id": gid}, {"$inc": {"ban_count": 1}}, upsert=True)


# ── Bans ─────────────────────────────────────

def log_ban(entry: dict):
    col_bans.insert_one(entry)


def total_bans() -> int:
    return col_bans.count_documents({})


def bans_for_group(gid: int) -> int:
    return col_bans.count_documents({"group_id": gid})


# ══════════════════════════════════════════════
# PERMISSION HELPERS
# ══════════════════════════════════════════════

def now_ts() -> int:
    return int(datetime.now(timezone.utc).timestamp())


def fmt_ts(ts) -> str:
    if not ts:
        return "♾️ Lifetime"
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%d %b %Y")


def is_owner(uid: int) -> bool:
    if OWNER_ID and uid == OWNER_ID:
        return True
    cfg = get_config()
    return cfg.get("bot_owner_id") == uid


def is_premium(uid: int) -> bool:
    doc = get_premium(uid)
    if not doc:
        return False
    exp = doc.get("expires")
    if exp and exp < now_ts():
        return False
    return True


async def is_group_admin(context, gid: int, uid: int) -> bool:
    try:
        m = await context.bot.get_chat_member(gid, uid)
        return m.status in [ChatMember.ADMINISTRATOR, ChatMember.OWNER]
    except TelegramError:
        return False


async def can_manage_group(context, gid: int, uid: int) -> bool:
    g = get_group(gid)
    if g and g.get("owner_id") == uid:
        return True
    return await is_group_admin(context, gid, uid)


# ══════════════════════════════════════════════
# KEEP-ALIVE HTTP SERVER
# ══════════════════════════════════════════════

class PingHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        prem_count  = col_premium.count_documents({})
        group_count = col_groups.count_documents({})
        ban_count   = total_bans()
        self.wfile.write(
            f"Guard Bot alive | Premium: {prem_count} | Groups: {group_count} | Bans: {ban_count}".encode()
        )

    def log_message(self, *args):
        pass


def start_keepalive():
    def _run():
        HTTPServer(("0.0.0.0", PORT), PingHandler).serve_forever()
    threading.Thread(target=_run, daemon=True).start()
    logger.info(f"Keep-alive on port {PORT}")


# ══════════════════════════════════════════════
# BAN HELPER — DM + Ban + Log
# ══════════════════════════════════════════════

async def do_ban(context, uid: int, uname: str, gid: int, gname: str, reason: str) -> bool:
    # 1. DM the user
    try:
        await context.bot.send_message(
            chat_id=uid,
            text=(
                "🚫 *Aapko ban kar diya gaya!*\n\n"
                f"📌 *Group:* {gname}\n"
                f"❌ *Reason:* `{reason}` se aapne leave kiya\n\n"
                "Wapas join karne ke liye group admin se contact karo.\n"
                "📋 Pehle saare required chats join karo, fir admin se request karo."
            ),
            parse_mode="Markdown",
        )
    except TelegramError:
        pass

    # 2. Ban
    try:
        await context.bot.ban_chat_member(gid, uid)
    except TelegramError as e:
        logger.error(f"Ban failed {uid} in {gid}: {e}")
        return False

    # 3. Update DB
    increment_ban_count(gid)
    log_ban({
        "user_id": uid, "user_name": uname,
        "group_id": gid, "group_name": gname,
        "reason": reason, "time": now_ts(),
    })

    # 4. Notify group
    try:
        await context.bot.send_message(
            gid,
            f"🚫 *{uname}* ko ban kiya gaya\n📍 Reason: *{reason}* se leave kiya",
            parse_mode="Markdown",
        )
    except TelegramError:
        pass

    logger.info(f"Banned {uid} ({uname}) from {gid} for leaving {reason}")
    return True


# ══════════════════════════════════════════════
# /start  /help
# ══════════════════════════════════════════════

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid  = update.effective_user.id
    chat = update.effective_chat

    # Ensure owner is set from env
    if OWNER_ID:
        cfg = get_config()
        if cfg.get("bot_owner_id") != OWNER_ID:
            set_config_field("bot_owner_id", OWNER_ID)

    if not OWNER_ID and not get_config().get("bot_owner_id"):
        await update.message.reply_text(
            "⚠️ Bot configure nahi hua.\n`OWNER_ID` env variable set karo.",
            parse_mode="Markdown",
        )
        return

    # ── Group chat ──────────────────────────
    if chat.type in ["group", "supergroup"]:
        gid = chat.id
        g   = get_group(gid)
        perm = is_premium(uid) or is_owner(uid)

        if not g:
            if perm:
                await update.message.reply_text(
                    "⚙️ Ye group setup nahi hua.\nSetup karne ke liye: `/setup`",
                    parse_mode="Markdown",
                )
            else:
                await update.message.reply_text("ℹ️ Is group me bot active nahi hai.")
            return

        mc = g.get("monitored_chats", {})
        await update.message.reply_text(
            f"🛡️ *Guard Bot — Active*\n\n"
            f"👁️ Monitored Chats: *{len(mc)}*\n"
            f"🚫 Total Bans: *{g.get('ban_count', 0)}*\n\n"
            "`/mycheck` — Apna status\n`/rules` — Rules dekho",
            parse_mode="Markdown",
        )
        return

    # ── Private chat ────────────────────────
    prem_list  = all_premium()
    group_list = all_groups()
    total      = total_bans()

    if is_owner(uid):
        await update.message.reply_text(
            f"👑 *Guard Bot — Owner Panel*\n\n"
            f"💎 Premium Users: *{len(prem_list)}*\n"
            f"👥 Active Groups: *{len(group_list)}*\n"
            f"🚫 Total Bans: *{total}*\n\n"
            "🔐 *Owner Commands:*\n"
            "`/addpremium <id> [days]` — Premium do\n"
            "`/removepremium <id>` — Premium hatao\n"
            "`/listpremium` — Users dekho\n"
            "`/botstats` — Full stats\n"
            "`/broadcast <msg>` — Sab ko message\n\n"
            "💎 *Premium commands bhi available hain*",
            parse_mode="Markdown",
        )
    elif is_premium(uid):
        pdata     = get_premium(uid) or {}
        my_groups = [g for g in group_list if g.get("owner_id") == uid]
        grp_lines = "\n".join(f"  • *{g['name']}*" for g in my_groups) or "  (koi group nahi)"
        await update.message.reply_text(
            f"💎 *Guard Bot — Premium Panel*\n\n"
            f"📅 Expires: {fmt_ts(pdata.get('expires'))}\n"
            f"👥 Aapke Groups: *{len(my_groups)}*\n{grp_lines}\n\n"
            "📋 *Commands:*\n"
            "`/setup` — Group me bot setup karo\n"
            "`/addchat <id>` — Monitored chat add\n"
            "`/removechat <id>` — Chat hatao\n"
            "`/listchats` — Chats dekho\n"
            "`/checkall` — Members check + ban\n"
            "`/unbanuser <id>` — Unban karo\n"
            "`/mystats` — Aapka stats",
            parse_mode="Markdown",
        )
    else:
        await update.message.reply_text(
            "🛡️ *Guard Bot*\n\n"
            "Ye group protection bot hai.\n\n"
            "Agar aap kisi active group me ho:\n"
            "`/mycheck` — Apna membership status\n"
            "`/rules` — Required chats dekho\n\n"
            "Premium ke liye bot owner se contact karo.",
            parse_mode="Markdown",
        )


# ══════════════════════════════════════════════
# OWNER COMMANDS
# ══════════════════════════════════════════════

async def cmd_addpremium(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_owner(uid):
        await update.message.reply_text("❌ Sirf bot owner.")
        return
    if not context.args:
        await update.message.reply_text(
            "Usage:\n"
            "`/addpremium <user_id>` — Lifetime\n"
            "`/addpremium <user_id> 30` — 30 din",
            parse_mode="Markdown",
        )
        return
    try:
        target_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Invalid user ID.")
        return

    days    = int(context.args[1]) if len(context.args) > 1 else None
    expires = now_ts() + days * 86400 if days else None

    try:
        tuser = await context.bot.get_chat(target_id)
        uname = tuser.full_name or str(target_id)
        uhandle = f"@{tuser.username}" if tuser.username else "—"
    except TelegramError:
        uname, uhandle = str(target_id), "—"

    set_premium(target_id, {
        "name": uname, "username": uhandle,
        "expires": expires, "added_on": now_ts(), "added_by": uid,
    })

    exp_text = f"{days} din" if days else "Lifetime"
    await update.message.reply_text(
        f"✅ *Premium diya!*\n\n"
        f"👤 *{uname}* (`{target_id}`)\n"
        f"📅 Validity: *{exp_text}* | Expires: {fmt_ts(expires)}",
        parse_mode="Markdown",
    )

    try:
        await context.bot.send_message(
            target_id,
            f"🎉 *Aapko Premium mil gaya!*\n\n"
            f"📅 Validity: *{exp_text}*\n\n"
            "Ab apne group me bot lagao:\n"
            "1️⃣ Bot ko group me add karo\n"
            "2️⃣ Bot ko Admin banao (Ban users permission)\n"
            "3️⃣ Group me `/setup` karo\n"
            "4️⃣ `/addchat <chat_id>` se chats add karo",
            parse_mode="Markdown",
        )
    except TelegramError:
        pass


async def cmd_removepremium(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_owner(uid):
        await update.message.reply_text("❌ Sirf bot owner.")
        return
    if not context.args:
        await update.message.reply_text("Usage: `/removepremium <user_id>`", parse_mode="Markdown")
        return
    try:
        target_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Invalid ID.")
        return

    doc = get_premium(target_id)
    if not doc:
        await update.message.reply_text("❌ Ye user premium me nahi hai.")
        return

    name = doc.get("name", str(target_id))
    delete_premium(target_id)
    await update.message.reply_text(f"✅ *{name}* ka premium hata diya.", parse_mode="Markdown")
    try:
        await context.bot.send_message(
            target_id,
            "⚠️ *Aapka premium expire ho gaya.*\nBot ab aapke groups me kaam nahi karega.",
            parse_mode="Markdown",
        )
    except TelegramError:
        pass


async def cmd_listpremium(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_owner(uid):
        await update.message.reply_text("❌ Sirf bot owner.")
        return

    prem = all_premium()
    if not prem:
        await update.message.reply_text("📋 Koi premium user nahi hai.")
        return

    lines = [f"💎 *Premium Users ({len(prem)}):*\n"]
    for doc in prem:
        exp  = doc.get("expires")
        tag  = "⛔ Expired" if (exp and exp < now_ts()) else fmt_ts(exp)
        name = doc.get("name", str(doc["_id"]))
        uh   = doc.get("username", "—")
        lines.append(f"• *{name}* {uh}\n  ID: `{doc['_id']}` | {tag}")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def cmd_botstats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_owner(uid):
        await update.message.reply_text("❌ Sirf bot owner.")
        return

    prem_list  = all_premium()
    group_list = all_groups()
    active_p   = sum(1 for d in prem_list if not d.get("expires") or d["expires"] > now_ts())

    grp_lines = []
    for g in group_list:
        mc = g.get("monitored_chats", {})
        grp_lines.append(f"  • *{g['name']}* — {len(mc)} chats, {g.get('ban_count', 0)} bans")

    await update.message.reply_text(
        f"📊 *Bot Statistics*\n\n"
        f"💎 Premium Users: *{len(prem_list)}* (active: {active_p})\n"
        f"👥 Groups: *{len(group_list)}*\n"
        f"🚫 Total Bans Ever: *{total_bans()}*\n\n"
        + ("*Groups:*\n" + "\n".join(grp_lines) if grp_lines else "No groups yet."),
        parse_mode="Markdown",
    )


async def cmd_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_owner(uid):
        await update.message.reply_text("❌ Sirf bot owner.")
        return
    if not context.args:
        await update.message.reply_text("Usage: `/broadcast <message>`", parse_mode="Markdown")
        return

    msg = " ".join(context.args)
    sent, failed = 0, 0
    for doc in all_premium():
        try:
            await context.bot.send_message(
                doc["_id"],
                f"📢 *Bot Owner ka Message:*\n\n{msg}",
                parse_mode="Markdown",
            )
            sent += 1
        except TelegramError:
            failed += 1

    await update.message.reply_text(
        f"✅ Broadcast done!\nSent: {sent} | Failed: {failed}",
        parse_mode="Markdown",
    )


# ══════════════════════════════════════════════
# PREMIUM / GROUP SETUP COMMANDS
# ══════════════════════════════════════════════

async def cmd_setup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid  = update.effective_user.id
    chat = update.effective_chat

    if not (is_premium(uid) or is_owner(uid)):
        await update.message.reply_text(
            "❌ Bot setup ke liye *premium* chahiye.\nOwner se contact karo.",
            parse_mode="Markdown",
        )
        return
    if chat.type not in ["group", "supergroup"]:
        await update.message.reply_text("⚠️ `/setup` group me use karo.", parse_mode="Markdown")
        return

    gid = chat.id
    g   = get_group(gid)

    if g and g.get("owner_id") != uid and not is_owner(uid):
        await update.message.reply_text("❌ Ye group kisi aur ne setup kiya hua hai.")
        return

    try:
        bm = await context.bot.get_chat_member(gid, context.bot.id)
        if bm.status != ChatMember.ADMINISTRATOR:
            await update.message.reply_text(
                "⚠️ Bot ko pehle *Admin* banao (Ban users permission), fir `/setup` karo.",
                parse_mode="Markdown",
            )
            return
    except TelegramError:
        pass

    if g:
        set_group(gid, {"name": chat.title})
        await update.message.reply_text(
            f"✅ *{chat.title}* already setup hai.\n\n`/addchat <id>` se chats manage karo.",
            parse_mode="Markdown",
        )
        return

    set_group(gid, {
        "name": chat.title, "owner_id": uid,
        "monitored_chats": {}, "ban_count": 0, "setup_on": now_ts(),
    })
    await update.message.reply_text(
        f"✅ *{chat.title}* setup ho gaya!\n\n"
        "Ab monitored chats add karo:\n`/addchat <chat_id>`",
        parse_mode="Markdown",
    )


async def cmd_addchat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid  = update.effective_user.id
    chat = update.effective_chat
    gid  = chat.id

    if not (is_premium(uid) or is_owner(uid)):
        return
    if chat.type not in ["group", "supergroup"]:
        await update.message.reply_text("⚠️ Group me use karo.")
        return

    g = get_group(gid)
    if not g:
        await update.message.reply_text("❌ Pehle `/setup` karo.", parse_mode="Markdown")
        return
    if not await can_manage_group(context, gid, uid):
        await update.message.reply_text("❌ Permission nahi hai.")
        return
    if not context.args:
        await update.message.reply_text("Usage: `/addchat <chat_id>`", parse_mode="Markdown")
        return

    try:
        cid = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Invalid ID.")
        return

    mc = g.get("monitored_chats", {})
    if str(cid) in mc:
        await update.message.reply_text(f"✅ Pehle se monitor ho raha hai: `{cid}`", parse_mode="Markdown")
        return

    try:
        tchat = await context.bot.get_chat(cid)
        mc[str(cid)] = {"name": tchat.title, "type": tchat.type}
        set_group(gid, {"monitored_chats": mc})
        await update.message.reply_text(
            f"✅ *{tchat.title}* monitor me add!\n\nLeave karne par → auto ban.",
            parse_mode="Markdown",
        )
    except TelegramError as e:
        await update.message.reply_text(
            f"❌ Chat access nahi hua. Bot wahan bhi admin hona chahiye.\n`{e}`",
            parse_mode="Markdown",
        )


async def cmd_removechat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid  = update.effective_user.id
    chat = update.effective_chat
    gid  = chat.id

    if not (is_premium(uid) or is_owner(uid)):
        return
    if chat.type not in ["group", "supergroup"]:
        return
    g = get_group(gid)
    if not g:
        await update.message.reply_text("❌ Pehle `/setup` karo.", parse_mode="Markdown")
        return
    if not await can_manage_group(context, gid, uid):
        await update.message.reply_text("❌ Permission nahi.")
        return
    if not context.args:
        await update.message.reply_text("Usage: `/removechat <chat_id>`", parse_mode="Markdown")
        return
    try:
        cid = str(int(context.args[0]))
    except ValueError:
        await update.message.reply_text("❌ Invalid ID.")
        return

    mc = g.get("monitored_chats", {})
    if cid not in mc:
        await update.message.reply_text(f"❌ `{cid}` monitor me nahi hai.", parse_mode="Markdown")
        return

    name = mc[cid].get("name", cid)
    del mc[cid]
    set_group(gid, {"monitored_chats": mc})
    await update.message.reply_text(f"✅ *{name}* monitor se hata diya.", parse_mode="Markdown")


async def cmd_listchats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid  = update.effective_user.id
    chat = update.effective_chat

    if chat.type in ["group", "supergroup"]:
        g = get_group(chat.id)
        if not g:
            await update.message.reply_text("❌ Bot setup nahi hua.")
            return
        mc    = g.get("monitored_chats", {})
        lines = [f"👁️ *Monitored Chats — {g['name']}*\n"]
        if mc:
            for cid, info in mc.items():
                icon = "📢" if "channel" in info.get("type", "") else "👥"
                lines.append(f"{icon} *{info['name']}*\n   ID: `{cid}`")
        else:
            lines.append("Koi monitored chat nahi.\n`/addchat <id>` se add karo.")
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
    else:
        if not (is_premium(uid) or is_owner(uid)):
            return
        my_groups = [g for g in all_groups() if g.get("owner_id") == uid]
        if not my_groups:
            await update.message.reply_text("Aapka koi group setup nahi.")
            return
        for g in my_groups:
            mc    = g.get("monitored_chats", {})
            lines = [f"👥 *{g['name']}* — {len(mc)} chats\n"]
            for cid, info in mc.items():
                icon = "📢" if "channel" in info.get("type", "") else "👥"
                lines.append(f"  {icon} {info['name']} (`{cid}`)")
            await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def cmd_checkall(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid  = update.effective_user.id
    chat = update.effective_chat
    gid  = chat.id

    if chat.type not in ["group", "supergroup"]:
        await update.message.reply_text("⚠️ Group me use karo.")
        return
    g = get_group(gid)
    if not g:
        await update.message.reply_text("❌ Bot setup nahi hua.")
        return
    if not await can_manage_group(context, gid, uid):
        await update.message.reply_text("❌ Sirf admins.")
        return

    mc = g.get("monitored_chats", {})
    if not mc:
        await update.message.reply_text("❌ Koi monitored chat nahi hai.")
        return

    msg = await update.message.reply_text("⏳ Members check ho rahe hain...")
    checked, banned_count = 0, 0

    try:
        members = []
        async for m in context.bot.get_chat_members(gid):
            if not m.user.is_bot and m.status not in [ChatMember.LEFT, ChatMember.BANNED]:
                members.append(m.user)
    except TelegramError as e:
        await msg.edit_text(f"❌ Members nahi mile: {e}")
        return

    for user in members:
        checked += 1
        ban_reason = None
        for cid, info in mc.items():
            try:
                cm = await context.bot.get_chat_member(int(cid), user.id)
                if cm.status in [ChatMember.LEFT, ChatMember.BANNED]:
                    ban_reason = info.get("name", cid)
                    break
            except TelegramError:
                pass
        if ban_reason:
            ok = await do_ban(context, user.id, user.full_name, gid, g["name"], ban_reason)
            if ok:
                banned_count += 1

    await msg.edit_text(
        f"✅ *Check Complete!*\n\n"
        f"👥 Checked: `{checked}`\n🚫 Banned: `{banned_count}`\n\n"
        "Har banned user ko DM bhi gaya.",
        parse_mode="Markdown",
    )


async def cmd_unbanuser(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid  = update.effective_user.id
    chat = update.effective_chat
    gid  = chat.id

    if chat.type not in ["group", "supergroup"]:
        await update.message.reply_text("⚠️ Group me use karo.")
        return
    g = get_group(gid)
    if not g:
        await update.message.reply_text("❌ Bot setup nahi hua.")
        return
    if not await can_manage_group(context, gid, uid):
        await update.message.reply_text("❌ Permission nahi.")
        return
    if not context.args:
        await update.message.reply_text("Usage: `/unbanuser <user_id>`", parse_mode="Markdown")
        return
    try:
        target = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Invalid ID.")
        return

    try:
        await context.bot.unban_chat_member(gid, target)
        await update.message.reply_text(f"✅ User `{target}` unban ho gaya.", parse_mode="Markdown")
        try:
            await context.bot.send_message(
                target,
                f"✅ *Aapka ban hata liya gaya!*\n\nGroup: *{g['name']}*\n\n"
                "Wapas join kar sakte ho — pehle required chats join karo!",
                parse_mode="Markdown",
            )
        except TelegramError:
            pass
    except TelegramError as e:
        await update.message.reply_text(f"❌ Unban nahi ho paya: {e}")


async def cmd_mystats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not (is_premium(uid) or is_owner(uid)):
        return

    my_groups   = [g for g in all_groups() if g.get("owner_id") == uid]
    total_b     = sum(g.get("ban_count", 0) for g in my_groups)
    pdata       = get_premium(uid) or {}

    lines = [f"📊 *Aapka Stats*\n",
             f"👥 Groups: *{len(my_groups)}* | 🚫 Total Bans: *{total_b}*\n"]
    for g in my_groups:
        mc = g.get("monitored_chats", {})
        lines.append(
            f"📌 *{g['name']}*\n"
            f"   Monitored: {len(mc)} | Bans: {g.get('ban_count', 0)} | Setup: {fmt_ts(g.get('setup_on'))}"
        )

    if pdata:
        lines.append(f"\n💎 Premium expires: {fmt_ts(pdata.get('expires'))}")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


# ══════════════════════════════════════════════
# MEMBER COMMANDS
# ══════════════════════════════════════════════

async def cmd_mycheck(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid  = update.effective_user.id
    chat = update.effective_chat

    if chat.type not in ["group", "supergroup"]:
        await update.message.reply_text("⚠️ Group me use karo.")
        return
    g = get_group(chat.id)
    if not g:
        await update.message.reply_text("ℹ️ Is group me bot active nahi hai.")
        return

    mc     = g.get("monitored_chats", {})
    lines  = ["📋 *Aapka Membership Status*\n"]
    all_ok = True

    for cid, info in mc.items():
        name = info.get("name", cid)
        try:
            cm = await context.bot.get_chat_member(int(cid), uid)
            if cm.status in [ChatMember.LEFT, ChatMember.BANNED]:
                lines.append(f"❌ *{name}* — Join nahi kiya")
                all_ok = False
            else:
                lines.append(f"✅ *{name}* — Joined")
        except TelegramError:
            lines.append(f"⚠️ *{name}* — Check nahi hua")

    if not mc:
        lines.append("✅ Koi monitored chat nahi hai — safe hain!")
    elif all_ok:
        lines.append("\n🎉 Sab theek! Saare required chats me hain.")
    else:
        lines.append("\n⚠️ Missing chats jaldi join karo — ban ho sakte ho!")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def cmd_rules(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat.type not in ["group", "supergroup"]:
        await update.message.reply_text("⚠️ Group me use karo.")
        return
    g = get_group(chat.id)
    if not g:
        await update.message.reply_text("ℹ️ Is group me bot active nahi hai.")
        return

    mc    = g.get("monitored_chats", {})
    lines = [
        f"📜 *{g['name']} — Guard Rules*\n",
        "📌 Rule 1: Neeche diye saare chats me member rehna zaroori hai.",
        "📌 Rule 2: Kisi bhi required chat se leave karne par *is group se ban* hoga.",
        "📌 Rule 3: Ban hone par aapko personal DM milega.",
        "📌 Rule 4: Wapas join ke liye admin se contact karo.\n",
        "👁️ *Required Chats:*",
    ]
    if mc:
        for info in mc.values():
            icon = "📢" if "channel" in info.get("type", "") else "👥"
            lines.append(f"  {icon} *{info['name']}*")
    else:
        lines.append("  (Abhi koi required chat set nahi)")

    lines.append("\n`/mycheck` se apna status check karo.")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


# ══════════════════════════════════════════════
# AUTO BAN — Chat Member Handler
# ══════════════════════════════════════════════

async def on_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    result = update.chat_member
    if not result:
        return

    chat_id    = result.chat.id
    user       = result.new_chat_member.user
    new_status = result.new_chat_member.status
    old_status = result.old_chat_member.status if result.old_chat_member else None

    if user.is_bot:
        return

    was_member = old_status in [
        ChatMember.MEMBER, ChatMember.ADMINISTRATOR,
        ChatMember.OWNER, ChatMember.RESTRICTED,
    ]
    now_left = new_status in [ChatMember.LEFT, ChatMember.BANNED]
    if not (was_member and now_left):
        return

    # Check every group that monitors this chat
    for g in all_groups():
        gid = g["_id"]
        mc  = g.get("monitored_chats", {})

        if str(chat_id) not in mc:
            continue

        # Premium check for group owner
        owner_id = g.get("owner_id")
        if owner_id and not is_owner(owner_id) and not is_premium(owner_id):
            continue

        try:
            lm = await context.bot.get_chat_member(gid, user.id)
            if lm.status in [ChatMember.LEFT, ChatMember.BANNED]:
                continue
        except TelegramError:
            continue

        reason = mc[str(chat_id)].get("name", str(chat_id))
        await do_ban(context, user.id, user.full_name, gid, g["name"], reason)


# ══════════════════════════════════════════════
# MAIN — Async bot runner + restart loop
# ══════════════════════════════════════════════

async def run_bot_once():
    """Build app, register handlers, run polling until error/stop."""
    logger.info("Bot starting...")
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("addpremium",    cmd_addpremium))
    app.add_handler(CommandHandler("removepremium", cmd_removepremium))
    app.add_handler(CommandHandler("listpremium",   cmd_listpremium))
    app.add_handler(CommandHandler("botstats",      cmd_botstats))
    app.add_handler(CommandHandler("broadcast",     cmd_broadcast))

    app.add_handler(CommandHandler("setup",         cmd_setup))
    app.add_handler(CommandHandler("addchat",       cmd_addchat))
    app.add_handler(CommandHandler("removechat",    cmd_removechat))
    app.add_handler(CommandHandler("listchats",     cmd_listchats))
    app.add_handler(CommandHandler("checkall",      cmd_checkall))
    app.add_handler(CommandHandler("unbanuser",     cmd_unbanuser))
    app.add_handler(CommandHandler("mystats",       cmd_mystats))

    app.add_handler(CommandHandler("start",         cmd_start))
    app.add_handler(CommandHandler("help",          cmd_start))
    app.add_handler(CommandHandler("mycheck",       cmd_mycheck))
    app.add_handler(CommandHandler("rules",         cmd_rules))

    app.add_handler(ChatMemberHandler(on_chat_member, ChatMemberHandler.ANY_CHAT_MEMBER))

    async with app:
        await app.start()
        await app.updater.start_polling(
            allowed_updates=["message", "chat_member"],
            drop_pending_updates=True,
        )
        logger.info("Bot is running!")
        # Keep alive until KeyboardInterrupt or error
        while True:
            await asyncio.sleep(60)


def main():
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN set nahi hai!")
        return

    # Sync owner on startup
    if OWNER_ID:
        col_config.update_one(
            {"_id": "main"},
            {"$set": {"bot_owner_id": OWNER_ID}},
            upsert=True,
        )
        logger.info(f"Owner set: {OWNER_ID}")

    start_keepalive()

    # Restart loop — fresh event loop each time to avoid 'no current event loop' error
    while True:
        try:
            asyncio.run(run_bot_once())
        except KeyboardInterrupt:
            logger.info("Bot stopped by user.")
            break
        except Exception as e:
            logger.error(f"Crash: {e} — restarting in 5s...")
            time.sleep(5)


if __name__ == "__main__":
    main()
