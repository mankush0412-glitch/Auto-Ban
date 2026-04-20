"""
╔══════════════════════════════════════════════════╗
║       GUARD BOT — Professional Edition v2.0      ║
║   Owner → Premium Users → Group Protection       ║
║   Storage: MongoDB Atlas | 24/7 on Render        ║
╚══════════════════════════════════════════════════╝
"""

import os
import asyncio
import logging
import time
from datetime import datetime, timezone
from contextlib import asynccontextmanager

from pymongo import MongoClient, DESCENDING
from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse
import uvicorn

from telegram import (
    Update, ChatMember,
    InlineKeyboardButton, InlineKeyboardMarkup,
)
from telegram.ext import (
    Application, CommandHandler, ChatMemberHandler,
    CallbackQueryHandler, MessageHandler,
    ContextTypes, filters,
)
from telegram.error import TelegramError

# ── Logging ──────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ── Environment ──────────────────────────────────────────────
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
OWNER_ID  = int(os.environ.get("OWNER_ID", "0"))
MONGO_URI = os.environ.get("MONGO_URI", "")
PORT      = int(os.environ.get("PORT", 8080))

# ── In-memory appeal conversation state ──────────────────────
appeal_waiting: dict[int, int] = {}   # {user_id: group_id}


# ══════════════════════════════════════════════════════════════
# MONGODB
# ══════════════════════════════════════════════════════════════

def connect_mongo():
    if not MONGO_URI:
        raise RuntimeError("MONGO_URI is not set!")
    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=8000)
    client.admin.command("ping")
    logger.info("✅ MongoDB connected!")
    return client


mongo_client = connect_mongo()
mdb          = mongo_client["guard_bot"]

col_config  = mdb["config"]
col_premium = mdb["premium_users"]
col_groups  = mdb["groups"]
col_bans    = mdb["banned_log"]
col_appeals = mdb["appeals"]


# ── Config ────────────────────────────────────────────────────

def get_config() -> dict:
    return col_config.find_one({"_id": "main"}) or {}

def set_cfg(key: str, value):
    col_config.update_one({"_id": "main"}, {"$set": {key: value}}, upsert=True)


# ── Premium ───────────────────────────────────────────────────

def get_premium(uid: int) -> dict | None:
    return col_premium.find_one({"_id": uid})

def set_premium(uid: int, data: dict):
    col_premium.update_one({"_id": uid}, {"$set": data}, upsert=True)

def del_premium(uid: int):
    col_premium.delete_one({"_id": uid})

def all_premium() -> list:
    return list(col_premium.find())


# ── Groups ────────────────────────────────────────────────────

def get_group(gid: int) -> dict | None:
    return col_groups.find_one({"_id": gid})

def set_group(gid: int, data: dict):
    col_groups.update_one({"_id": gid}, {"$set": data}, upsert=True)

def all_groups() -> list:
    return list(col_groups.find())

def inc_ban(gid: int):
    col_groups.update_one({"_id": gid}, {"$inc": {"ban_count": 1}}, upsert=True)

def track_member_join(gid: int, uid: int, name: str):
    col_groups.update_one(
        {"_id": gid},
        {"$set": {f"tracked.{uid}": name}},
        upsert=False,
    )

def track_member_leave(gid: int, uid: int):
    col_groups.update_one(
        {"_id": gid},
        {"$unset": {f"tracked.{uid}": ""}},
        upsert=False,
    )

def get_tracked_members(gid: int) -> dict:
    g = get_group(gid)
    if not g:
        return {}
    return {int(k): v for k, v in g.get("tracked", {}).items()}


# ── Bans ──────────────────────────────────────────────────────

def log_ban_entry(entry: dict):
    col_bans.insert_one(entry)

def total_bans() -> int:
    return col_bans.count_documents({})


# ── Appeals ───────────────────────────────────────────────────

def create_appeal(uid: int, uname: str, gid: int, gname: str, reason: str):
    col_appeals.update_one(
        {"user_id": uid, "group_id": gid, "status": "pending"},
        {"$set": {
            "user_id": uid, "user_name": uname,
            "group_id": gid, "group_name": gname,
            "reason": reason, "status": "pending",
            "timestamp": now_ts(),
        }},
        upsert=True,
    )

def get_pending_appeals() -> list:
    return list(col_appeals.find({"status": "pending"}).sort("timestamp", DESCENDING))

def resolve_appeal(uid: int, gid: int, status: str):
    col_appeals.update_one(
        {"user_id": uid, "group_id": gid, "status": "pending"},
        {"$set": {"status": status}},
    )

def has_pending_appeal(uid: int, gid: int) -> bool:
    return col_appeals.find_one(
        {"user_id": uid, "group_id": gid, "status": "pending"}
    ) is not None


# ══════════════════════════════════════════════════════════════
# UTILITY
# ══════════════════════════════════════════════════════════════

def now_ts() -> int:
    return int(datetime.now(timezone.utc).timestamp())

def fmt_date(ts) -> str:
    if not ts:
        return "♾️  Lifetime"
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%d %b %Y")

def fmt_time(ts) -> str:
    if not ts:
        return "—"
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%d %b %Y, %H:%M UTC")

def is_owner(uid: int) -> bool:
    if OWNER_ID and uid == OWNER_ID:
        return True
    return get_config().get("bot_owner_id") == uid

def is_premium(uid: int) -> bool:
    if is_owner(uid):
        return True
    doc = get_premium(uid)
    if not doc:
        return False
    exp = doc.get("expires")
    return not (exp and exp < now_ts())

def is_whitelisted(uid: int, gid: int) -> bool:
    g = get_group(gid)
    return g is not None and uid in g.get("whitelist", [])

async def can_manage(context, gid: int, uid: int) -> bool:
    g = get_group(gid)
    if g and g.get("owner_id") == uid:
        return True
    try:
        admins = await context.bot.get_chat_administrators(gid)
        return uid in [a.user.id for a in admins]
    except TelegramError:
        return False


# ══════════════════════════════════════════════════════════════
# GLOBAL BOT APPLICATION (built once, reused by FastAPI)
# ══════════════════════════════════════════════════════════════

bot_app: Application = None


# ══════════════════════════════════════════════════════════════
# LOG CHANNEL
# ══════════════════════════════════════════════════════════════

