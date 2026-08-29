import asyncio
import threading
import sqlite3
import time
import re
from datetime import datetime
from pathlib import Path

import telebot
from telebot.types import ChatPermissions

from telethon import TelegramClient, events
from telethon.tl.functions.channels import (
    CreateChannelRequest,
    EditAdminRequest,
    EditPhotoRequest,
    InviteToChannelRequest,
    GetParticipantsRequest,
    EditTitleRequest
)
from telethon.tl.functions.messages import (
    ExportChatInviteRequest,
    EditChatAboutRequest
)
from telethon.tl.types import ChatAdminRights, InputChatUploadedPhoto, ChannelParticipantsSearch

# ==========================
# CONFIGURATION
# ==========================

API_ID = 38104096
API_HASH = "55151dd94726a5c2ed278ef7cdea5fdf"

BOT_TOKEN = "8856194855:AAEzXnsUtc1yEYxyerBjOxj-ow0cpzCs2AE"
OWNER_ID = 8587658245
BOT_USERNAME = "ArddyMMBot"
SESSION = "arddymm"

PFP_CHANNEL = "mmpfps"
PFP_FILE = "pfp.jpg"

GROUP_NAME = "Arddy MM | Waiting For Deal"
GROUP_ABOUT = """Arddy MM Official Middleman

👤 Owner : @arrdymm
📢 Channel : @miideals"""

UPI_ID = "vikasgupta147@fam"
OWNER_USERNAME = "@arddymm"
CHANNEL_USERNAME = "@miideals"

WELCOME_MESSAGE = """🤝 **Welcome to Arddy MM**

Please fill the deal details using the format below and send it in this group.

━━━━━━━━━━━━━━━
📋 **DEAL FORMAT**

👤 Buyer:
👤 Seller:
📦 Service:
💰 Amount:
📝 Conditions:

Managed by:
@arddymm • @miideals"""

VOUCH_MESSAGE = """Thanks for using my MM service ! 🤝

Please leave a vouch in our official vouch channel.

Leave a vouch : <a href="https://t.me/miidlemam/18?comment=12">Voucher Channel</a>

📋 VOUCH FORMAT (Tap to Copy)

Format : <code>Vouch @arrdymm for MM'd</code>

Thank you for choosing Arddy MM Service."""

# ==========================
# DATABASE & LOG STORAGE SETUP
# ==========================

