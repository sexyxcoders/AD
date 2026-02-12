#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
ADIMYZE PRO v12 — FINAL STABILIZED VERSION
Fixes: Keypad conflicts, State machine leaks, Session reliability.
"""

import asyncio
import random
import logging
import re
import sys
import os
import fcntl
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
)
from telegram.constants import ParseMode
from telegram.error import BadRequest

from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.functions.account import UpdateProfileRequest, UpdateUsernameRequest
from telethon.tl.types import InputPeerChannel
from telethon.errors import (
    SessionPasswordNeededError,
    PhoneCodeInvalidError,
    PhoneCodeEmptyError,
    FloodWaitError,
    UsernameOccupiedError,
    ChatWriteForbiddenError,
    PeerFloodError,
    PasswordHashInvalidError,
    PhoneNumberInvalidError,
    AuthKeyUnregisteredError,
)

from motor.motor_asyncio import AsyncIOMotorClient

# --- CONFIGURATION ---
BOT_TOKEN = "8463982454:AAFXhclFtn5cCoJLZl3l-SwhPMk3ssv6J8o"
API_ID = 22657083
API_HASH = "d6186691704bd901bdab275ceaab88f3"
MONGO_URI = "mongodb+srv://StarGiftBot_db_user:gld1RLm4eYbCWZlC@cluster0.erob6sp.mongodb.net/?retryWrites=true&w=majority"
DB_NAME = "adimyze"
CHANNEL_LINK = "https://t.me/testttxs"

PROFILE_NAME = "Nexa"
PROFILE_BIO = "🔥 Managed by @nexaxoders | Adimyze Pro v12 🚀"

logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s')
logger = logging.getLogger(__name__)

mongo_client = AsyncIOMotorClient(MONGO_URI)
db = mongo_client[DB_NAME]

user_states: Dict[int, Dict[str, Any]] = {}
ad_tasks: Dict[int, asyncio.Task] = {}
PID_FILE = Path(__file__).with_suffix(".pid")

# --- UI BUILDERS ---
def kb_welcome():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🚀 Dashboard", callback_data="nav_dashboard")],
        [InlineKeyboardButton("📞 Support", callback_data="nav_support"), InlineKeyboardButton("ℹ️ About", callback_data="nav_about")],
    ])

def kb_dashboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Add Account", callback_data="nav_add_account"), InlineKeyboardButton("👥 My Accounts", callback_data="nav_my_accounts")],
        [InlineKeyboardButton("📥 Load Chats", callback_data="nav_load_chats"), InlineKeyboardButton("📢 Set Ad", callback_data="nav_set_ad")],
        [InlineKeyboardButton("📊 Status", callback_data="nav_status"), InlineKeyboardButton("⏱️ Delays", callback_data="nav_delays")],
        [InlineKeyboardButton("▶️ Start Ads", callback_data="nav_start_ads"), InlineKeyboardButton("⛔ Stop Ads", callback_data="nav_stop_ads")],
        [InlineKeyboardButton("🏠 Home", callback_data="nav_home")],
    ])

def kb_otp(buffer: str = "", is_2fa: bool = False, phone: str = ""):
    display = ("•" * len(buffer)).ljust(10, " ") if is_2fa else buffer.ljust(5, "█")
    
    keys = [
        [InlineKeyboardButton(f"Current: {display}", callback_data="otp_void")],
        [InlineKeyboardButton("1", callback_data="otp_1"), InlineKeyboardButton("2", callback_data="otp_2"), InlineKeyboardButton("3", callback_data="otp_3")],
        [InlineKeyboardButton("4", callback_data="otp_4"), InlineKeyboardButton("5", callback_data="otp_5"), InlineKeyboardButton("6", callback_data="otp_6")],
        [InlineKeyboardButton("7", callback_data="otp_7"), InlineKeyboardButton("8", callback_data="otp_8"), InlineKeyboardButton("9", callback_data="otp_9")],
        [InlineKeyboardButton("⌫", callback_data="otp_back"), InlineKeyboardButton("0", callback_data="otp_0"), InlineKeyboardButton("✅", callback_data="otp_done")],
        [InlineKeyboardButton("❌ Cancel Login", callback_data="otp_cancel")]
    ]
    return InlineKeyboardMarkup(keys)

# --- OTP CORE LOGIC ---
async def process_otp_input(uid: int, data: str, query):
    state = user_states.get(uid)
    if not state or state.get("step") not in ["otp_input", "2fa_input"]:
        return

    if data == "otp_cancel":
        cleanup_state(uid)
        await query.edit_message_text("❌ Login aborted.", reply_markup=kb_dashboard())
        return

    if data == "otp_done":
        await verify_credentials(uid, query)
        return

    if data == "otp_back":
        state["buffer"] = state["buffer"][:-1]
    elif data.startswith("otp_") and len(data) > 4:
        char = data.split("_")[1]
        limit = 32 if state["step"] == "2fa_input" else 5
        if len(state["buffer"]) < limit:
            state["buffer"] += char

    # Update the keyboard UI
    is_2fa = state["step"] == "2fa_input"
    await query.edit_message_text(
        f"<b>{'🔐 Enter 2FA Password' if is_2fa else f'🔑 Enter OTP - {state.get('phone')}'}</b>\n"
        f"Input: <code>{state['buffer']}</code>",
        reply_markup=kb_otp(state["buffer"], is_2fa, state.get("phone", "")),
        parse_mode=ParseMode.HTML
    )

async def verify_credentials(uid: int, query):
    state = user_states[uid]
    client = state["client"]
    try:
        if state["step"] == "otp_input":
            await client.sign_in(phone=state["phone"], code=state["buffer"], phone_code_hash=state["hash"])
        else:
            await client.sign_in(password=state["buffer"])
        
        await finalize_account(uid, query, client)
    except SessionPasswordNeededError:
        state["step"] = "2fa_input"
        state["buffer"] = ""
        await query.edit_message_text("🔐 2FA Password Required:", reply_markup=kb_otp("", True, state["phone"]))
    except Exception as e:
        await query.answer(f"⚠️ Error: {str(e)[:50]}", show_alert=True)

# --- ROUTER ---
async def cb_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    uid = query.from_user.id
    data = query.data
    await query.answer()

    # Priority: OTP Keypad
    if data.startswith("otp_"):
        await process_otp_input(uid, data, query)
        return

    # Dashboard Logic
    if data.startswith("nav_"):
        action = data.replace("nav_", "")
        
        if action == "home":
            await query.edit_message_text("🏠 Main Menu", reply_markup=kb_welcome())
        elif action == "dashboard":
            await show_dashboard(query, uid)
        elif action == "add_account":
            user_states[uid] = {"step": "wait_phone"}
            await query.edit_message_text("📱 Please send the phone number (+123...):", reply_markup=kb_dashboard())
        elif action == "my_accounts":
            await show_accounts_list(query, uid)
        elif action == "load_chats":
            await run_chat_loader(query, uid)
        elif action == "start_ads":
            await toggle_campaign(query, uid, True)
        elif action == "stop_ads":
            await toggle_campaign(query, uid, False)
        elif action == "status":
            await show_status_page(query, uid)
        elif action == "set_ad":
            user_states[uid] = {"step": "wait_ad"}
            await query.edit_message_text("📢 Forward a message from your Saved Messages now.")

# --- CAMPAIGN ENGINE ---
async def toggle_campaign(query, uid: int, start: bool):
    await db.users.update_one({"user_id": uid}, {"$set": {"running": start}}, upsert=True)
    if start:
        if uid in ad_tasks: ad_tasks[uid].cancel()
        ad_tasks[uid] = asyncio.create_task(campaign_worker(uid))
        msg = "🟢 Campaign Started!"
    else:
        if uid in ad_tasks: ad_tasks[uid].cancel()
        msg = "🔴 Campaign Stopped!"
    
    await query.answer(msg, show_alert=True)
    await show_dashboard(query, uid)

async def campaign_worker(uid: int):
    while True:
        user = await db.users.find_one({"user_id": uid})
        if not user or not user.get("running"): break
        
        chats = user.get("chats", [])
        ad = user.get("ad_message")
        if not chats or not ad: break

        for chat in chats:
            # Check if still running
            check = await db.users.find_one({"user_id": uid})
            if not check.get("running"): break

            try:
                acc = await db.accounts.find_one({"_id": chat["account_id"]})
                if not acc: continue
                
                client = TelegramClient(StringSession(acc["session"]), API_ID, API_HASH)
                await client.connect()
                await client.forward_messages(chat["chat_id"], ad["msg_id"], from_peer="me")
                await client.disconnect()
                
                await db.users.update_one({"user_id": uid}, {"$inc": {"total_sent": 1}}, upsert=True)
                await asyncio.sleep(random.randint(60, 150)) # Anti-flood
            except Exception as e:
                logger.error(f"Worker Error: {e}")
        
        await asyncio.sleep(1800) # Break between cycles

# --- HELPERS ---
async def show_dashboard(query, uid: int):
    accs = await db.accounts.count_documents({"user_id": uid})
    user_doc = await db.users.find_one({"user_id": uid}) or {}
    status = "🟢 ACTIVE" if user_doc.get("running") else "🔴 INACTIVE"
    
    text = f"🚀 <b>DASHBOARD</b>\n\nAccounts: {accs}\nStatus: {status}\nSent Total: {user_doc.get('total_sent', 0)}"
    await query.edit_message_text(text, reply_markup=kb_dashboard(), parse_mode=ParseMode.HTML)

async def finalize_account(uid: int, query, client: TelegramClient):
    session = client.session.save()
    phone = user_states[uid]["phone"]
    
    await db.accounts.update_one(
        {"phone": phone},
        {"$set": {"user_id": uid, "session": session, "last_used": datetime.now()}},
        upsert=True
    )
    cleanup_state(uid)
    await query.edit_message_text("✅ Account successfully linked!", reply_markup=kb_dashboard())
    await client.disconnect()

def cleanup_state(uid: int):
    state = user_states.pop(uid, None)
    if state and "client" in state:
        asyncio.create_task(state["client"].disconnect())

# --- BOOT ---
async def main():
    app = Application.builder().token(BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", lambda u, c: u.message.reply_text("Welcome!", reply_markup=kb_welcome())))
    app.add_handler(CallbackQueryHandler(cb_router))
    
    async def global_msg_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
        uid = update.effective_user.id
        state = user_states.get(uid, {})
        
        if state.get("step") == "wait_phone":
            phone = update.message.text
            client = TelegramClient(StringSession(), API_ID, API_HASH)
            await client.connect()
            sent = await client.send_code_request(phone)
            user_states[uid] = {"step": "otp_input", "phone": phone, "hash": sent.phone_code_hash, "buffer": "", "client": client}
            await update.message.reply_text(f"OTP sent to {phone}", reply_markup=kb_otp("", False, phone))
        
        elif state.get("step") == "wait_ad" and update.message.forward_origin:
            ad_data = {"msg_id": update.message.forward_origin.message_id}
            await db.users.update_one({"user_id": uid}, {"$set": {"ad_message": ad_data}}, upsert=True)
            user_states.pop(uid)
            await update.message.reply_text("✅ Ad Message Saved!", reply_markup=kb_dashboard())

    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, global_msg_handler))
    
    print("Bot Start sequence complete.")
    await app.run_polling()

if __name__ == "__main__":
    asyncio.run(main())