async def send_log(context, gid: int, text: str):
    g = get_group(gid)
    if not g:
        return
    log_ch = g.get("log_channel_id")
    if not log_ch:
        return
    try:
        await context.bot.send_message(log_ch, text, parse_mode="Markdown")
    except TelegramError:
        pass


# ══════════════════════════════════════════════════════════════
# BAN / UNBAN CORE
# ══════════════════════════════════════════════════════════════

async def do_ban(
    context, uid: int, uname: str,
    gid: int, gname: str, reason: str,
) -> bool:
    if is_whitelisted(uid, gid):
        logger.info(f"Skipped — whitelisted: {uid} in {gid}")
        return False

    appeal_kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("📩  Submit Appeal", callback_data=f"appeal_start:{gid}")
    ]])
    try:
        await context.bot.send_message(
            uid,
            f"🚫  *You Have Been Banned*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📌  *Group:* {gname}\n"
            f"❌  *Reason:* You left *{reason}*\n\n"
            f"To get unbanned, submit an appeal below or\n"
            f"contact the group admin directly.",
            parse_mode="Markdown",
            reply_markup=appeal_kb,
        )
    except TelegramError:
        pass

    try:
        await context.bot.ban_chat_member(gid, uid)
    except TelegramError as e:
        logger.error(f"Ban failed {uid} in {gid}: {e}")
        return False

    inc_ban(gid)
    track_member_leave(gid, uid)
    log_ban_entry({
        "user_id": uid, "user_name": uname,
        "group_id": gid, "group_name": gname,
        "reason": reason, "time": now_ts(),
    })

    try:
        await context.bot.send_message(
            gid,
            f"🚫  *{uname}* has been banned\n"
            f"📍  *Reason:* Left *{reason}*",
            parse_mode="Markdown",
        )
    except TelegramError:
        pass

    await send_log(context, gid,
        f"🚫  *Ban Executed*\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"👤  *User:* {uname} (`{uid}`)\n"
        f"📌  *Group:* {gname}\n"
        f"❌  *Reason:* Left {reason}\n"
        f"🕐  *Time:* {fmt_time(now_ts())}"
    )

    logger.info(f"Banned {uid} ({uname}) from {gid}")
    return True


async def do_unban(
    context, uid: int,
    gid: int, gname: str, by_name: str,
) -> bool:
    try:
        await context.bot.unban_chat_member(gid, uid)
    except TelegramError as e:
        logger.error(f"Unban failed {uid} in {gid}: {e}")
        return False

    try:
        await context.bot.send_message(
            uid,
            f"✅  *Your Ban Has Been Lifted!*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📌  *Group:* {gname}\n\n"
            f"You can now rejoin — make sure you've joined\n"
            f"all required channels first.",
            parse_mode="Markdown",
        )
    except TelegramError:
        pass

    await send_log(context, gid,
        f"✅  *User Unbanned*\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"👤  *User ID:* `{uid}`\n"
        f"📌  *Group:* {gname}\n"
        f"👮  *By:* {by_name}\n"
        f"🕐  *Time:* {fmt_time(now_ts())}"
    )
    return True


# ══════════════════════════════════════════════════════════════
# APPEAL SYSTEM
# ══════════════════════════════════════════════════════════════

async def cb_appeal_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q   = update.callback_query
    uid = q.from_user.id
    await q.answer()

    gid = int(q.data.split(":")[1])
    g   = get_group(gid)
    if not g:
        await q.edit_message_text("❌  Group not found.")
        return

    if has_pending_appeal(uid, gid):
        await q.edit_message_text(
            "⏳  *Your appeal is already pending.*\n\n"
            "Please wait for the admin to review it.",
            parse_mode="Markdown",
        )
        return

    appeal_waiting[uid] = gid
    await q.edit_message_text(
        f"📩  *Submit Appeal*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📌  *Group:* {g['name']}\n\n"
        f"Please type your reason in the next message.\n"
        f"_Example: I accidentally left and have rejoined._",
        parse_mode="Markdown",
    )


async def handle_appeal_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid  = update.effective_user.id
    chat = update.effective_chat

    if chat.type != "private" or uid not in appeal_waiting:
        return

    gid    = appeal_waiting.pop(uid)
    reason = update.message.text.strip()[:500]
    g      = get_group(gid)
    uname  = update.effective_user.full_name

    if not g:
        await update.message.reply_text("❌  Group not found.")
        return

    create_appeal(uid, uname, gid, g["name"], reason)

    owner_id = get_config().get("bot_owner_id") or OWNER_ID
    if owner_id:
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅  Unban", callback_data=f"appeal_accept:{uid}:{gid}"),
            InlineKeyboardButton("❌  Reject", callback_data=f"appeal_reject:{uid}:{gid}"),
        ]])
        try:
            await context.bot.send_message(
                owner_id,
                f"📩  *New Ban Appeal*\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"👤  *User:* {uname} (`{uid}`)\n"
                f"📌  *Group:* {g['name']}\n"
                f"✍️   *Reason:* {reason}\n"
                f"🕐  *Time:* {fmt_time(now_ts())}",
                parse_mode="Markdown",
                reply_markup=kb,
            )
        except TelegramError:
            pass

    await update.message.reply_text(
        f"✅  *Appeal Submitted!*\n\n"
        f"Your appeal has been sent to the admin for review.\n"
        f"You'll be notified once a decision is made.",
        parse_mode="Markdown",
    )


