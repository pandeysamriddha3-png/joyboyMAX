import asyncio
import logging
import os
import re
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ChatMemberStatus, ChatType, ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    ChatPermissions,
    Message,
)
from dotenv import load_dotenv


# ============================================================
# CONFIG
# ============================================================

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    raise RuntimeError(
        "BOT_TOKEN is missing. Create a .env file and add:\n"
        "BOT_TOKEN=YOUR_BOT_TOKEN"
    )


# ============================================================
# BOT SETUP
# ============================================================

logging.basicConfig(level=logging.INFO)

bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
)

dp = Dispatcher()


# ============================================================
# TEMPORARY IN-MEMORY STORAGE
# Everything disappears when the bot restarts.
# ============================================================

# {chat_id: {user_id: warning_count}}
warnings = defaultdict(lambda: defaultdict(int))

# {chat_id: set("badword", "another word")}
filters = defaultdict(set)

# {chat_id: settings}
group_settings = defaultdict(
    lambda: {
        "warn_limit": 3,
        "welcome": True,
        "welcome_text": "Welcome join @joboyMM, {mention}! 👋",
        "antispam": True,
        "antilink": False,
    }
)

# Spam tracking:
# {(chat_id, user_id): deque[timestamps]}
spam_tracker = defaultdict(lambda: deque(maxlen=10))


# ============================================================
# HELPERS
# ============================================================

async def is_admin(message: Message) -> bool:
    """Check whether the message sender is a Telegram admin."""
    if not message.from_user:
        return False

    member = await bot.get_chat_member(
        message.chat.id,
        message.from_user.id,
    )

    return member.status in {
        ChatMemberStatus.ADMINISTRATOR,
        ChatMemberStatus.CREATOR,
    }


async def is_reply_to_user(message: Message):
    """Return replied-to user."""
    if message.reply_to_message and message.reply_to_message.from_user:
        return message.reply_to_message.from_user

    return None


def mention(user) -> str:
    """Create an HTML mention."""
    name = user.full_name.replace("<", "&lt;").replace(">", "&gt;")
    return f'<a href="tg://user?id={user.id}">{name}</a>'


def parse_duration(text: str):
    """
    Parse durations:
    30s
    10m
    2h
    1d
    """
    match = re.fullmatch(r"(\d+)(s|m|h|d)", text.lower())

    if not match:
        return None

    amount = int(match.group(1))
    unit = match.group(2)

    multipliers = {
        "s": 1,
        "m": 60,
        "h": 3600,
        "d": 86400,
    }

    return timedelta(seconds=amount * multipliers[unit])


def get_command_args(message: Message):
    """Get text after command."""
    if not message.text:
        return []

    parts = message.text.split(maxsplit=1)

    if len(parts) == 1:
        return []

    return parts[1].split()


def get_full_args(message: Message):
    """Get complete argument string."""
    if not message.text:
        return ""

    parts = message.text.split(maxsplit=1)

    return parts[1] if len(parts) > 1 else ""


# ============================================================
# START
# ============================================================

@dp.message(CommandStart())
async def start(message: Message):
    await message.answer(
        "👋 <b>walcome to joyboy MAX </b>\n\n"
        "I'm online.\n\n"
        "Use /help to see commands."
    )


# ============================================================
# HELP
# ============================================================

@dp.message(Command("help"))
async def help_command(message: Message):
    await message.answer(
        "<b>🛡️ Moderation</b>\n"
        "/ban — ban replied user\n"
        "/unban — unban user by ID\n"
        "/mute 10m — mute replied user\n"
        "/unmute — unmute replied user\n"
        "/kick — kick replied user\n"
        "/purge 20 — delete messages\n\n"

        "<b>⚠️ Warnings</b>\n"
        "/warn reason — warn replied user\n"
        "/warnings — show warnings\n"
        "/resetwarns — reset warnings\n"
        "/setwarnlimit 3 — warning limit\n\n"

        "<b>🚫 Filters</b>\n"
        "/filter word\n"
        "/filters\n"
        "/stopfilter word\n\n"

        "<b>👋 Welcome</b>\n"
        "/welcome on\n"
        "/welcome off\n"
        "/setwelcome message\n\n"

        "<b>⚙️ Settings</b>\n"
        "/settings\n"
        "/antilink on\n"
        "/antilink off\n\n"

        "<b>👤 User</b>\n"
        "/id\n"
        "/info"
    )


