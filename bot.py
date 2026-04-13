import os
import logging
import json
from telegram import Update, ChatMember, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    ChatMemberHandler,
    CallbackQueryHandler,
    ContextTypes,
)
from telegram.error import TelegramError

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
DATA_FILE = "data.json"


def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r") as f:
            return json.load(f)
    return {
        "lecture_group_id": None,
        "lecture_group_name": None,
        "monitored_chats": {},
        "banned_users": [],
        "bot_owner_id": None,
    }


def save_data():
    with open(DATA_FILE, "w") as f:
        json.dump(config, f, indent=2)


config = load_data()


def get_lecture_id():
    return config.get("lecture_group_id")


def get_monitored():
    return config.get("monitored_chats", {})


async def get_user_role(context, chat_id, user_id):
    try:
        m = await context.bot.get_chat_member(chat_id, user_id)
        return m.status
    except TelegramError:
        return None


async def is_lecture_admin(context, user_id):
    lid = get_lecture_id()
    if not lid:
        return False
    role = await get_user_role(context, lid, user_id)
    return role in [ChatMember.ADMINISTRATOR, ChatMember.OWNER]


async def is_bot_owner(user_id):
    return config.get("bot_owner_id") == user_id


# ─────────────────────────────────────────────
# /start
# ─────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    lid = get_lecture_id()

    if config.get("bot_owner_id") is None:
        config["bot_owner_id"] = user_id
        save_data()
        await update.message.reply_text(
            "👋 *Aap is bot ke owner ban gaye hain!*\n\n"
            "Ab lecture group set karo:\n"
            "1️⃣ Bot ko apne lecture group me add karo\n"
            "2️⃣ Bot ko Admin banao (Ban Users permission de)\n"
            "3️⃣ Lecture group me ja ke `/setlecturegroup` command do\n\n"
            "Ya seedha yahan type karo:\n`/setlecturegroup <group_id>`",
            parse_mode="Markdown",
        )
        return

    if not lid:
        await update.message.reply_text(
            "⚙️ *Setup incomplete!*\n\n"
            "Lecture group abhi set nahi hua.\n"
            "Bot owner: Lecture group me ja ke `/setlecturegroup` command do.",
            parse_mode="Markdown",
        )
        return

    is_admin = await is_lecture_admin(context, user_id)
    is_owner = await is_bot_owner(user_id)

    if is_admin or is_owner:
        await update.message.reply_text(
            f"🛡️ *Lecture Guard Bot*\n\n"
            f"📌 Lecture Group: *{config.get('lecture_group_name', 'Set hai')}*\n"
            f"👁️ Monitored Chats: *{len(get_monitored())}*\n\n"
            "🔧 *Admin Commands:*\n"
            "`/addchat <chat_id>` — Monitor me add karo\n"
            "`/removechat <chat_id>` — Monitor se hatao\n"
            "`/listchats` — Saare monitored chats dekho\n"
            "`/checkall` — Saare members check karo\n"
            "`/status` — Bot ka status\n"
            "`/setlecturegroup` — Lecture group change karo\n"
            "`/unbanuser <user_id>` — Kisi ko unban karo\n\n"
            "📋 *Member Commands:*\n"
            "`/mycheck` — Apna membership check karo\n"
            "`/rules` — Group rules dekho",
            parse_mode="Markdown",
        )
    else:
        await update.message.reply_text(
            f"👋 *Lecture Guard Bot*\n\n"
            f"Yeh bot *{config.get('lecture_group_name', 'lecture group')}* ke members ki monitoring karta hai.\n\n"
            "Agar aap lecture group me ho aur kisi monitored group/channel se leave karoge toh aapko ban kar diya jayega.\n\n"
            "Commands:\n"
            "`/mycheck` — Apna membership status check karo\n"
            "`/rules` — Rules dekho",
            parse_mode="Markdown",
        )