async def cb_appeal_accept(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q   = update.callback_query
    uid = q.from_user.id
    await q.answer()

    if not is_owner(uid):
        await q.answer("❌  Owner only.", show_alert=True)
        return

    parts  = q.data.split(":")
    target = int(parts[1])
    gid    = int(parts[2])
    g      = get_group(gid)

    resolve_appeal(target, gid, "accepted")
    await do_unban(context, target, gid, g["name"] if g else str(gid), "Owner")

    await q.edit_message_text(
        q.message.text + "\n\n✅  *ACCEPTED — User has been unbanned.*",
        parse_mode="Markdown",
    )

    if g and g.get("owner_id") and g["owner_id"] != uid:
        try:
            await context.bot.send_message(
                g["owner_id"],
                f"✅  Appeal accepted for `{target}` in *{g['name']}* — unbanned.",
                parse_mode="Markdown",
            )
        except TelegramError:
            pass


async def cb_appeal_reject(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q   = update.callback_query
    uid = q.from_user.id
    await q.answer()

    if not is_owner(uid):
        await q.answer("❌  Owner only.", show_alert=True)
        return

    parts  = q.data.split(":")
    target = int(parts[1])
    gid    = int(parts[2])

    resolve_appeal(target, gid, "rejected")

    try:
        await context.bot.send_message(
            target,
            "❌  *Your Appeal Has Been Rejected*\n\n"
            "Your ban remains in place.\n"
            "For further queries, contact the group admin directly.",
            parse_mode="Markdown",
        )
    except TelegramError:
        pass

    await q.edit_message_text(
        q.message.text + "\n\n❌  *REJECTED — User remains banned.*",
        parse_mode="Markdown",
    )


# ══════════════════════════════════════════════════════════════
# INLINE MENU KEYBOARDS
# ══════════════════════════════════════════════════════════════

def group_main_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("👁️  Monitored Chats", callback_data="gm:chats"),
            InlineKeyboardButton("📋  Whitelist",        callback_data="gm:whitelist"),
        ],
        [
            InlineKeyboardButton("⚙️  Settings",  callback_data="gm:settings"),
            InlineKeyboardButton("📊  Statistics", callback_data="gm:stats"),
        ],
        [
            InlineKeyboardButton("🔍  Check All Members Now", callback_data="gm:check"),
        ],
    ])


def owner_main_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("💎  Premium Users",   callback_data="om:premium"),
            InlineKeyboardButton("📊  Bot Stats",       callback_data="om:stats"),
        ],
        [
            InlineKeyboardButton("📩  Pending Appeals", callback_data="om:appeals"),
            InlineKeyboardButton("📢  Broadcast",       callback_data="om:broadcast"),
        ],
    ])


def back_to_group_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("⬅️  Back to Panel", callback_data="gm:back")
    ]])


def back_to_owner_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("⬅️  Back to Panel", callback_data="om:back")
    ]])


# ══════════════════════════════════════════════════════════════
# /start  /help
# ══════════════════════════════════════════════════════════════

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid  = update.effective_user.id
    chat = update.effective_chat

    if OWNER_ID:
        if get_config().get("bot_owner_id") != OWNER_ID:
            set_cfg("bot_owner_id", OWNER_ID)

    if chat.type in ["group", "supergroup"]:
        g  = get_group(chat.id)
        mc = g.get("monitored_chats", {}) if g else {}
        if g:
            await update.message.reply_text(
                f"🛡️  *Guard Bot — Active*\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"👁️  Monitoring: *{len(mc)}* chat(s)\n"
                f"🚫  Total Bans: *{g.get('ban_count', 0)}*\n\n"
                f"`/menu` — Control Panel\n"
                f"`/mycheck` — Check your status\n"
                f"`/rules` — View required chats",
                parse_mode="Markdown",
            )
        else:
            await update.message.reply_text(
                "🛡️  *Guard Bot*\n\n"
                "Not set up in this group yet.\n"
                "Use `/setup` to activate _(Premium required)_.",
                parse_mode="Markdown",
            )
        return

    if is_owner(uid):
        prem = all_premium()
        grps = all_groups()
        await update.message.reply_text(
            f"👑  *Welcome, Owner!*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"💎  Premium Users: *{len(prem)}*\n"
            f"👥  Active Groups: *{len(grps)}*\n"
            f"🚫  Total Bans: *{total_bans()}*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "Tap `/menu` to open the control panel.",
            parse_mode="Markdown",
        )
    elif is_premium(uid):
        pdata     = get_premium(uid) or {}
        my_groups = [g for g in all_groups() if g.get("owner_id") == uid]
        await update.message.reply_text(
            f"💎  *Welcome, Premium User!*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📅  Expires: {fmt_date(pdata.get('expires'))}\n"
            f"👥  Your Groups: *{len(my_groups)}*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "Go to your group and use `/menu` to manage it.",
            parse_mode="Markdown",
        )
    else:
        await update.message.reply_text(
            "🛡️  *Guard Bot*\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "This bot protects groups by monitoring required\n"
            "channel memberships automatically.\n\n"
            "`/mycheck` — Check your membership status\n"
            "`/rules` — View group rules\n\n"
            "_Premium required to set up group protection._",
            parse_mode="Markdown",
        )


# ══════════════════════════════════════════════════════════════
# /menu  + INLINE CALLBACKS
# ══════════════════════════════════════════════════════════════

async def cmd_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid  = update.effective_user.id
    chat = update.effective_chat

    if chat.type in ["group", "supergroup"]:
        g = get_group(chat.id)
        if not g:
            await update.message.reply_text(
                "❌  Bot is not set up here. Use `/setup` first.",
                parse_mode="Markdown",
            )
            return
        if not await can_manage(context, chat.id, uid):
            await update.message.reply_text("❌  Only group admins can access the panel.")
            return
        mc = g.get("monitored_chats", {})
        await update.message.reply_text(
            f"🛡️  *Guard Bot — Control Panel*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📌  *Group:* {g['name']}\n"
            f"👁️  *Monitoring:* {len(mc)} chat(s)\n"
            f"🚫  *Total Bans:* {g.get('ban_count', 0)}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━",
            parse_mode="Markdown",
            reply_markup=group_main_kb(),
        )
    else:
        if not is_owner(uid):
            await update.message.reply_text("❌  Owner only.")
            return
        prem = all_premium()
        grps = all_groups()
        await update.message.reply_text(
            f"👑  *Owner Control Panel*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"💎  *Premium Users:* {len(prem)}\n"
            f"👥  *Active Groups:* {len(grps)}\n"
            f"🚫  *Total Bans:* {total_bans()}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━",
            parse_mode="Markdown",
            reply_markup=owner_main_kb(),
        )