db = sqlite3.connect("deals.db", check_same_thread=False)
cursor = db.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS deals(
    chat_id INTEGER PRIMARY KEY,
    amount REAL,
    currency TEXT DEFAULT 'INR',
    start_time TEXT,
    end_time TEXT
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS msg_logs(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER,
    message_id INTEGER,
    user_name TEXT,
    original_text TEXT,
    edited_text TEXT,
    status TEXT, -- 'EDITED' or 'DELETED'
    timestamp TEXT
)
""")
db.commit()

msg_cache = {}

def save_amount(chat_id, amount, currency="INR"):
    cursor.execute(
        "INSERT OR REPLACE INTO deals(chat_id, amount, currency, start_time, end_time) "
        "VALUES(?, ?, ?, (SELECT start_time FROM deals WHERE chat_id=?), (SELECT end_time FROM deals WHERE chat_id=?))",
        (chat_id, amount, currency, chat_id, chat_id)
    )
    db.commit()

def save_tat(chat_id, start_time, end_time=None):
    cursor.execute(
        "UPDATE deals SET start_time=?, end_time=? WHERE chat_id=?",
        (start_time, end_time, chat_id)
    )
    if cursor.rowcount == 0:
        cursor.execute(
            "INSERT INTO deals(chat_id, amount, currency, start_time, end_time) VALUES(?, 0, 'INR', ?, ?)",
            (chat_id, start_time, end_time)
        )
    db.commit()

def get_deal(chat_id):
    cursor.execute("SELECT amount, currency, start_time, end_time FROM deals WHERE chat_id=?", (chat_id,))
    row = cursor.fetchone()
    if row:
        return row[0], row[1], row[2], row[3]
    return 0, "INR", None, None

def log_edited_msg(chat_id, message_id, user_name, orig_text, new_text):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute(
        "INSERT INTO msg_logs(chat_id, message_id, user_name, original_text, edited_text, status, timestamp) "
        "VALUES(?, ?, ?, ?, ?, 'EDITED', ?)",
        (chat_id, message_id, user_name, orig_text, new_text, now)
    )
    db.commit()

def log_deleted_msg(chat_id, message_id, user_name, orig_text):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute(
        "INSERT INTO msg_logs(chat_id, message_id, user_name, original_text, edited_text, status, timestamp) "
        "VALUES(?, ?, ?, ?, '', 'DELETED', ?)",
        (chat_id, message_id, user_name, orig_text, now)
    )
    db.commit()

def get_logs(chat_id):
    cursor.execute(
        "SELECT user_name, original_text, edited_text, status, timestamp FROM msg_logs WHERE chat_id=? ORDER BY id ASC",
        (chat_id,)
    )
    return cursor.fetchall()

def clear_logs(chat_id):
    cursor.execute("DELETE FROM msg_logs WHERE chat_id=?", (chat_id,))
    cursor.execute("DELETE FROM deals WHERE chat_id=?", (chat_id,))
    db.commit()

# ==========================
# BOT CLIENT (pyTelegramBotAPI)
# ==========================

bot = telebot.TeleBot(BOT_TOKEN)

def calculate_fee(amount):
    if amount <= 49:
        return 0
    elif amount <= 200:
        return 10
    elif amount <= 400:
        return 15
    elif amount <= 600:
        return 20
    elif amount <= 800:
        return 25
    elif amount <= 1000:
        return 30
    else:
        return ((amount + 99) // 100) * 10

def calculate_usd_fee(amount):
    if amount <= 5:
        return 0.5
    elif amount <= 10:
        return 1
    elif amount <= 15:
        return 2
    elif amount <= 20:
        return 3
    elif amount <= 25:
        return 4
    elif amount <= 30:
        return 5
    else:
        return max(5, round(amount * 0.01, 2))

@bot.message_handler(commands=['start'])
def start(message):
    if message.from_user.id != OWNER_ID:
        return
    bot.reply_to(message, "✅ Arddy MM Bot Online")

# SETUP COMMAND (.setup)
@bot.message_handler(func=lambda m: m.text and m.text.lower() == ".setup")
def setup_group(message):
    if message.from_user.id != OWNER_ID:
        return
    try:
        bot.delete_message(message.chat.id, message.message_id)
    except Exception:
        pass

    # Reset Title & Description
    try:
        bot.set_chat_title(message.chat.id, GROUP_NAME)
        bot.set_chat_description(message.chat.id, GROUP_ABOUT)
    except Exception as e:
        print("Setup error:", e)

    # Send & Pin Welcome Message
    w_msg = bot.send_message(message.chat.id, WELCOME_MESSAGE, parse_mode="Markdown")
    try:
        bot.pin_chat_message(message.chat.id, w_msg.message_id, disable_notification=True)
    except Exception:
        pass

# TAT COMMAND LOGIC
@bot.message_handler(func=lambda m: m.text and m.text.lower().startswith(".tat"))
def handle_tat(message):
    if message.from_user.id != OWNER_ID:
        return
    try:
        bot.delete_message(message.chat.id, message.message_id)
    except Exception:
        pass

    args = message.text.split()
    now_str = datetime.now().strftime("%I:%M %p | %d %b %Y")

    if len(args) == 2:
        param = args[1].lower()
        
        if param == "start":
            amount, currency, _, _ = get_deal(message.chat.id)
            if amount == 0:
                bot.send_message(
                    message.chat.id, 
                    "⚠️ **PAYMENT NOT RECEIVED YET!**\n\n`.tat start` tabhi chalega jab pehle payment receive ho jaye.\nPehle `.pay <amount>` aur `.rcv` chalaayein.",
                    parse_mode="Markdown"
                )
                return

            save_tat(message.chat.id, start_time=now_str)
            bot.send_message(
                message.chat.id,
                f"⏱️ **DEAL TAT STARTED**\n\n📅 **Start Time:** `{now_str}`\n⏳ Status: In Progress (Payment Received)\n\nManaged by:\n@arddymm • @miideals",
                parse_mode="Markdown"
            )

        elif param == "end":
            _, _, start_t, _ = get_deal(message.chat.id)
            save_tat(message.chat.id, start_time=start_t or "Not Set", end_time=now_str)
            bot.send_message(
                message.chat.id,
                f"⏱️ **DEAL TAT COMPLETED**\n\n📅 **Start Time:** `{start_t or 'N/A'}`\n🏁 **End Time:** `{now_str}`\n✅ Status: Finished\n\nManaged by:\n@arddymm • @miideals",
                parse_mode="Markdown"
            )

        else:
            match = re.match(r"^(\d+)(m|h)$", param)
            if match:
                val = int(match.group(1))
                unit = match.group(2)
                seconds = val * 60 if unit == "m" else val * 3600
                
                save_tat(message.chat.id, start_time=now_str)
                bot.send_message(
                    message.chat.id,
                    f"⏱️ **CUSTOM TAT TIMER SET**\n\n📅 **Start Time:** `{now_str}`\n⏳ **Limit:** {val} {'Minute(s)' if unit=='m' else 'Hour(s)'}\n🔔 Auto-reminder active!\n\nManaged by:\n@arddymm • @miideals",
                    parse_mode="Markdown"
                )

                def start_timer(chat_id, total_sec):
                    if total_sec > 300:
                        time.sleep(total_sec - 300)
                        bot.send_message(chat_id, "⚠️ **TAT ALERT:** Only 5 minutes remaining for deal release limit!", parse_mode="Markdown")
                        time.sleep(300)
                    else:
                        time.sleep(total_sec)
                    
                    bot.send_message(chat_id, "🚨 **TAT TIME OVER:** Target limit reached! Please check deal status or release payment.", parse_mode="Markdown")

                threading.Thread(target=start_timer, args=(message.chat.id, seconds), daemon=True).start()
            else:
                bot.send_message(message.chat.id, "❌ Invalid Format!\nUse: `.tat start`, `.tat end`, `.tat 1h`, or `.tat 30m`", parse_mode="Markdown")

# .LINK COMMAND
@bot.message_handler(func=lambda m: m.text and m.text.lower() == ".link")
def get_gc_link(message):
    if message.from_user.id != OWNER_ID:
        return
    try:
        bot.delete_message(message.chat.id, message.message_id)
    except Exception:
        pass

    try:
        link = bot.export_chat_invite_link(message.chat.id)
        bot.send_message(
            message.chat.id,
            f"🔗 **Group Invite Link:**\n{link}",
            parse_mode="Markdown"
        )
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Failed to get link: {e}")

# .REVIEW COMMAND
@bot.message_handler(func=lambda m: m.text and m.text.lower() == ".review")
def review_logs(message):
    if message.from_user.id != OWNER_ID:
        return
    try:
        bot.delete_message(message.chat.id, message.message_id)
    except Exception:
        pass

    logs = get_logs(message.chat.id)
    if not logs:
        bot.send_message(message.chat.id, "🔍 **No edited or deleted messages recorded.**", parse_mode="Markdown")
        return

    report = "📋 **MESSAGE AUDIT REVIEW LOGS**\n━━━━━━━━━━━━━━━\n\n"
    for idx, (user, orig, edited, status, ts) in enumerate(logs, 1):
        if status == "EDITED":
            report += f"{idx}. ✏️ **EDITED BY:** {user}\n⏰ Time: {ts}\n❌ **Before:** {orig}\n✅ **After:** {edited}\n\n"
        else:
            report += f"{idx}. 🗑️ **DELETED BY:** {user}\n⏰ Time: {ts}\n📜 **Content:** {orig}\n\n"

    if len(report) > 4000:
        for i in range(0, len(report), 4000):
            bot.send_message(message.chat.id, report[i:i+4000], parse_mode="Markdown")
    else:
        bot.send_message(message.chat.id, report, parse_mode="Markdown")

# PAYMENT COMMANDS (.pay, .payy, .dpay)
@bot.message_handler(func=lambda m: m.text and m.text.lower().split()[0] in ['.pay', '.payy', '.dpay'])
def handle_pay_commands(message):
    if message.from_user.id != OWNER_ID:
        return
    try:
        bot.delete_message(message.chat.id, message.message_id)
    except Exception:
        pass

    args = message.text.split()
    cmd = args[0].lower()

    if len(args) != 2:
        bot.send_message(message.chat.id, f"❌ Usage: {cmd} <amount>")
        return

    try:
        amount = float(args[1]) if cmd == ".dpay" else int(args[1])
    except ValueError:
        bot.send_message(message.chat.id, "❌ Amount must be a number.")
        return

    if amount <= 0:
        bot.send_message(message.chat.id, "❌ Amount must be greater than 0.")
        return

    if cmd == ".dpay":
        save_amount(message.chat.id, amount, "USD")
        fee = calculate_usd_fee(amount)
        total = amount + fee
        bot.send_message(
            message.chat.id,
            f"💵 **PAYMENT REQUEST**\n\n💰 Deal Amount : ${amount:.2f}\n💸 MM Fee : ${fee:.2f}\n💳 Total : ${total:.2f}\n\n🌐 **Available Networks**\n🔹 TRC20 (USDT)\n🔹 BEP20 (USDT)\n🔹 ERC20 (USDT)\n🔹 SOL (USDT)\n\n⚠️ Choose your preferred network and wait for the admin to provide the wallet address.\n\n📸 After payment, send the TXID or payment screenshot.\n\nManaged by:\n@arddymm • @miideals",
            parse_mode="Markdown"
        )
    elif cmd == ".pay":
        save_amount(message.chat.id, amount, "INR")
        fee = calculate_fee(amount)
        total = amount + fee
        bot.send_message(
            message.chat.id,
            f"💳 **PAYMENT REQUEST**\n\n💰 Deal Amount : ₹{amount}\n💸 MM Fee : ₹{fee}\n💵 Total : ₹{total}\n\n🏦 UPI ID : <code>{UPI_ID}</code>\nclick for : <a href=\"https://t.me/ardyqr/2\">Qr</a>\n\n⚠️ Buyer, complete the payment and send screenshot.\n\nManaged by:\n@arddymm • @miideals",
            parse_mode="HTML",
            disable_web_page_preview=True
        )
    elif cmd == ".payy":
        save_amount(message.chat.id, amount, "INR")
        fee = calculate_fee(amount)
        total = amount + fee
        bot.send_message(
            message.chat.id,
            f"💳 **PAYMENT REQUEST**\n\n💰 Deal Amount : ₹{amount}\n💸 MM Fee : ₹{fee}\n💵 Total : ₹{total}\n\n🏦 UPI ID : <code>shinichirohere@nyes</code>\nclick for : <a href=\"https://t.me/arddyhu/2\">Qr</a>\n\n⚠️ Buyer, complete the payment and send screenshot.\n\nManaged by:\n@arddymm • @miideals",
            parse_mode="HTML",
            disable_web_page_preview=True
        )

@bot.message_handler(func=lambda m: m.text and m.text.lower() == ".rcv")
def rcv(message):
    if message.from_user.id != OWNER_ID:
        return
    try:
        bot.delete_message(message.chat.id, message.message_id)
    except Exception:
        pass

    amount, currency, _, _ = get_deal(message.chat.id)
    symbol = "₹" if currency == "INR" else "$"

    try:
        bot.set_chat_title(message.chat.id, f"ARRDY MM | {symbol}{amount} | HOLDING")
    except Exception:
        pass

    received = bot.send_message(
        message.chat.id,
        "✅ **PAYMENT RECEIVED**\n\nI have successfully received and verified both the payment and the MM fee.\n\nThe funds are now securely held by the Middleman. It is safe to proceed with the deal according to the agreed terms.\n\nThe funds will be released only after the deal has been completed successfully and all agreed conditions have been fulfilled.\n\nThank you for your cooperation.\n\nManaged by:\n@arddymm • @miideals",
        parse_mode="Markdown"
    )

    try:
        bot.pin_chat_message(message.chat.id, received.message_id, disable_notification=True)
    except Exception:
        pass

@bot.message_handler(func=lambda m: m.text and m.text.lower() == ".sent")
def sent(message):
    if message.from_user.id != OWNER_ID:
        return
    try:
        bot.delete_message(message.chat.id, message.message_id)
    except Exception:
        pass

    try:
        bot.set_chat_title(message.chat.id, "ARRDY MM | COMPLETED ✅")
    except Exception:
        pass

    released = bot.send_message(
        message.chat.id,
        "✅ **PAYMENT RELEASED**\n\nThe funds have been successfully released to the Seller.\n\nThis Middleman transaction has now been completed successfully.\n\nThank you for choosing Arddy MM.",
        parse_mode="Markdown"
    )

    try:
        bot.pin_chat_message(message.chat.id, released.message_id, disable_notification=True)
    except Exception:
        pass

    bot.send_message(
        message.chat.id,
        VOUCH_MESSAGE,
        parse_mode="HTML",
        disable_web_page_preview=True
    )

@bot.message_handler(func=lambda m: m.text and m.text.lower() == ".lock")
def lock_group(message):
    if message.from_user.id != OWNER_ID:
        return
    try:
        bot.delete_message(message.chat.id, message.message_id)
    except Exception:
        pass

    try:
        bot.set_chat_permissions(message.chat.id, ChatPermissions(can_send_messages=False))
    except Exception:
        return

    bot.send_message(
        message.chat.id,
        "🔒 **GROUP LOCKED**\n\nThis deal has been completed.\n\nOnly admins can send messages.\n\n**WANT TO SUPPORT US?**\n\n✦ PAY AN EXTRA FEE — Every bit of support matters.\n✦ SHARE WITH FRIENDS — Help us reach more people.\n✦ USE OUR SERVICE AGAIN — We’re always here for your future deals.\n\n💬 Buy • Sell • Chat\nJoin @dealups — connect, trade & chat with the community. 🤝\n\nManaged by:\n@arddymm • @miideals",
        parse_mode="Markdown"
    )

@bot.message_handler(func=lambda m: m.text and m.text.lower() == ".unlock")
def unlock_group(message):
    if message.from_user.id != OWNER_ID:
        return
    try:
        bot.delete_message(message.chat.id, message.message_id)
    except Exception:
        pass

    try:
        bot.set_chat_permissions(
            message.chat.id,
            ChatPermissions(can_send_messages=True, can_send_media_messages=True, can_send_other_messages=True)
        )
    except Exception:
        return

    bot.send_message(
        message.chat.id,
        "🔓 **GROUP UNLOCKED**\n\nMembers can now send messages.\n\nManaged by:\n@arddymm • @miideals",
        parse_mode="Markdown"
    )

@bot.message_handler(func=lambda m: m.text and m.text.lower() == ".delete")
def delete_message(message):
    if message.from_user.id != OWNER_ID:
        return

    if not message.reply_to_message:
        bot.reply_to(message, "❌ Reply to a message with .delete")
        return

    try:
        bot.delete_message(message.chat.id, message.message_id)
    except Exception:
        pass

    try:
        user_name = message.reply_to_message.from_user.first_name or "User"
        orig_text = message.reply_to_message.text or "[Non-Text Message]"
        log_deleted_msg(message.chat.id, message.reply_to_message.message_id, user_name, orig_text)
        bot.delete_message(message.chat.id, message.reply_to_message.message_id)
    except Exception:
        bot.send_message(message.chat.id, "❌ Couldn't delete message.")

# REFUND COMMAND (.refund) WITH AUTO VOUCH MESSAGE
@bot.message_handler(func=lambda m: m.text and m.text.lower().startswith(".refund"))
def refund(message):
    if message.from_user.id != OWNER_ID:
        return
    try:
        bot.delete_message(message.chat.id, message.message_id)
    except Exception:
        pass

    args = message.text.split()
    if len(args) != 2:
        bot.send_message(message.chat.id, "Usage: .refund @username")
        return

    username = args[1]
    amount, currency, _, _ = get_deal(message.chat.id)
    symbol = "₹" if currency == "INR" else "$"

    try:
        bot.set_chat_title(message.chat.id, f"ARRDY MM | {symbol}{amount} | REFUNDED")
    except Exception:
        pass

    refunded = bot.send_message(
        message.chat.id,
        f"⚠️ **REFUND COMPLETED**\n\n👤 Refunded To : {username}\n💰 Amount : {symbol}{amount}\n\nThe funds have been refunded successfully.\n\nManaged by:\n@arddymm • @miideals",
        parse_mode="Markdown"
    )

    try:
        bot.pin_chat_message(message.chat.id, refunded.message_id, disable_notification=True)
    except Exception:
        pass

    # Send Vouch Message Automatically after refund
    bot.send_message(
        message.chat.id,
        VOUCH_MESSAGE,
        parse_mode="HTML",
        disable_web_page_preview=True
    )

# Message Caching MUST BE AT THE BOTTOM OF HANDLERS
@bot.message_handler(func=lambda m: True, content_types=['text'])
def cache_messages(message):
    if message.chat.type in ["group", "supergroup"]:
        key = (message.chat.id, message.message_id)
        user_name = message.from_user.first_name or "User"
        if message.from_user.username:
            user_name += f" (@{message.from_user.username})"
        msg_cache[key] = {
            "user_name": user_name,
            "text": message.text
        }

@bot.edited_message_handler(func=lambda m: True)
def handle_edited_message(message):
    if message.chat.type in ["group", "supergroup"]:
        key = (message.chat.id, message.message_id)
        user_name = message.from_user.first_name or "User"
        if message.from_user.username:
            user_name += f" (@{message.from_user.username})"
        
        orig_text = msg_cache.get(key, {}).get("text", "[Original Text Unknown]")
        new_text = message.text or ""
        
        log_edited_msg(message.chat.id, message.message_id, user_name, orig_text, new_text)
        msg_cache[key] = {"user_name": user_name, "text": new_text}

# ==========================
# TELETHON CLIENT (Userbot & Group Management)
# ==========================

userbot = TelegramClient(SESSION, API_ID, API_HASH)

async def download_pfp():
    try:
        messages = await userbot.get_messages(PFP_CHANNEL, limit=1)
        if messages and messages[0].photo:
            await messages[0].download_media(file=PFP_FILE)
            print("PFP Downloaded!")
    except Exception as e:
        print(f"PFP Error: {e}")

@userbot.on(events.NewMessage(pattern=r"^/mm$"))
async def mm_handler(event):
    if not event.is_private or event.sender_id != OWNER_ID:
        return

    sender = await event.get_sender()
    name = sender.first_name or "User"

    try:
        await download_pfp()

        result = await userbot(
            CreateChannelRequest(title=GROUP_NAME, about=GROUP_ABOUT, megagroup=True)
        )
        chat = result.chats[0]

        try:
            if Path(PFP_FILE).exists():
                uploaded = await userbot.upload_file(PFP_FILE)
                await userbot(EditPhotoRequest(channel=chat, photo=InputChatUploadedPhoto(file=uploaded)))
        except Exception as e:
            print("PFP Error:", e)

        try:
            bot_entity = await userbot.get_entity(BOT_USERNAME)
            await userbot(InviteToChannelRequest(channel=chat, users=[bot_entity]))

            bot_admin_rights = ChatAdminRights(
                change_info=True,
                delete_messages=True,
                ban_users=True,
                invite_users=True,
                pin_messages=True,
                manage_call=True,
                other=True,
                add_admins=False,
                anonymous=False
            )

            await userbot(
                EditAdminRequest(
                    channel=chat,
                    user_id=bot_entity,
                    admin_rights=bot_admin_rights,
                    rank="Arddy MM",
                )
            )
        except Exception as e:
            print("Bot Promote Error:", e)

        try:
            owner_entity = await userbot.get_entity(OWNER_ID)
            owner_rights = ChatAdminRights(
                change_info=True, delete_messages=True, ban_users=True,
                invite_users=True, pin_messages=True, add_admins=True,
                manage_call=True, other=True
            )
            await userbot(
                EditAdminRequest(channel=chat, user_id=owner_entity, admin_rights=owner_rights, rank="Owner")
            )
        except Exception as e:
            print("Owner Promote Error:", e)

        invite = await userbot(ExportChatInviteRequest(chat))
        link = invite.link

        await event.reply(
            "✅ **Your MM Group has been created!**\n\n"
            f"👤 **Owner:** {name}\n"
            f"🏷️ **Name:** {GROUP_NAME}\n"
            f"🔗 **Link:** {link}"
        )

    except Exception as e:
        await event.reply(f"❌ **Error Creating Group:**\n`{e}`")

# .CLEAR COMMAND (Kicks non-admins, Deletes Messages, Revokes Link, Resets SAME group)
@userbot.on(events.NewMessage(pattern=r"^\.clear$"))
async def clear_handler(event):
    if event.sender_id != OWNER_ID or not event.is_group:
        return

    chat = await event.get_chat()
    chat_id = event.chat_id

    try:
        status_msg = await event.respond("🔄 **Clearing Group Messages & Resetting...**")

        # 1. GC ke Purane Messages Delete Karna (Up to 100 messages)
        try:
            async for msg in userbot.iter_messages(chat, limit=100):
                try:
                    await msg.delete()
                except Exception:
                    pass
        except Exception as e:
            print("Delete Msg Error:", e)

        # 2. Non-admin members ko remove (kick) karna
        participants = await userbot(GetParticipantsRequest(
            channel=chat, filter=ChannelParticipantsSearch(''), offset=0, limit=200, hash=0
        ))

        for p in participants.users:
            if p.id != OWNER_ID and not p.bot:
                try:
                    await userbot.kick_participant(chat, p.id)
                except Exception:
                    pass

        # 3. Database Logs Aur Deals Clear Karna
        clear_logs(chat_id)

        # 4. Purana Invite Link Revoke karna aur SAME GC ka Naya Link Banana
        new_invite = await userbot(ExportChatInviteRequest(chat))
        new_link = new_invite.link

        # 5. Title Aur Description Reset Karna
        try:
            await userbot(EditTitleRequest(channel=chat, title=GROUP_NAME))
            await userbot(EditChatAboutRequest(peer=chat, about=GROUP_ABOUT))
        except Exception as e:
            print("About Error:", e)

        # 6. Lock Permissions Remove Karna (Unlock)
        try:
            bot.set_chat_permissions(
                chat_id,
                ChatPermissions(can_send_messages=True, can_send_media_messages=True, can_send_other_messages=True)
            )
        except Exception:
            pass

        # Final Success Announcement
        await event.respond(
            f"✅ **Group Cleared & Reset Successfully!**\n\n"
            f"🆕 **New Group Link (Old Link Expired):**\n{new_link}\n\n"
            f"👤 Non-admin members removed.\n"
            f"🧹 Chat messages deleted & logs cleared.\n"
            f"🤝 Same group ready for the next deal!"
        )

        # Automatic Welcome Message & Pin
        w_msg = bot.send_message(chat_id, WELCOME_MESSAGE, parse_mode="Markdown")
        try:
            bot.pin_chat_message(chat_id, w_msg.message_id, disable_notification=True)
        except Exception:
            pass

    except Exception as e:
        await event.respond(f"❌ **Error executing .clear:** {e}")


# ==========================
# THREAD RUNNER FOR DUAL CLIENTS
# ==========================

def run_telebot():
    print("🤖 Telebot Polling Started...")
    bot.infinity_polling()

async def main():
    t = threading.Thread(target=run_telebot, daemon=True)
    t.start()

    print("⚡ Telethon Userbot Starting...")
    await userbot.start()
    await userbot.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(main())