# ============================================================
# BAN
# ============================================================

@dp.message(Command("ban"))
async def ban_user(message: Message):
    if not await is_admin(message):
        return await message.answer("❌ Admins only.")

    user = await is_reply_to_user(message)

    if not user:
        return await message.answer(
            "Reply to the user you want to ban."
        )

    if user.id == message.from_user.id:
        return await message.answer("❌ You can't ban yourself.")

    try:
        await bot.ban_chat_member(
            chat_id=message.chat.id,
            user_id=user.id,
        )

        await message.answer(
            f"🔨 <b>Banned</b>\n"
            f"User: {mention(user)}"
        )

    except Exception as e:
        logging.exception(e)
        await message.answer(
            "❌ I couldn't ban that user. "
            "Make sure I have permission to ban members."
        )


# ============================================================
# UNBAN
# ============================================================

@dp.message(Command("unban"))
async def unban_user(message: Message):
    if not await is_admin(message):
        return await message.answer("❌ Admins only.")

    args = get_command_args(message)

    if not args:
        return await message.answer(
            "Usage:\n/unban USER_ID"
        )

    try:
        user_id = int(args[0])

        await bot.unban_chat_member(
            chat_id=message.chat.id,
            user_id=user_id,
            only_if_banned=True,
        )

        await message.answer(
            f"✅ User <code>{user_id}</code> unbanned."
        )

    except ValueError:
        await message.answer("❌ User ID must be a number.")

    except Exception as e:
        logging.exception(e)
        await message.answer(
            "❌ Couldn't unban that user."
        )


# ============================================================
# MUTE
# ============================================================

@dp.message(Command("mute"))
async def mute_user(message: Message):
    if not await is_admin(message):
        return await message.answer("❌ Admins only.")

    user = await is_reply_to_user(message)

    if not user:
        return await message.answer(
            "Reply to a user.\nExample: /mute 10m"
        )

    args = get_command_args(message)

    if not args:
        return await message.answer(
            "Usage: /mute 10m\n"
            "Examples: 30s, 10m, 2h, 1d"
        )

    duration = parse_duration(args[0])

    if not duration:
        return await message.answer(
            "❌ Invalid duration.\n"
            "Use 30s, 10m, 2h or 1d."
        )

    until = datetime.now(timezone.utc) + duration

    try:
        await bot.restrict_chat_member(
            chat_id=message.chat.id,
            user_id=user.id,
            permissions=ChatPermissions(
                can_send_messages=False
            ),
            until_date=until,
        )

        await message.answer(
            f"🔇 <b>Muted</b>\n"
            f"User: {mention(user)}\n"
            f"Duration: <code>{args[0]}</code>"
        )

    except Exception as e:
        logging.exception(e)
        await message.answer(
            "❌ Couldn't mute that user."
        )


# ============================================================
# UNMUTE
# ============================================================

@dp.message(Command("unmute"))
async def unmute_user(message: Message):
    if not await is_admin(message):
        return await message.answer("❌ Admins only.")

    user = await is_reply_to_user(message)

    if not user:
        return await message.answer(
            "Reply to the user you want to unmute."
        )

    try:
        await bot.restrict_chat_member(
            chat_id=message.chat.id,
            user_id=user.id,
            permissions=ChatPermissions(
                can_send_messages=True,
                can_send_audios=True,
                can_send_documents=True,
                can_send_photos=True,
                can_send_videos=True,
                can_send_video_notes=True,
                can_send_voice_notes=True,
                can_send_polls=True,
                can_send_other_messages=True,
                can_add_web_page_previews=True,
            ),
        )

        await message.answer(
            f"🔊 <b>Unmuted</b> {mention(user)}"
        )

    except Exception as e:
        logging.exception(e)
        await message.answer(
            "❌ Couldn't unmute that user."
        )


# ============================================================
# KICK
# ============================================================