async def cb_group_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q    = update.callback_query
    uid  = q.from_user.id
    gid  = q.message.chat.id
    page = q.data.split(":")[1]
    await q.answer()

    g = get_group(gid)
    if not g:
        await q.edit_message_text("❌  Group not found.")
        return
    if not await can_manage(context, gid, uid):
        await q.answer("❌  Admins only.", show_alert=True)
        return

    mc = g.get("monitored_chats", {})

    if page == "back":
        await q.edit_message_text(
            f"🛡️  *Guard Bot — Control Panel*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📌  *Group:* {g['name']}\n"
            f"👁️  *Monitoring:* {len(mc)} chat(s)\n"
            f"🚫  *Total Bans:* {g.get('ban_count', 0)}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━",
            parse_mode="Markdown",
            reply_markup=group_main_kb(),
        )

    elif page == "chats":
        if not mc:
            text = "👁️  *Monitored Chats*\n\nNo chats added yet.\nUse `/addchat <id>` to add one."
        else:
            lines = [f"👁️  *Monitored Chats* ({len(mc)})\n"]
            for cid, info in mc.items():
                lines.append(f"• `{cid}` — {info.get('name', 'Unknown')}")
            text = "\n".join(lines)
        await q.edit_message_text(text, parse_mode="Markdown", reply_markup=back_to_group_kb())

    elif page == "whitelist":
        wl = g.get("whitelist", [])
        if not wl:
            text = "📋  *Whitelist*\n\nNo users whitelisted.\nUse `/whitelist <user_id>` to add."
        else:
            lines = [f"📋  *Whitelist* ({len(wl)})\n"]
            for u in wl:
                lines.append(f"• `{u}`")
            text = "\n".join(lines)
        await q.edit_message_text(text, parse_mode="Markdown", reply_markup=back_to_group_kb())

    elif page == "settings":
        sch = g.get("schedule_hours", "Not set")
        mm  = g.get("min_members", "Not set")
        lc  = g.get("log_channel_id", "Not set")
        text = (
            f"⚙️  *Settings*\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"📅  Auto-Check: every *{sch}* hours\n"
            f"👥  Min Members Alert: *{mm}*\n"
            f"📢  Log Channel: `{lc}`\n\n"
            f"Use `/setschedule`, `/setminmembers`, `/setlog` to change."
        )
        await q.edit_message_text(text, parse_mode="Markdown", reply_markup=back_to_group_kb())

    elif page == "stats":
        text = (
            f"📊  *Group Statistics*\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"📌  *Group:* {g['name']}\n"
            f"👁️  *Monitored:* {len(mc)} chat(s)\n"
            f"👥  *Tracked Members:* {len(get_tracked_members(gid))}\n"
            f"🚫  *Total Bans:* {g.get('ban_count', 0)}\n"
            f"📋  *Whitelist:* {len(g.get('whitelist', []))}"
        )
        await q.edit_message_text(text, parse_mode="Markdown", reply_markup=back_to_group_kb())

    elif page == "check":
        await q.edit_message_text(
            "🔍  *Manual check started...*\n\nThis may take a few minutes.",
            parse_mode="Markdown",
        )
        members  = get_tracked_members(gid)
        checked  = 0
        banned_c = 0
        for uid_m, uname_m in members.items():
            checked += 1
            for cid, info in mc.items():
                try:
                    cm = await context.bot.get_chat_member(int(cid), uid_m)
                    if cm.status in [ChatMember.LEFT, ChatMember.BANNED]:
                        ok = await do_ban(
                            context, uid_m, uname_m,
                            gid, g["name"], info["name"],
                        )
                        if ok:
                            banned_c += 1
                        break
                except TelegramError:
                    pass
        set_group(gid, {"last_auto_check": now_ts()})
        await context.bot.send_message(
            gid,
            f"✅  *Check Complete*\n"
            f"👥  Checked: {checked}\n"
            f"🚫  Banned: {banned_c}",
            parse_mode="Markdown",
        )


async def cb_owner_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q   = update.callback_query
    uid = q.from_user.id
    await q.answer()

    if not is_owner(uid):
        await q.answer("❌  Owner only.", show_alert=True)
        return

    page = q.data.split(":")[1]
    prem = all_premium()
    grps = all_groups()

    if page == "back":
        await q.edit_message_text(
            f"👑  *Owner Control Panel*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"💎  *Premium Users:* {len(prem)}\n"
            f"👥  *Active Groups:* {len(grps)}\n"
            f"🚫  *Total Bans:* {total_bans()}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━",
            parse_mode="Markdown",
            reply_markup=owner_main_kb(),
        )

    elif page == "premium":
        if not prem:
            text = "💎  *Premium Users*\n\nNo premium users yet."
        else:
            lines = [f"💎  *Premium Users* ({len(prem)})\n"]
            for p in prem:
                exp = fmt_date(p.get("expires"))
                lines.append(f"• `{p['_id']}` — {p.get('name', 'Unknown')} | Exp: {exp}")
            text = "\n".join(lines)
        await q.edit_message_text(text, parse_mode="Markdown", reply_markup=back_to_owner_kb())

    elif page == "stats":
        text = (
            f"📊  *Bot Statistics*\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"💎  Premium Users: *{len(prem)}*\n"
            f"👥  Active Groups: *{len(grps)}*\n"
            f"🚫  Total Bans: *{total_bans()}*\n"
            f"📩  Pending Appeals: *{len(get_pending_appeals())}*"
        )
        await q.edit_message_text(text, parse_mode="Markdown", reply_markup=back_to_owner_kb())

    elif page == "appeals":
        appeals = get_pending_appeals()
        if not appeals:
            text = "📩  *Pending Appeals*\n\nNo pending appeals."
            await q.edit_message_text(text, parse_mode="Markdown", reply_markup=back_to_owner_kb())
        else:
            for ap in appeals[:5]:
                kb = InlineKeyboardMarkup([[
                    InlineKeyboardButton("✅  Unban", callback_data=f"appeal_accept:{ap['user_id']}:{ap['group_id']}"),
                    InlineKeyboardButton("❌  Reject", callback_data=f"appeal_reject:{ap['user_id']}:{ap['group_id']}"),
                ]])
                await context.bot.send_message(
                    uid,
                    f"📩  *Appeal*\n"
                    f"👤  `{ap['user_id']}` — {ap.get('user_name','?')}\n"
                    f"📌  {ap.get('group_name','?')}\n"
                    f"✍️  {ap.get('reason','?')}\n"
                    f"🕐  {fmt_time(ap.get('timestamp'))}",
                    parse_mode="Markdown",
                    reply_markup=kb,
                )
            await q.edit_message_text(
                f"📩  Showing {min(5, len(appeals))} of {len(appeals)} pending appeals.",
                reply_markup=back_to_owner_kb(),
            )

    elif page == "broadcast":
        await q.edit_message_text(
            "📢  *Broadcast*\n\nUse `/broadcast <message>` to send a message to all premium users.",
            parse_mode="Markdown",
            reply_markup=back_to_owner_kb(),
        )