# ─────────────────────────────────────────────
# /setlecturegroup
# ─────────────────────────────────────────────
async def setlecturegroup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    is_owner = await is_bot_owner(user_id)

    if not is_owner:
        current_lid = get_lecture_id()
        if current_lid:
            is_admin = await is_lecture_admin(context, user_id)
            if not is_admin:
                await update.message.reply_text("❌ Sirf bot owner ya lecture group admin ye command use kar sakte hain.")
                return
        else:
            await update.message.reply_text("❌ Sirf bot owner ye command use kar sakta hai.")
            return

    chat = update.effective_chat

    if context.args:
        try:
            target_id = int(context.args[0])
            try:
                target_chat = await context.bot.get_chat(target_id)
                config["lecture_group_id"] = target_id
                config["lecture_group_name"] = target_chat.title
                save_data()
                await update.message.reply_text(
                    f"✅ Lecture group set ho gaya:\n*{target_chat.title}* (`{target_id}`)",
                    parse_mode="Markdown",
                )
            except TelegramError as e:
                await update.message.reply_text(f"❌ Chat access nahi hua: {e}")
        except ValueError:
            await update.message.reply_text("❌ Invalid ID. Number hona chahiye.")
        return

    if chat.type in ["group", "supergroup"]:
        config["lecture_group_id"] = chat.id
        config["lecture_group_name"] = chat.title
        save_data()
        await update.message.reply_text(
            f"✅ *{chat.title}* ab lecture group set ho gaya!\n\n"
            "Ab kisi bhi group/channel monitor karne ke liye:\n`/addchat <chat_id>`",
            parse_mode="Markdown",
        )
    else:
        await update.message.reply_text(
            "Ye command group me use karo, ya ID do:\n`/setlecturegroup <group_id>`",
            parse_mode="Markdown",
        )


# ─────────────────────────────────────────────
# /addchat
# ─────────────────────────────────────────────
async def addchat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    lid = get_lecture_id()

    if not lid:
        await update.message.reply_text("❌ Pehle lecture group set karo: `/setlecturegroup`", parse_mode="Markdown")
        return

    is_admin = await is_lecture_admin(context, user_id)
    is_owner = await is_bot_owner(user_id)
    if not (is_admin or is_owner):
        await update.message.reply_text("❌ Sirf lecture group admins ye command use kar sakte hain.")
        return

    if not context.args:
        await update.message.reply_text("Usage: `/addchat <chat_id>`", parse_mode="Markdown")
        return

    try:
        chat_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Invalid ID. Number dalo.")
        return

    monitored = get_monitored()
    if str(chat_id) in monitored:
        await update.message.reply_text(f"✅ Ye chat pehle se monitor ho raha hai: `{chat_id}`", parse_mode="Markdown")
        return

    try:
        chat = await context.bot.get_chat(chat_id)
        monitored[str(chat_id)] = {"name": chat.title, "type": chat.type}
        config["monitored_chats"] = monitored
        save_data()
        await update.message.reply_text(
            f"✅ Monitor me add ho gaya:\n*{chat.title}* (`{chat_id}`)\n\n"
            "Ab agar koi member is chat se leave karega, toh use lecture group se ban kar diya jayega.",
            parse_mode="Markdown",
        )
    except TelegramError as e:
        await update.message.reply_text(
            f"❌ Chat access nahi hua `{chat_id}`.\n"
            "Pakka karo ki bot us group/channel me admin hai.\n"
            f"Error: `{e}`",
            parse_mode="Markdown",
        )