@dp.message(Command("kick"))
async def kick_user(message: Message):
    if not await is_admin(message):
        return await message.answer("❌ Admins only.")

    user = await is_reply_to_user(message)

    if not user:
        return await message.answer(
            "Reply to the user you want to kick."
        )

    try:
        # Ban + immediately unban = kick
        await bot.ban_chat_member(
            message.chat.id,
            user.id,
        )

        await bot.unban_chat_member(
            message.chat.id,
            user.id,
        )

        await message.answer(
            f"👢 <b>Kicked</b> {mention(user)}"
        )

    except Exception as e:
        logging.exception(e)
        await message.answer(
            "❌ Couldn't kick that user."
        )


# ============================================================
# WARN
# ============================================================

@dp.message(Command("warn"))
async def warn_user(message: Message):
    if not await is_admin(message):
        return await message.answer("❌ Admins only.")

    user = await is_reply_to_user(message)

    if not user:
        return await message.answer(
            "Reply to a user to warn them."
        )

    reason = get_full_args(message)

    if reason.startswith("@"):
        reason = ""

    warnings[message.chat.id][user.id] += 1

    count = warnings[message.chat.id][user.id]
    limit = group_settings[message.chat.id]["warn_limit"]

    await message.answer(
        f"⚠️ <b>Warning</b>\n"
        f"User: {mention(user)}\n"
        f"Reason: {reason or 'No reason provided'}\n"
        f"Warnings: <b>{count}/{limit}</b>"
    )

    # Automatic action
    if count >= limit:
        try:
            await bot.restrict_chat_member(
                message.chat.id,
                user.id,
                permissions=ChatPermissions(
                    can_send_messages=False
                ),
            )

            warnings[message.chat.id][user.id] = 0

            await message.answer(
                f"🔇 {mention(user)} reached the warning limit "
                f"and has been muted."
            )

        except Exception:
            logging.exception("Automatic warning action failed.")


# ============================================================
# SHOW WARNINGS
# ============================================================

@dp.message(Command("warnings"))
async def show_warnings(message: Message):
    user = await is_reply_to_user(message)

    if not user:
        user = message.from_user

    count = warnings[message.chat.id][user.id]
    limit = group_settings[message.chat.id]["warn_limit"]

    await message.answer(
        f"⚠️ {mention(user)} has "
        f"<b>{count}/{limit}</b> warnings."
    )


# ============================================================
# RESET WARNINGS
# ============================================================

@dp.message(Command("resetwarns"))
async def reset_warnings(message: Message):
    if not await is_admin(message):
        return await message.answer("❌ Admins only.")

    user = await is_reply_to_user(message)

    if not user:
        return await message.answer(
            "Reply to the user."
        )

    warnings[message.chat.id][user.id] = 0

    await message.answer(
        f"✅ Warnings reset for {mention(user)}."
    )


# ============================================================
# SET WARNING LIMIT
# ============================================================

@dp.message(Command("setwarnlimit"))
async def set_warn_limit(message: Message):
    if not await is_admin(message):
        return await message.answer("❌ Admins only.")

    args = get_command_args(message)

    if not args:
        return await message.answer(
            "Usage: /setwarnlimit 3"
        )

    try:
        limit = int(args[0])

        if limit < 1 or limit > 20:
            raise ValueError

        group_settings[message.chat.id]["warn_limit"] = limit

        await message.answer(
            f"✅ Warning limit set to <b>{limit}</b>."
        )

    except ValueError:
        await message.answer(
            "❌ Choose a number from 1 to 20."
        )


# ============================================================
# PURGE
# ============================================================

@dp.message(Command("purge"))
async def purge_messages(message: Message):
    if not await is_admin(message):
        return await message.answer("❌ Admins only.")

    args = get_command_args(message)

    if not args:
        return await message.answer(
            "Usage: /purge 20"
        )

    try:
        amount = int(args[0])

        if amount < 1 or amount > 100:
            raise ValueError

    except ValueError:
        return await message.answer(
            "❌ Use a number between 1 and 100."
        )

    deleted = 0

    # Delete command message first
    try:
        await message.delete()
    except Exception:
        pass

    # Telegram message IDs are sequential.
    start_id = message.message_id - 1

    for msg_id in range(start_id, max(0, start_id - amount), -1):
        try:
            await bot.delete_message(
                message.chat.id,
                msg_id,
            )

            deleted += 1

        except Exception:
            pass

    confirmation = await bot.send_message(
        message.chat.id,
        f"🧹 Deleted <b>{deleted}</b> messages.",
    )

    await asyncio.sleep(3)

    try:
        await confirmation.delete()
    except Exception:
        pass