# ══════════════════════════════════════════════════════════════
# PREMIUM COMMANDS (Owner only)
# ══════════════════════════════════════════════════════════════

async def cmd_addpremium(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_owner(uid):
        await update.message.reply_text("❌  Owner only.")
        return
    args = context.args
    if not args:
        await update.message.reply_text("Usage: `/addpremium <user_id> [days]`", parse_mode="Markdown")
        return
    try:
        target = int(args[0])
    except ValueError:
        await update.message.reply_text("❌  Invalid user ID.")
        return
    days = None
    if len(args) > 1:
        try:
            days = int(args[1])
        except ValueError:
            await update.message.reply_text("❌  Invalid days.")
            return
    expires = (now_ts() + days * 86400) if days else None
    set_premium(target, {"name": str(target), "expires": expires, "added_by": uid, "added_at": now_ts()})
    exp_str = fmt_date(expires)
    await update.message.reply_text(
        f"✅  Premium granted to `{target}`\n📅  Expires: {exp_str}",
        parse_mode="Markdown",
    )
    try:
        await context.bot.send_message(
            target,
            f"💎  *You've been granted Premium!*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📅  Expires: {exp_str}\n\n"
            f"Add the bot to your group, make it Admin with Ban permission,\n"
            f"then send `/setup` in the group.\n\n"
            f"Use `/menu` for full control panel.",
            parse_mode="Markdown",
        )
    except TelegramError:
        pass


async def cmd_removepremium(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_owner(uid):
        await update.message.reply_text("❌  Owner only.")
        return
    args = context.args
    if not args:
        await update.message.reply_text("Usage: `/removepremium <user_id>`", parse_mode="Markdown")
        return
    try:
        target = int(args[0])
    except ValueError:
        await update.message.reply_text("❌  Invalid user ID.")
        return
    del_premium(target)
    await update.message.reply_text(f"✅  Premium removed from `{target}`", parse_mode="Markdown")


async def cmd_listpremium(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_owner(uid):
        await update.message.reply_text("❌  Owner only.")
        return
    prem = all_premium()
    if not prem:
        await update.message.reply_text("No premium users.")
        return
    lines = [f"💎  *Premium Users* ({len(prem)})\n"]
    for p in prem:
        lines.append(f"• `{p['_id']}` — {p.get('name','?')} | {fmt_date(p.get('expires'))}")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def cmd_botstats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_owner(uid):
        await update.message.reply_text("❌  Owner only.")
        return
    await update.message.reply_text(
        f"📊  *Bot Statistics*\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💎  Premium Users: *{len(all_premium())}*\n"
        f"👥  Active Groups: *{len(all_groups())}*\n"
        f"🚫  Total Bans: *{total_bans()}*\n"
        f"📩  Pending Appeals: *{len(get_pending_appeals())}*",
        parse_mode="Markdown",
    )


async def cmd_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_owner(uid):
        await update.message.reply_text("❌  Owner only.")
        return
    if not context.args:
        await update.message.reply_text("Usage: `/broadcast <message>`", parse_mode="Markdown")
        return
    msg = " ".join(context.args)
    prem = all_premium()
    sent = 0
    for p in prem:
        try:
            await context.bot.send_message(p["_id"], f"📢  *Broadcast*\n\n{msg}", parse_mode="Markdown")
            sent += 1
        except TelegramError:
            pass
    await update.message.reply_text(f"✅  Broadcast sent to {sent}/{len(prem)} premium users.")


# ══════════════════════════════════════════════════════════════
# GROUP COMMANDS (Premium)
# ══════════════════════════════════════════════════════════════

async def cmd_setup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid  = update.effective_user.id
    chat = update.effective_chat
    if chat.type not in ["group", "supergroup"]:
        await update.message.reply_text("❌  Use this command in a group.")
        return
    if not is_premium(uid):
        await update.message.reply_text("❌  Premium required.")
        return
    if not await can_manage(context, chat.id, uid):
        await update.message.reply_text("❌  Only group admins can set up the bot.")
        return
    set_group(chat.id, {"name": chat.title, "owner_id": uid, "monitored_chats": {}, "whitelist": [], "ban_count": 0})
    await update.message.reply_text(
        f"✅  *Guard Bot activated!*\n\n"
        f"📌  Group: *{chat.title}*\n\n"
        f"Next steps:\n"
        f"1. `/addchat <channel_id>` — add channels to monitor\n"
        f"2. `/setlog <log_channel_id>` — set a log channel (optional)\n"
        f"3. `/setschedule <hours>` — set auto-check interval\n"
        f"4. `/menu` — open control panel",
        parse_mode="Markdown",
    )


async def cmd_addchat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid  = update.effective_user.id
    chat = update.effective_chat
    if chat.type not in ["group", "supergroup"]:
        await update.message.reply_text("❌  Use in group.")
        return
    if not is_premium(uid) or not await can_manage(context, chat.id, uid):
        await update.message.reply_text("❌  Premium admin only.")
        return
    if not context.args:
        await update.message.reply_text("Usage: `/addchat <chat_id>`", parse_mode="Markdown")
        return
    try:
        cid = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌  Invalid chat ID (must be a number like -100xxxxxxxxxx).")
        return
    try:
        chat_info = await context.bot.get_chat(cid)
        cname = chat_info.title or str(cid)
    except TelegramError:
        cname = str(cid)
    g = get_group(chat.id)
    if not g:
        await update.message.reply_text("❌  Run `/setup` first.")
        return
    mc = g.get("monitored_chats", {})
    mc[str(cid)] = {"name": cname}
    set_group(chat.id, {"monitored_chats": mc})
    await update.message.reply_text(f"✅  Added: *{cname}* (`{cid}`)", parse_mode="Markdown")


async def cmd_removechat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid  = update.effective_user.id
    chat = update.effective_chat
    if chat.type not in ["group", "supergroup"]:
        await update.message.reply_text("❌  Use in group.")
        return
    if not is_premium(uid) or not await can_manage(context, chat.id, uid):
        await update.message.reply_text("❌  Premium admin only.")
        return
    if not context.args:
        await update.message.reply_text("Usage: `/removechat <chat_id>`", parse_mode="Markdown")
        return
    cid = context.args[0]
    g   = get_group(chat.id)
    if not g:
        await update.message.reply_text("❌  Run `/setup` first.")
        return
    mc = g.get("monitored_chats", {})
    if cid in mc:
        del mc[cid]
        set_group(chat.id, {"monitored_chats": mc})
        await update.message.reply_text(f"✅  Removed `{cid}` from monitored chats.", parse_mode="Markdown")
    else:
        await update.message.reply_text("❌  Chat not found in list.")


async def cmd_listchats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid  = update.effective_user.id
    chat = update.effective_chat
    if chat.type not in ["group", "supergroup"]:
        await update.message.reply_text("❌  Use in group.")
        return
    g = get_group(chat.id)
    if not g:
        await update.message.reply_text("❌  Run `/setup` first.")
        return
    mc = g.get("monitored_chats", {})
    if not mc:
        await update.message.reply_text("No monitored chats.")
        return
    lines = [f"👁️  *Monitored Chats* ({len(mc)})\n"]
    for cid, info in mc.items():
        lines.append(f"• `{cid}` — {info.get('name','?')}")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def cmd_whitelist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid  = update.effective_user.id
    chat = update.effective_chat
    if chat.type not in ["group", "supergroup"]:
        await update.message.reply_text("❌  Use in group.")
        return
    if not is_premium(uid) or not await can_manage(context, chat.id, uid):
        await update.message.reply_text("❌  Premium admin only.")
        return
    if not context.args:
        await update.message.reply_text("Usage: `/whitelist <user_id>`", parse_mode="Markdown")
        return
    try:
        target = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌  Invalid user ID.")
        return
    g = get_group(chat.id)
    if not g:
        await update.message.reply_text("❌  Run `/setup` first.")
        return
    wl = g.get("whitelist", [])
    if target not in wl:
        wl.append(target)
    set_group(chat.id, {"whitelist": wl})
    await update.message.reply_text(f"✅  `{target}` added to whitelist.", parse_mode="Markdown")


async def cmd_unwhitelist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid  = update.effective_user.id
    chat = update.effective_chat
    if chat.type not in ["group", "supergroup"]:
        await update.message.reply_text("❌  Use in group.")
        return
    if not is_premium(uid) or not await can_manage(context, chat.id, uid):
        await update.message.reply_text("❌  Premium admin only.")
        return
    if not context.args:
        await update.message.reply_text("Usage: `/unwhitelist <user_id>`", parse_mode="Markdown")
        return
    try:
        target = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌  Invalid user ID.")
        return
    g = get_group(chat.id)
    if not g:
        await update.message.reply_text("❌  Run `/setup` first.")
        return
    wl = g.get("whitelist", [])
    if target in wl:
        wl.remove(target)
    set_group(chat.id, {"whitelist": wl})
    await update.message.reply_text(f"✅  `{target}` removed from whitelist.", parse_mode="Markdown")


async def cmd_setlog(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid  = update.effective_user.id
    chat = update.effective_chat
    if chat.type not in ["group", "supergroup"]:
        await update.message.reply_text("❌  Use in group.")
        return
    if not is_premium(uid) or not await can_manage(context, chat.id, uid):
        await update.message.reply_text("❌  Premium admin only.")
        return
    if not context.args:
        await update.message.reply_text("Usage: `/setlog <log_channel_id>`", parse_mode="Markdown")
        return
    try:
        log_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌  Invalid channel ID.")
        return
    set_group(chat.id, {"log_channel_id": log_id})
    await update.message.reply_text(f"✅  Log channel set to `{log_id}`", parse_mode="Markdown")


async def cmd_setschedule(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid  = update.effective_user.id
    chat = update.effective_chat
    if chat.type not in ["group", "supergroup"]:
        await update.message.reply_text("❌  Use in group.")
        return
    if not is_premium(uid) or not await can_manage(context, chat.id, uid):
        await update.message.reply_text("❌  Premium admin only.")
        return
    if not context.args:
        await update.message.reply_text("Usage: `/setschedule <hours>`", parse_mode="Markdown")
        return
    try:
        hours = int(context.args[0])
        if hours < 1:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌  Invalid hours (min 1).")
        return
    set_group(chat.id, {"schedule_hours": hours})
    await update.message.reply_text(f"✅  Auto-check set to every *{hours}* hour(s).", parse_mode="Markdown")


async def cmd_setminmembers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid  = update.effective_user.id
    chat = update.effective_chat
    if chat.type not in ["group", "supergroup"]:
        await update.message.reply_text("❌  Use in group.")
        return
    if not is_premium(uid) or not await can_manage(context, chat.id, uid):
        await update.message.reply_text("❌  Premium admin only.")
        return
    if not context.args:
        await update.message.reply_text("Usage: `/setminmembers <number>`", parse_mode="Markdown")
        return
    try:
        mm = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌  Invalid number.")
        return
    set_group(chat.id, {"min_members": mm})
    await update.message.reply_text(f"✅  Min member alert set to *{mm}*.", parse_mode="Markdown")


async def cmd_checkall(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid  = update.effective_user.id
    chat = update.effective_chat
    if chat.type not in ["group", "supergroup"]:
        await update.message.reply_text("❌  Use in group.")
        return
    if not is_premium(uid) or not await can_manage(context, chat.id, uid):
        await update.message.reply_text("❌  Premium admin only.")
        return
    g = get_group(chat.id)
    if not g:
        await update.message.reply_text("❌  Run `/setup` first.")
        return
    mc = g.get("monitored_chats", {})
    if not mc:
        await update.message.reply_text("❌  No monitored chats. Use `/addchat` first.")
        return

    msg = await update.message.reply_text("🔍  Checking all members... please wait.")
    members  = get_tracked_members(chat.id)
    checked  = 0
    banned_c = 0

    for uid_m, uname_m in members.items():
        checked += 1
        for cid, info in mc.items():
            try:
                cm = await context.bot.get_chat_member(int(cid), uid_m)
                if cm.status in [ChatMember.LEFT, ChatMember.BANNED]:
                    ok = await do_ban(
                        context, uid_m, uname_m,
                        chat.id, g["name"], info["name"],
                    )
                    if ok:
                        banned_c += 1
                    break
            except TelegramError:
                pass

    set_group(chat.id, {"last_auto_check": now_ts()})
    await msg.edit_text(
        f"✅  *Check Complete*\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"👥  Members checked: *{checked}*\n"
        f"🚫  Members banned: *{banned_c}*",
        parse_mode="Markdown",
    )


async def cmd_unbanuser(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid  = update.effective_user.id
    chat = update.effective_chat
    if chat.type not in ["group", "supergroup"]:
        await update.message.reply_text("❌  Use in group.")
        return
    if not is_premium(uid) or not await can_manage(context, chat.id, uid):
        await update.message.reply_text("❌  Premium admin only.")
        return
    if not context.args:
        await update.message.reply_text("Usage: `/unbanuser <user_id>`", parse_mode="Markdown")
        return
    try:
        target = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌  Invalid user ID.")
        return
    g = get_group(chat.id)
    ok = await do_unban(context, target, chat.id, g["name"] if g else str(chat.id), update.effective_user.full_name)
    if ok:
        await update.message.reply_text(f"✅  `{target}` has been unbanned.", parse_mode="Markdown")
    else:
        await update.message.reply_text(f"❌  Failed to unban `{target}`.", parse_mode="Markdown")


async def cmd_mystats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid  = update.effective_user.id
    chat = update.effective_chat
    if chat.type not in ["group", "supergroup"]:
        await update.message.reply_text("❌  Use in group.")
        return
    g = get_group(chat.id)
    if not g:
        await update.message.reply_text("❌  Bot not set up here.")
        return
    await update.message.reply_text(
        f"📊  *Group Statistics*\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📌  *Group:* {g['name']}\n"
        f"👁️  *Monitored:* {len(g.get('monitored_chats', {}))} chat(s)\n"
        f"👥  *Tracked:* {len(get_tracked_members(chat.id))} members\n"
        f"🚫  *Total Bans:* {g.get('ban_count', 0)}\n"
        f"📋  *Whitelist:* {len(g.get('whitelist', []))}",
        parse_mode="Markdown",
    )


# ══════════════════════════════════════════════════════════════
# MEMBER COMMANDS (General users)
# ══════════════════════════════════════════════════════════════

async def cmd_mycheck(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid  = update.effective_user.id
    chat = update.effective_chat
    if chat.type not in ["group", "supergroup"]:
        await update.message.reply_text("❌  Use this in the group.")
        return
    g = get_group(chat.id)
    if not g:
        await update.message.reply_text("❌  Bot not set up here.")
        return
    mc = g.get("monitored_chats", {})
    if not mc:
        await update.message.reply_text("✅  No channels required.")
        return

    results = []
    for cid, info in mc.items():
        try:
            cm = await context.bot.get_chat_member(int(cid), uid)
            status = "✅  Member" if cm.status in [ChatMember.MEMBER, ChatMember.ADMINISTRATOR, ChatMember.OWNER] else "❌  Not joined"
        except TelegramError:
            status = "⚠️  Unknown"
        results.append(f"• *{info.get('name','?')}*: {status}")

    await update.message.reply_text(
        f"🔍  *Your Membership Status*\n━━━━━━━━━━━━━━━━━━\n" + "\n".join(results),
        parse_mode="Markdown",
    )


async def cmd_rules(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat.type not in ["group", "supergroup"]:
        await update.message.reply_text("❌  Use this in the group.")
        return
    g = get_group(chat.id)
    if not g:
        await update.message.reply_text("❌  Bot not set up here.")
        return
    mc = g.get("monitored_chats", {})
    if not mc:
        await update.message.reply_text("No required chats.")
        return
    lines = ["📋  *Required Chats*\n━━━━━━━━━━━━━━━━━━"]
    for cid, info in mc.items():
        lines.append(f"• {info.get('name','?')} (`{cid}`)")
    lines.append("\n_Members must be in all these chats to stay in this group._")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


# ══════════════════════════════════════════════════════════════
# CHAT MEMBER EVENTS
# ══════════════════════════════════════════════════════════════

async def on_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    result = update.chat_member
    if not result:
        return

    gid   = result.chat.id
    g     = get_group(gid)
    if not g:
        return

    uid   = result.new_chat_member.user.id
    uname = result.new_chat_member.user.full_name
    new_s = result.new_chat_member.status
    old_s = result.old_chat_member.status if result.old_chat_member else None

    active_statuses = [ChatMember.MEMBER, ChatMember.ADMINISTRATOR, ChatMember.OWNER, ChatMember.RESTRICTED]

    if new_s in active_statuses and old_s not in active_statuses:
        track_member_join(gid, uid, uname)
        mc = g.get("monitored_chats", {})
        for cid, info in mc.items():
            try:
                cm = await context.bot.get_chat_member(int(cid), uid)
                if cm.status in [ChatMember.LEFT, ChatMember.BANNED]:
                    await do_ban(context, uid, uname, gid, g["name"], info["name"])
                    return
            except TelegramError:
                pass

    elif new_s in [ChatMember.LEFT, ChatMember.BANNED] and old_s in active_statuses:
        mc = g.get("monitored_chats", {})
        if mc:
            await do_ban(context, uid, uname, gid, g["name"], g["name"])
        else:
            track_member_leave(gid, uid)

        mm = g.get("min_members")
        if mm:
            alert_to = g.get("owner_id") or (get_config().get("bot_owner_id"))
            if alert_to:
                try:
                    count = await context.bot.get_chat_member_count(gid)
                    if count < mm:
                        try:
                            await context.bot.send_message(
                                alert_to,
                                f"⚠️  *Member Count Alert!*\n"
                                f"━━━━━━━━━━━━━━━━━━\n"
                                f"📌  *Group:* {g['name']}\n"
                                f"👥  *Current:* {count} members\n"
                                f"📉  *Threshold:* {mm} members",
                                parse_mode="Markdown",
                            )
                        except TelegramError:
                            pass
                except TelegramError:
                    pass


# ══════════════════════════════════════════════════════════════
# AUTO SCHEDULE JOB
# ══════════════════════════════════════════════════════════════

async def scheduled_check_job(context: ContextTypes.DEFAULT_TYPE):
    ts = now_ts()
    for g in all_groups():
        gid = g["_id"]
        sch = g.get("schedule_hours")
        if not sch:
            continue

        last = g.get("last_auto_check") or 0
        if ts - last < sch * 3600:
            continue

        mc = g.get("monitored_chats", {})
        if not mc:
            continue

        owner_id = g.get("owner_id")
        if owner_id and not is_owner(owner_id) and not is_premium(owner_id):
            continue

        logger.info(f"⏰ Auto-check: {g['name']} ({gid})")
        members  = get_tracked_members(gid)
        checked  = 0
        banned_c = 0

        for uid_m, uname_m in members.items():
            checked += 1
            for cid, info in mc.items():
                try:
                    cm = await context.bot.get_chat_member(int(cid), uid_m)
                    if cm.status in [ChatMember.LEFT, ChatMember.BANNED]:
                        ok = await do_ban(
                            context, uid_m, uname_m,
                            gid, g["name"], info["name"],
                        )
                        if ok:
                            banned_c += 1
                        break
                except TelegramError:
                    pass

        set_group(gid, {"last_auto_check": ts})

        if owner_id:
            try:
                await context.bot.send_message(
                    owner_id,
                    f"📅  *Scheduled Check Complete*\n"
                    f"━━━━━━━━━━━━━━━━━━\n"
                    f"📌  *Group:* {g['name']}\n"
                    f"👥  *Checked:* {checked}\n"
                    f"🚫  *Banned:* {banned_c}\n"
                    f"🕐  *Time:* {fmt_time(ts)}",
                    parse_mode="Markdown",
                )
            except TelegramError:
                pass

        mm = g.get("min_members")
        if mm and owner_id:
            try:
                count = await context.bot.get_chat_member_count(gid)
                if count < mm:
                    await context.bot.send_message(
                        owner_id,
                        f"⚠️  *Member Count Alert!*\n\n"
                        f"📌  *{g['name']}* now has only *{count}* members\n"
                        f"📉  Threshold: {mm}",
                        parse_mode="Markdown",
                    )
            except TelegramError:
                pass


# ══════════════════════════════════════════════════════════════
# FASTAPI APP + BOT STARTUP (replaces threading keep-alive)
# ══════════════════════════════════════════════════════════════

def build_bot_app() -> Application:
    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .build()
    )

    # Owner
    app.add_handler(CommandHandler("addpremium",    cmd_addpremium))
    app.add_handler(CommandHandler("removepremium", cmd_removepremium))
    app.add_handler(CommandHandler("listpremium",   cmd_listpremium))
    app.add_handler(CommandHandler("botstats",      cmd_botstats))
    app.add_handler(CommandHandler("broadcast",     cmd_broadcast))

    # Premium / Group management
    app.add_handler(CommandHandler("setup",         cmd_setup))
    app.add_handler(CommandHandler("addchat",       cmd_addchat))
    app.add_handler(CommandHandler("removechat",    cmd_removechat))
    app.add_handler(CommandHandler("listchats",     cmd_listchats))
    app.add_handler(CommandHandler("whitelist",     cmd_whitelist))
    app.add_handler(CommandHandler("unwhitelist",   cmd_unwhitelist))
    app.add_handler(CommandHandler("setlog",        cmd_setlog))
    app.add_handler(CommandHandler("setschedule",   cmd_setschedule))
    app.add_handler(CommandHandler("setminmembers", cmd_setminmembers))
    app.add_handler(CommandHandler("checkall",      cmd_checkall))
    app.add_handler(CommandHandler("unbanuser",     cmd_unbanuser))
    app.add_handler(CommandHandler("mystats",       cmd_mystats))

    # General
    app.add_handler(CommandHandler("start",   cmd_start))
    app.add_handler(CommandHandler("help",    cmd_start))
    app.add_handler(CommandHandler("menu",    cmd_menu))
    app.add_handler(CommandHandler("mycheck", cmd_mycheck))
    app.add_handler(CommandHandler("rules",   cmd_rules))

    # Inline callbacks
    app.add_handler(CallbackQueryHandler(cb_appeal_start,  pattern=r"^appeal_start:"))
    app.add_handler(CallbackQueryHandler(cb_appeal_accept, pattern=r"^appeal_accept:"))
    app.add_handler(CallbackQueryHandler(cb_appeal_reject, pattern=r"^appeal_reject:"))
    app.add_handler(CallbackQueryHandler(cb_group_menu,    pattern=r"^gm:"))
    app.add_handler(CallbackQueryHandler(cb_owner_menu,    pattern=r"^om:"))

    # ChatMember events
    app.add_handler(ChatMemberHandler(on_chat_member, ChatMemberHandler.ANY_CHAT_MEMBER))

    # Private message — appeal text input
    app.add_handler(MessageHandler(
        filters.TEXT & filters.ChatType.PRIVATE & ~filters.COMMAND,
        handle_appeal_text,
    ))

    # Scheduled job — every 30 minutes
    if app.job_queue is not None:
        app.job_queue.run_repeating(scheduled_check_job, interval=1800, first=60)
    else:
        logger.warning("JobQueue not available — install python-telegram-bot[job-queue]")

    return app


@asynccontextmanager
async def lifespan(web_app: FastAPI):
    global bot_app

    if not BOT_TOKEN:
        logger.error("BOT_TOKEN is not set!")
        yield
        return

    if OWNER_ID:
        col_config.update_one(
            {"_id": "main"},
            {"$set": {"bot_owner_id": OWNER_ID}},
            upsert=True,
        )
        logger.info(f"Owner synced: {OWNER_ID}")

    bot_app = build_bot_app()

    async with bot_app:
        await bot_app.start()
        await bot_app.updater.start_polling(
            allowed_updates=["message", "chat_member", "callback_query"],
            drop_pending_updates=True,
        )
        logger.info("✅ Guard Bot polling started!")
        yield
        await bot_app.updater.stop()
        await bot_app.stop()
        logger.info("Guard Bot stopped.")


web = FastAPI(lifespan=lifespan)


@web.get("/")
async def root():
    prem_count  = col_premium.count_documents({})
    group_count = col_groups.count_documents({})
    ban_count   = total_bans()
    return PlainTextResponse(
        f"🛡️ Guard Bot | Premium: {prem_count} | Groups: {group_count} | Bans: {ban_count}"
    )


@web.get("/health")
async def health():
    return PlainTextResponse("OK")


# ══════════════════════════════════════════════════════════════
# ENTRY POINT
# ══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    uvicorn.run(
        "bot:web",
        host="0.0.0.0",
        port=PORT,
        log_level="info",
    )