# ─────────────────────────────────────────────
# /removechat
# ─────────────────────────────────────────────
async def removechat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    lid = get_lecture_id()
    if not lid:
        await update.message.reply_text("❌ Lecture group set nahi hai.")
        return

    is_admin = await is_lecture_admin(context, user_id)
    is_owner = await is_bot_owner(user_id)
    if not (is_admin or is_owner):
        await update.message.reply_text("❌ Sirf lecture group admins ye command use kar sakte hain.")
        return

    if not context.args:
        await update.message.reply_text("Usage: `/removechat <chat_id>`", parse_mode="Markdown")
        return

    try:
        chat_id = str(int(context.args[0]))
    except ValueError:
        await update.message.reply_text("❌ Invalid ID.")
        return

    monitored = get_monitored()
    if chat_id not in monitored:
        await update.message.reply_text(f"❌ `{chat_id}` monitor me nahi hai.", parse_mode="Markdown")
        return

    name = monitored[chat_id].get("name", chat_id)
    del monitored[chat_id]
    config["monitored_chats"] = monitored
    save_data()
    await update.message.reply_text(f"✅ *{name}* monitor se hata diya gaya.", parse_mode="Markdown")


# ─────────────────────────────────────────────
# /listchats
# ─────────────────────────────────────────────
async def listchats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    monitored = get_monitored()
    lid = get_lecture_id()

    lines = []
    if lid:
        lines.append(f"📌 *Lecture Group:* {config.get('lecture_group_name', 'Unknown')} (`{lid}`)\n")

    if not monitored:
        lines.append("📋 Abhi koi monitored chat nahi hai.\n`/addchat <chat_id>` se add karo.")
    else:
        lines.append("👁️ *Monitored Chats:*")
        for cid, info in monitored.items():
            name = info.get("name", "Unknown")
            ctype = info.get("type", "")
            icon = "📢" if "channel" in ctype else "👥"
            lines.append(f"{icon} *{name}* (`{cid}`)")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


# ─────────────────────────────────────────────
# /status
# ─────────────────────────────────────────────
async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lid = get_lecture_id()
    monitored = get_monitored()
    banned = config.get("banned_users", [])
    owner_id = config.get("bot_owner_id")

    if lid:
        try:
            bot_member = await context.bot.get_chat_member(lid, context.bot.id)
            bot_status = "✅ Admin" if bot_member.status == ChatMember.ADMINISTRATOR else "⚠️ Admin nahi"
        except TelegramError:
            bot_status = "❌ Check nahi hua"
    else:
        bot_status = "N/A"

    await update.message.reply_text(
        f"🤖 *Bot Status*\n\n"
        f"📌 Lecture Group: *{config.get('lecture_group_name', 'Set nahi')}*\n"
        f"🔑 Bot in Lecture Group: {bot_status}\n"
        f"👁️ Monitored Chats: *{len(monitored)}*\n"
        f"🚫 Total Bans: *{len(banned)}*\n"
        f"👑 Owner ID: `{owner_id}`",
        parse_mode="Markdown",
    )