# ============================================================
# FILTER ADD
# ============================================================

@dp.message(Command("filter"))
async def add_filter(message: Message):
    if not await is_admin(message):
        return await message.answer("❌ Admins only.")

    word = get_full_args(message).strip().lower()

    if not word:
        return await message.answer(
            "Usage: /filter badword"
        )

    filters[message.chat.id].add(word)

    await message.answer(
        f"🚫 Filter added: <code>{word}</code>"
    )


# ============================================================
# FILTER LIST
# ============================================================

@dp.message(Command("filters"))
async def list_filters(message: Message):
    items = filters[message.chat.id]

    if not items:
        return await message.answer(
            "✅ No filters configured."
        )

    text = "\n".join(
        f"• <code>{word}</code>"
        for word in sorted(items)
    )

    await message.answer(
        f"<b>🚫 Filters</b>\n\n{text}"
    )


# ============================================================
# FILTER REMOVE
# ============================================================

@dp.message(Command("stopfilter"))
async def remove_filter(message: Message):
    if not await is_admin(message):
        return await message.answer("❌ Admins only.")

    word = get_full_args(message).strip().lower()

    if not word:
        return await message.answer(
            "Usage: /stopfilter badword"
        )

    if word in filters[message.chat.id]:
        filters[message.chat.id].remove(word)

        await message.answer(
            f"✅ Filter removed: <code>{word}</code>"
        )
    else:
        await message.answer(
            "❌ That filter doesn't exist."
        )


# ============================================================
# WELCOME SETTINGS
# ============================================================

@dp.message(Command("welcome"))
async def welcome_setting(message: Message):
    if not await is_admin(message):
        return await message.answer("❌ Admins only.")

    args = get_command_args(message)

    if not args or args[0].lower() not in {"on", "off"}:
        return await message.answer(
            "Usage:\n"
            "/welcome on\n"
            "/welcome off"
        )

    enabled = args[0].lower() == "on"

    group_settings[message.chat.id]["welcome"] = enabled

    await message.answer(
        f"👋 Welcome messages: "
        f"<b>{'ON' if enabled else 'OFF'}</b>"
    )


# ============================================================
# SET WELCOME MESSAGE
# ============================================================

@dp.message(Command("setwelcome"))
async def set_welcome(message: Message):
    if not await is_admin(message):
        return await message.answer("❌ Admins only.")

    text = get_full_args(message).strip()

    if not text:
        return await message.answer(
            "Usage:\n"
            "/setwelcome Welcome {mention}! 👋"
        )

    group_settings[message.chat.id]["welcome_text"] = text

    await message.answer(
        "✅ Welcome message updated."
    )


# ============================================================
# NEW MEMBER WELCOME
# ============================================================

@dp.message(F.new_chat_members)
async def welcome_new_members(message: Message):
    settings = group_settings[message.chat.id]

    if not settings["welcome"]:
        return

    for user in message.new_chat_members:
        text = settings["welcome_text"]

        text = text.replace(
            "{mention}",
            mention(user),
        )

        text = text.replace(
            "{name}",
            user.full_name,
        )

        text = text.replace(
            "{username}",
            f"@{user.username}"
            if user.username
            else user.full_name,
        )

        await message.answer(text)


# ============================================================
# SETTINGS
# ============================================================

@dp.message(Command("settings"))
async def settings_command(message: Message):
    settings = group_settings[message.chat.id]

    await message.answer(
        "<b>⚙️ Group Settings</b>\n\n"
        f"Warning limit: <b>{settings['warn_limit']}</b>\n"
        f"Welcome: <b>{'ON' if settings['welcome'] else 'OFF'}</b>\n"
        f"Anti-spam: <b>{'ON' if settings['antispam'] else 'OFF'}</b>\n"
        f"Anti-link: <b>{'ON' if settings['antilink'] else 'OFF'}</b>"
    )


# ============================================================
# ANTI-LINK
# ============================================================

@dp.message(Command("antilink"))
async def antilink_setting(message: Message):
    if not await is_admin(message):
        return await message.answer("❌ Admins only.")

    args = get_command_args(message)

    if not args or args[0].lower() not in {"on", "off"}:
        return await message.answer(
            "Usage:\n"
            "/antilink on\n"
            "/antilink off"
        )

    enabled = args[0].lower() == "on"

    group_settings[message.chat.id]["antilink"] = enabled

    await message.answer(
        f"🔗 Anti-link: "
        f"<b>{'ON' if enabled else 'OFF'}</b>"
    )


# ============================================================
# USER ID
# ============================================================

@dp.message(Command("id"))
async def user_id(message: Message):
    user = await is_reply_to_user(message)

    if not user:
        user = message.from_user

    await message.answer(
        f"👤 <b>User information</b>\n\n"
        f"Name: {mention(user)}\n"
        f"ID: <code>{user.id}</code>\n"
        f"Username: "
        f"<code>@{user.username}</code>"
        if user.username
        else
        f"👤 <b>User information</b>\n\n"
        f"Name: {mention(user)}\n"
        f"ID: <code>{user.id}</code>"
    )


# ============================================================
# INFO
# ============================================================

@dp.message(Command("info"))
async def info_command(message: Message):
    user = await is_reply_to_user(message)

    if not user:
        user = message.from_user

    try:
        member = await bot.get_chat_member(
            message.chat.id,
            user.id,
        )

        role = member.status.value

    except Exception:
        role = "unknown"

    warn_count = warnings[message.chat.id][user.id]

    await message.answer(
        f"<b>👤 User Info</b>\n\n"
        f"Name: {mention(user)}\n"
        f"ID: <code>{user.id}</code>\n"
        f"Username: "
        f"<code>@{user.username}</code>\n"
        f"Role: <b>{role}</b>\n"
        f"Warnings: <b>{warn_count}</b>"
    )


# ============================================================
# ANTI-SPAM + FILTER + ANTI-LINK
# ============================================================

URL_PATTERN = re.compile(
    r"(https?://\S+|www\.\S+|t\.me/\S+)",
    re.IGNORECASE,
)


@dp.message(F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP}))
async def message_security(message: Message):
    if not message.from_user:
        return

    # Don't moderate admins.
    if await is_admin(message):
        return

    chat_id = message.chat.id
    user_id = message.from_user.id
    text = message.text or message.caption or ""

    settings = group_settings[chat_id]

    # --------------------------------------------------------
    # FILTERS
    # --------------------------------------------------------

    lowered = text.lower()

    for word in filters[chat_id]:
        if word in lowered:
            try:
                await message.delete()
            except Exception:
                pass

            return

    # --------------------------------------------------------
    # ANTI-LINK
    # --------------------------------------------------------

    if settings["antilink"] and URL_PATTERN.search(text):
        try:
            await message.delete()
        except Exception:
            pass

        return

    # --------------------------------------------------------
    # FLOOD CONTROL
    # 6 messages within 8 seconds
    # --------------------------------------------------------

    if settings["antispam"]:
        now = time.monotonic()

        key = (chat_id, user_id)

        timestamps = spam_tracker[key]

        timestamps.append(now)

        while timestamps and now - timestamps[0] > 8:
            timestamps.popleft()

        if len(timestamps) >= 6:
            try:
                await bot.restrict_chat_member(
                    chat_id,
                    user_id,
                    permissions=ChatPermissions(
                        can_send_messages=False
                    ),
                    until_date=datetime.now(timezone.utc)
                    + timedelta(seconds=30),
                )

                await message.answer(
                    f"🛑 {mention(message.from_user)} "
                    f"was muted for 30 seconds "
                    f"because of flooding."
                )

            except Exception:
                logging.exception(
                    "Anti-spam restriction failed."
                )

            timestamps.clear()


# ============================================================
# RUN
# ============================================================

async def main():
    print("====================================")
    print(" Rose-style Telegram Bot")
    print(" Running locally")
    print(" No database")
    print("====================================")

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