# ─────────────────────────────────────────────
# /checkall
# ─────────────────────────────────────────────
async def checkall(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    lid = get_lecture_id()
    if not lid:
        await update.message.reply_text("❌ Lecture group set nahi hai.")
        return

    is_admin = await is_lecture_admin(context, user_id)
    is_owner = await is_bot_owner(user_id)
    if not (is_admin or is_owner):
        await update.message.reply_text("❌ Sirf lecture group admins ye command use kar sakte hain.")
        return

    monitored = get_monitored()
    if not monitored:
        await update.message.reply_text("❌ Koi monitored chat nahi hai. `/addchat` se add karo.", parse_mode="Markdown")
        return

    msg = await update.message.reply_text("⏳ Saare members check ho rahe hain...")
    banned_count = 0
    checked_count = 0
    errors = []

    try:
        lecture_members = []
        async for member in context.bot.get_chat_members(lid):
            if not member.user.is_bot and member.status not in [ChatMember.LEFT, ChatMember.BANNED]:
                lecture_members.append(member.user)
    except TelegramError as e:
        await msg.edit_text(f"❌ Lecture group members nahi mile: {e}")
        return

    for user in lecture_members:
        checked_count += 1
        should_ban = False
        ban_reason_chat = None

        for cid, info in monitored.items():
            try:
                m = await context.bot.get_chat_member(int(cid), user.id)
                if m.status in [ChatMember.LEFT, ChatMember.BANNED]:
                    should_ban = True
                    ban_reason_chat = info.get("name", cid)
                    break
            except TelegramError:
                pass

        if should_ban:
            try:
                await context.bot.ban_chat_member(lid, user.id)
                banned_list = config.get("banned_users", [])
                if user.id not in banned_list:
                    banned_list.append(user.id)
                    config["banned_users"] = banned_list
                    save_data()
                banned_count += 1
                logger.info(f"Banned {user.id} ({user.full_name}) — not in {ban_reason_chat}")
            except TelegramError as e:
                errors.append(f"{user.full_name}: {e}")

    result_text = (
        f"✅ *Check Complete!*\n\n"
        f"👥 Members checked: `{checked_count}`\n"
        f"🚫 Members banned: `{banned_count}`"
    )
    if errors:
        result_text += f"\n\n⚠️ Errors ({len(errors)}):\n" + "\n".join(errors[:5])

    await msg.edit_text(result_text, parse_mode="Markdown")


# ─────────────────────────────────────────────
# /mycheck  (member khud apna check kare)
# ─────────────────────────────────────────────
async def mycheck(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    lid = get_lecture_id()
    monitored = get_monitored()

    if not lid:
        await update.message.reply_text("❌ Bot abhi configure nahi hua.")
        return

    try:
        lm = await context.bot.get_chat_member(lid, user_id)
        if lm.status in [ChatMember.LEFT, ChatMember.BANNED]:
            await update.message.reply_text("❌ Aap lecture group ke member nahi hain.")
            return
    except TelegramError:
        await update.message.reply_text("❌ Aapka lecture group membership check nahi ho paya.")
        return

    if not monitored:
        await update.message.reply_text("✅ Koi monitored chat nahi hai abhi.")
        return

    lines = ["📋 *Aapka Membership Status:*\n"]
    all_ok = True

    for cid, info in monitored.items():
        name = info.get("name", cid)
        try:
            m = await context.bot.get_chat_member(int(cid), user_id)
            if m.status in [ChatMember.LEFT, ChatMember.BANNED]:
                lines.append(f"❌ *{name}* — Aap member nahi hain")
                all_ok = False
            else:
                lines.append(f"✅ *{name}* — Joined")
        except TelegramError:
            lines.append(f"⚠️ *{name}* — Check nahi hua")

    if all_ok:
        lines.append("\n🎉 Aap saare required chats me hain!")
    else:
        lines.append("\n⚠️ Jo chats me nahi hain, unhe jaldi join karo varna lecture group se ban ho sakte ho!")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


# ─────────────────────────────────────────────
# /rules
# ─────────────────────────────────────────────
async def rules(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lid = get_lecture_id()
    monitored = get_monitored()
    lecture_name = config.get("lecture_group_name", "Lecture Group")

    lines = [
        f"📜 *{lecture_name} — Rules*\n",
        "1️⃣ Saare required groups/channels me member rehna zaroori hai.",
        "2️⃣ Agar aap kisi bhi monitored group ya channel se leave karte ho, toh aapko lecture group se ban kar diya jayega.",
        "3️⃣ Rejoining ke liye admin se contact karo.",
        "",
        "👁️ *Monitored Chats (inn me member rehna zaroori hai):*",
    ]

    if monitored:
        for cid, info in monitored.items():
            name = info.get("name", cid)
            ctype = info.get("type", "")
            icon = "📢" if "channel" in ctype else "👥"
            lines.append(f"{icon} {name}")
    else:
        lines.append("(Abhi koi monitored chat set nahi hai)")

    lines.append("\n`/mycheck` se apna status check karo.")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


# ─────────────────────────────────────────────
# /unbanuser
# ─────────────────────────────────────────────
async def unbanuser(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    lid = get_lecture_id()
    if not lid:
        await update.message.reply_text("❌ Lecture group set nahi hai.")
        return

    is_admin = await is_lecture_admin(context, user_id)
    is_owner = await is_bot_owner(user_id)
    if not (is_admin or is_owner):
        await update.message.reply_text("❌ Sirf admins ye command use kar sakte hain.")
        return

    if not context.args:
        await update.message.reply_text("Usage: `/unbanuser <user_id>`", parse_mode="Markdown")
        return

    try:
        target_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Invalid user ID.")
        return

    try:
        await context.bot.unban_chat_member(lid, target_id)
        banned_list = config.get("banned_users", [])
        if target_id in banned_list:
            banned_list.remove(target_id)
            config["banned_users"] = banned_list
            save_data()
        await update.message.reply_text(f"✅ User `{target_id}` ko unban kar diya gaya.", parse_mode="Markdown")
    except TelegramError as e:
        await update.message.reply_text(f"❌ Unban nahi ho paya: {e}")


# ─────────────────────────────────────────────
# Chat Member Handler
# ─────────────────────────────────────────────
async def track_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    result = update.chat_member
    if result is None:
        return

    chat_id = result.chat.id
    user = result.new_chat_member.user
    new_status = result.new_chat_member.status
    old_status = result.old_chat_member.status if result.old_chat_member else None

    if user.is_bot:
        return

    lid = get_lecture_id()
    monitored = get_monitored()

    if lid and chat_id == lid:
        logger.info(f"Lecture group member update: {user.id} ({user.full_name}) — {old_status} → {new_status}")
        return

    if str(chat_id) in monitored:
        was_member = old_status in [ChatMember.MEMBER, ChatMember.ADMINISTRATOR, ChatMember.OWNER, ChatMember.RESTRICTED]
        now_left = new_status in [ChatMember.LEFT, ChatMember.BANNED]

        if was_member and now_left and lid:
            logger.info(f"User {user.id} left monitored chat {chat_id}. Checking lecture group...")
            try:
                lect_member = await context.bot.get_chat_member(lid, user.id)
                if lect_member.status not in [ChatMember.LEFT, ChatMember.BANNED]:
                    try:
                        await context.bot.ban_chat_member(lid, user.id)
                        banned_list = config.get("banned_users", [])
                        if user.id not in banned_list:
                            banned_list.append(user.id)
                            config["banned_users"] = banned_list
                            save_data()

                        chat_name = monitored[str(chat_id)].get("name", str(chat_id))
                        logger.info(f"Banned {user.id} from lecture group for leaving {chat_name}")

                        try:
                            await context.bot.send_message(
                                lid,
                                f"🚫 *{user.full_name}* ko ban kar diya gaya.\n"
                                f"Reason: *{chat_name}* se leave kiya.",
                                parse_mode="Markdown",
                            )
                        except TelegramError:
                            pass

                    except TelegramError as e:
                        logger.error(f"Ban failed for {user.id}: {e}")
            except TelegramError as e:
                logger.error(f"Could not check lecture membership for {user.id}: {e}")


# ─────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────
def main():
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN environment variable set nahi hai!")
        return

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", start))
    app.add_handler(CommandHandler("setlecturegroup", setlecturegroup))
    app.add_handler(CommandHandler("addchat", addchat))
    app.add_handler(CommandHandler("removechat", removechat))
    app.add_handler(CommandHandler("listchats", listchats))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("checkall", checkall))
    app.add_handler(CommandHandler("mycheck", mycheck))
    app.add_handler(CommandHandler("rules", rules))
    app.add_handler(CommandHandler("unbanuser", unbanuser))
    app.add_handler(ChatMemberHandler(track_chat_member, ChatMemberHandler.ANY_CHAT_MEMBER))

    logger.info("Bot start ho raha hai...")
    app.run_polling(allowed_updates=["message", "chat_member"])


if __name__ == "__main__":
    main()
