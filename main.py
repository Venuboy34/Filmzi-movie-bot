import os
import re
import asyncio
import threading
import json
import logging
import requests
import tempfile
import aiohttp
import aiofiles
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from pyrogram import Client, filters
from pyrogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    Message,
    CallbackQuery,
)
from pyrogram.errors import UserNotParticipant, ChatAdminRequired
from typing import Dict, List, Union

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Environment variables for Koyeb deployment
API_ID = os.getenv('API_ID', 26091026)
API_HASH = os.getenv('API_HASH', "f608d185d836e0405775833c6888922f")
BOT_TOKEN = os.getenv('BOT_TOKEN', "7613692613:AAGkBg5_PDJkNSVf_a0uU0nYNS09GceDltw")
BASE_URL = os.getenv('BASE_URL', "https://v0-flask-movie-database-nine.vercel.app")
PORT = int(os.getenv('PORT', 8000))
ADMIN_ID = int(os.getenv('ADMIN_ID', 0))  # Your Telegram user ID

# Movie update group (users must join this)
MOVIE_GROUP_ID = "@filmzi2"  # Your group username
MOVIE_GROUP_LINK = "https://t.me/filmzi2"

# API configuration
MEDIA_ENDPOINT = "/media"
STATS_FILE = "user_stats.json"

# File download configuration
CHUNK_SIZE = 8192  # 8KB chunks for download
MAX_FILE_SIZE = 2 * 1024 * 1024 * 1024  # 2GB limit
TEMP_DIR = "/tmp/filmzi_downloads"  # Temporary directory for downloads

# Create temp directory if it doesn't exist
os.makedirs(TEMP_DIR, exist_ok=True)

# Initialize the bot
app = Client("Filmzi", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# User data cache (for pagination and state management)
user_data = {}
user_stats = {}

# Load statistics
def load_stats():
    global user_stats
    try:
        if os.path.exists(STATS_FILE):
            with open(STATS_FILE, 'r') as f:
                user_stats = json.load(f)
    except Exception as e:
        logger.error(f"Error sending photo: {e}")
        # Fallback to text message if photo fails
        await message.reply_text(welcome_message, reply_markup=keyboard)

# Add command handler for /plan
@app.on_message(filters.command("plan"))
async def plan_command(client: Client, message: Message):
    # Check membership first
    is_member = await check_user_membership(client, message.from_user.id)
    if not is_member:
        await message.reply_text(
            "❌ Please join our movie updates group first to use the bot!",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🎬 JOIN GROUP", url=MOVIE_GROUP_LINK)],
                [InlineKeyboardButton("✅ CHECK MEMBERSHIP", callback_data="check_membership")]
            ])
        )
        return

    track_user(message.from_user.id, "search")
    plan_message = (
        "**💎 PREMIUM PLANS 💎**\n\n"
        "**🔥 Premium Features:**\n"
        "• Unlimited downloads\n"
        "• Priority file sending\n"
        "• No ads or waiting\n"
        "• Early access to new movies\n"
        "• Multiple download sources\n"
        "• HD & 4K quality options\n"
        "• Faster upload speeds\n\n"
        "**💰 Pricing:**\n"
        "• 1 Month - $5\n"
        "• 3 Months - $12\n"
        "• 6 Months - $20\n"
        "• 1 Year - $35\n\n"
        "**📁 File Sending:** Up to 2GB per file\n"
        "**Contact for Premium:** [Zero Creations](https://t.me/zerocreations)"
    )
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("💎 GET PREMIUM", url="https://t.me/zerocreations")],
        [InlineKeyboardButton("🔙 Back to Home", callback_data="back_to_start")]
    ])
    
    await message.reply_text(plan_message, reply_markup=keyboard)

# Add command handler for /stats (admin only)
@app.on_message(filters.command("stats") & filters.user(ADMIN_ID) if ADMIN_ID else filters.command("stats"))
async def stats_command(client: Client, message: Message):
    total_users = len(user_stats)
    today = datetime.now().date().isoformat()

    # Calculate today's activity
    today_searches = 0
    today_downloads = 0
    for stats in user_stats.values():
        try:
            last_seen = datetime.fromisoformat(stats["last_seen"]).date()
            if last_seen.isoformat() == today:
                today_searches += stats.get("search_count", 0)
                today_downloads += stats.get("download_count", 0)
        except:
            continue
    
    # Get disk usage
    temp_files = len([f for f in os.listdir(TEMP_DIR) if os.path.isfile(os.path.join(TEMP_DIR, f))])
    
    stats_message = (
        f"**📊 FILMZI BOT STATISTICS**\n\n"
        f"**👥 Total Users:** {total_users:,}\n"
        f"**🔍 Today's Searches:** {today_searches:,}\n"
        f"**📥 Today's Downloads:** {today_downloads:,}\n\n"
        f"**📁 Temp Files:** {temp_files}\n"
        f"**🚀 Server Status:** Online\n"
        f"**💾 Database:** Connected\n"
        f"**📤 File Sending:** Enabled (2GB Max)"
    )
    
    await message.reply_text(stats_message)

# Auto-filter handler (text-based search) - Enhanced with membership check
@app.on_message(filters.text & filters.private & ~filters.command(["start", "plan", "stats"]))
async def auto_filter(client: Client, message: Message):
    user_id = message.from_user.id

    # Check membership first
    is_member = await check_user_membership(client, user_id)
    if not is_member:
        await message.reply_text(
            "**❌ Please join our movie updates group first to search movies!**",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🎬 JOIN GROUP", url=MOVIE_GROUP_LINK)],
                [InlineKeyboardButton("✅ CHECK MEMBERSHIP", callback_data="check_membership")]
            ])
        )
        return
    
    track_user(user_id, "search")
    query = message.text.strip()
    if len(query) < 2:
        await message.reply_text("**Please enter at least 2 characters to search.**")
        return
    
    # Add auto reaction to user's message
    try:
        await message.react("🔍")
    except Exception as e:
        logger.error(f"Error adding reaction: {e}")
    
    # Show searching status that will disappear
    search_msg = await message.reply_text(f"🔍 Searching for '{query}'...")
    
    # Get all media and filter locally
    all_media = await get_all_media()
    if not all_media or not isinstance(all_media, list):
        await search_msg.edit_text(f"**❌ Database connection failed. Please try again later.**")
        return
    
    results = filter_media_by_query(all_media, query)
    if not results:
        await search_msg.edit_text(
            f"**❌ No results found for '{query}'**\n\n"
            "**💡 Try searching with:**\n"
            "• Different spelling\n"
            "• Shorter keywords\n"
            "• Movie/show release year\n\n"
            "**Example:** Spider Man, Avengers, Breaking Bad"
        )
        return
    
    # Store results in user data for pagination
    user_data[user_id] = {
        "results": results,
        "current_page": 0,
        "query": query
    }
    
    # Delete the searching message and display first result
    try:
        await search_msg.delete()
    except:
        pass
    
    # Display first result
    await display_result_page(client, user_id, None, 0, message.chat.id)

# Callback query handlers
@app.on_callback_query()
async def handle_callback_query(client: Client, callback_query: CallbackQuery):
    data = callback_query.data
    user_id = callback_query.from_user.id

    # Check membership for most actions (except check_membership itself)
    if data != "check_membership":
        is_member = await check_user_membership(client, user_id)
        if not is_member:
            await callback_query.answer(
                "❌ Please join our movie updates group first!",
                show_alert=True
            )
            # Update the message to show join button
            await callback_query.edit_message_text(
                "**❌ You need to join our movie updates group to continue!**",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🎬 JOIN GROUP", url=MOVIE_GROUP_LINK)],
                    [InlineKeyboardButton("✅ CHECK MEMBERSHIP", callback_data="check_membership")]
                ])
            )
            return
    
    track_user(user_id, "search")
    
    if data == "check_membership":
        is_member = await check_user_membership(client, user_id)
        if is_member:
            await callback_query.answer("✅ Great! You're now a member. Enjoy the bot!", show_alert=True)
            # Redirect to main menu
            user_name = callback_query.from_user.first_name or "User"
            greeting = get_greeting()
            
            welcome_message = (
                f"ʜᴇʏ {user_name}, {greeting}\n\n"
                "🎭 **Welcome to Filmzi - Premium Auto Filter Bot**\n\n"
                "**✨ Features:**\n"
                "• 🎬 Movies & TV Shows\n"
                "• 📁 Direct File Sending (Up to 2GB)\n"
                "• 🎥 Multiple Quality Options\n"
                "• ⚡ Fast Download & Upload\n"
                "• 🔄 Auto File Cleanup\n\n"
                "**💡 Just type any movie or TV show name to search!**\n"
                "**🎭 All files sent directly to your chat!**"
            )
            
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("🛡️ ADD ME TO YOUR GROUP 🛡️", url=f"https://t.me/FilmziBot?startgroup=true")],
                [
                    InlineKeyboardButton("TOP SEARCHING ⭐", callback_data="top_searches"),
                    InlineKeyboardButton("HELP 📢", callback_data="help")
                ],
                [InlineKeyboardButton("📊 BOT STATS", callback_data="bot_stats")]
            ])
            
            await callback_query.edit_message_text(welcome_message, reply_markup=keyboard)
        else:
            await callback_query.answer(
                "❌ You haven't joined the group yet. Please join first!",
                show_alert=True
            )
        return
    
    if data.startswith("result_page_"):
        page = int(data.split("_")[2])
        await display_result_page(client, user_id, callback_query.message.id, page)
        await callback_query.answer()
    
    elif data.startswith("select_"):
        media_id = int(data.split("_")[1])
        media = await get_media_by_id(media_id)
        if not media:
            await callback_query.answer("❌ Media not found", show_alert=True)
            return
        
        keyboard = create_quality_buttons(media)
        await callback_query.edit_message_reply_markup(reply_markup=keyboard)
        await callback_query.answer()
    
    elif data.startswith("quality_"):
        quality = data.split("_")[1]
        media_id = int(data.split("_")[2])
        media = await get_media_by_id(media_id)
        track_user(user_id, "download")
        
        if not media or "video_links" not in media:
            await callback_query.answer("❌ Download link not available", show_alert=True)
            return
        
        video_url = media["video_links"].get(quality)
        if not video_url:
            await callback_query.answer("❌ Download link not available", show_alert=True)
            return
        
        # Send status message
        await callback_query.answer("🚀 Starting file preparation...", show_alert=True)
        
        # Update the message to show preparation status
        await callback_query.edit_message_text(
            f"🚀 **Preparing {media.get('title', 'N/A')} - {quality.upper()}**\n\n"
            "**Status:** Initializing download...\n"
            "**⏳ This may take a few minutes for large files**\n\n"
            "**💡 The file will be sent directly to this chat once ready!**",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📱 DIRECT LINK (BACKUP)", url=video_url)],
                [InlineKeyboardButton("🔙 Back", callback_data=f"back_to_quality_{media_id}")]
            ])
        )
        
        # Send video file directly using enhanced function
        sent_msg = await send_video_file(
            client, 
            callback_query.from_user.id, 
            video_url, 
            media, 
            quality
        )
        
        if sent_msg:
            # Update the callback message to show success
            await callback_query.edit_message_text(
                f"✅ **{media.get('title', 'N/A')} - {quality.upper()}** sent successfully!\n\n"
                "**📁 File has been delivered to your chat**\n"
                "**⚠️ File will be auto-deleted in 15 minutes**\n"
                "**💾 Save it to your device quickly!**\n\n"
                "**🎭 Thank you for using Filmzi Bot!**",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔍 Search More", callback_data="back_to_search")],
                    [InlineKeyboardButton("📢 Updates", url=MOVIE_GROUP_LINK)]
                ])
            )
        else:
            # Update message to show fallback option
            await callback_query.edit_message_text(
                f"⚠️ **Direct file sending failed for {media.get('title', 'N/A')}**\n\n"
                f"**📁 File Size:** May be too large for direct sending\n"
                f"**🎥 Quality:** {quality.upper()}\n\n"
                "**📱 Use the direct download link below:**\n"
                "**💡 This link will work in any browser or download manager**",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🚀 DOWNLOAD NOW", url=video_url)],
                    [InlineKeyboardButton("⭐ RATE", callback_data=f"rate_{media_id}_{quality}"),
                     InlineKeyboardButton("🔙 Back", callback_data=f"back_to_quality_{media_id}")]
                ])
            )
    
    elif data.startswith("season_"):
        season_num = data.split("_")[1]
        media_id = int(data.split("_")[2])
        media = await get_media_by_id(media_id)
        
        if not media or "seasons" not in media:
            await callback_query.answer("❌ Season data not available", show_alert=True)
            return
        
        season_key = f"season_{season_num}"
        if season_key not in media["seasons"]:
            await callback_query.answer("❌ Season not available", show_alert=True)
            return
        
        season_data = media["seasons"][season_key]
        keyboard = create_episode_buttons(season_data, media_id, season_num)
        
        await callback_query.edit_message_text(
            f"**📺 {media['title']} - Season {season_num}**\n\n"
            f"**Episodes Available:** {len(season_data.get('episodes', []))}\n"
            "**Select an episode to download:**",
            reply_markup=keyboard
        )
        await callback_query.answer()
    
    elif data.startswith("episode_"):
        parts = data.split("_")
        season_num = parts[1]
        episode_num = parts[2]
        media_id = int(parts[3])
        media = await get_media_by_id(media_id)
        track_user(user_id, "download")
        
        if not media or "seasons" not in media:
            await callback_query.answer("❌ Episode not available", show_alert=True)
            return
        
        season_key = f"season_{season_num}"
        if season_key not in media["seasons"]:
            await callback_query.answer("❌ Episode not available", show_alert=True)
            return
        
        episode = next(
            (ep for ep in media["seasons"][season_key]["episodes"] 
             if str(ep["episode_number"]) == episode_num),
            None
        )
        
        if not episode:
            await callback_query.answer("❌ Episode not found", show_alert=True)
            return
        
        # Auto select best available quality
        video_url = None
        quality = None
        
        # Check for available qualities (priority: 720p > 480p > 360p)
        if "video_720p" in episode and episode["video_720p"]:
            video_url = episode["video_720p"]
            quality = "720p"
        elif "video_480p" in episode and episode["video_480p"]:
            video_url = episode["video_480p"]
            quality = "480p"
        elif "video_360p" in episode and episode["video_360p"]:
            video_url = episode["video_360p"]
            quality = "360p"
        elif "video_links" in episode and episode["video_links"]:
            # If video_links is available, get the first available quality
            for q in ["720p", "480p", "360p"]:
                if q in episode["video_links"] and episode["video_links"][q]:
                    video_url = episode["video_links"][q]
                    quality = q
                    break
        
        if not video_url:
            await callback_query.answer("❌ Episode link not available", show_alert=True)
            return
        
        # Send status message
        await callback_query.answer("🚀 Preparing episode download...", show_alert=True)
        
        # Update message to show preparation status
        episode_title = episode.get("title", f"Episode {episode_num}")
        await callback_query.edit_message_text(
            f"🚀 **Preparing Episode**\n\n"
            f"**Show:** {media.get('title', 'N/A')}\n"
            f"**Season:** {season_num} | **Episode:** {episode_num}\n"
            f"**Title:** {episode_title}\n"
            f"**Quality:** {quality.upper()}\n\n"
            "**Status:** Initializing download...\n"
            "**⏳ Please wait while we prepare your file**",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📱 DIRECT LINK (BACKUP)", url=video_url)],
                [InlineKeyboardButton("🔙 Back to Episodes", callback_data=f"season_{season_num}_{media_id}")]
            ])
        )
        
        # Send video file directly for episodes using enhanced function
        episode_info = {
            "season": season_num,
            "episode": episode_num,
            "title": episode_title
        }
        
        sent_msg = await send_video_file(
            client, 
            callback_query.from_user.id, 
            video_url, 
            media, 
            quality,
            episode_info
        )
        
        if sent_msg:
            # Update the callback message to show success
            await callback_query.edit_message_text(
                f"✅ **Episode Sent Successfully!**\n\n"
                f"**📺 {media.get('title', 'N/A')} S{season_num}E{episode_num}**\n"
                f"**🎬 {episode_title}**\n"
                f"**🎥 Quality:** {quality.upper()}\n\n"
                "**📁 File delivered to your chat**\n"
                "**⚠️ Auto-delete in 15 minutes**\n"
                "**💾 Save quickly!**",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔍 More Episodes", callback_data=f"season_{season_num}_{media_id}")],
                    [InlineKeyboardButton("📢 Updates", url=MOVIE_GROUP_LINK)]
                ])
            )
        else:
            # Update message to show fallback option
            await callback_query.edit_message_text(
                f"⚠️ **Direct sending failed for this episode**\n\n"
                f"**📺 {media.get('title', 'N/A')} S{season_num}E{episode_num}**\n"
                f"**🎬 {episode_title}**\n"
                f"**🎥 Quality:** {quality.upper()}\n\n"
                "**📱 Use the direct download link:**",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🚀 DOWNLOAD NOW", url=video_url)],
                    [InlineKeyboardButton("⭐ RATE", callback_data=f"rate_{media_id}_{season_num}_{episode_num}"),
                     InlineKeyboardButton("🔙 Back", callback_data=f"season_{season_num}_{media_id}")]
                ])
            )
    
    elif data.startswith("back_to_"):
        if data == "back_to_search":
            if user_id in user_data:
                current_page = user_data[user_id]["current_page"]
                await display_result_page(client, user_id, callback_query.message.id, current_page)
        elif data.startswith("back_to_quality_"):
            media_id = int(data.split("_")[3])
            media = await get_media_by_id(media_id)
            if media:
                keyboard = create_quality_buttons(media)
                await callback_query.edit_message_reply_markup(reply_markup=keyboard)
        elif data.startswith("back_to_seasons_"):
            media_id = int(data.split("_")[3])
            media = await get_media_by_id(media_id)
            if media:
                keyboard = create_quality_buttons(media)
                await callback_query.edit_message_reply_markup(reply_markup=keyboard)
        
        await callback_query.answer()
    
    elif data in ["top_searches", "help", "bot_stats"]:
        if data == "top_searches":
            text = (
                "**🔝 TOP SEARCHES 🔝**\n\n"
                "**🎬 Popular Movies:**\n"
                "1. Spider-Man: No Way Home\n"
                "2. The Matrix\n"
                "3. Inception\n"
                "4. Interstellar\n"
                "5. Avengers: Endgame\n\n"
                "**📺 Popular TV Shows:**\n"
                "1. Breaking Bad\n"
                "2. Stranger Things\n"
                "3. Game of Thrones\n"
                "4. The Office\n"
                "5. Friends\n\n"
                "**💡 Search Tips:**\n"
                "• Use exact movie names\n"
                "• Try different spellings\n"
                "• Include release year if needed\n"
                "• Files sent directly to chat!"
            )
        elif data == "help":
            text = (
                "**📢 FILMZI BOT - HOW TO USE**\n\n"
                "**🔍 Search Movies/TV Shows:**\n"
                "• Type the name of any movie or TV show\n"
                "• Bot searches database automatically\n"
                "• Use 2+ characters for better results\n\n"
                "**🎬 For Movies:**\n"
                "• Browse through search results\n"
                "• Select quality (480p, 720p, 1080p)\n"
                "• **File sent directly to your chat!**\n\n"
                "**📺 For TV Shows:**\n"
                "• Choose season and episode\n"
                "• Auto quality selection\n"
                "• **Episodes sent directly!**\n\n"
                "**⚡ Direct File Sending:**\n"
                "• Files up to 2GB supported\n"
                "• Real-time download progress\n"
                "• Auto-upload to Telegram\n"
                "• Files auto-delete in 15 minutes\n\n"
                "**📱 Important Notes:**\n"
                "• Must join @filmzi2 group first\n"
                "• Save files quickly (auto-delete)\n"
                "• Works in groups too!\n"
                "• Backup download links provided\n\n"
                "**Need Help?** Contact: [Zero Creations](https://t.me/zerocreations)"
            )
        else:  # bot_stats
            total_users = len(user_stats)
            today = datetime.now().date().isoformat()
            
            # Calculate today's activity
            today_searches = 0
            today_downloads = 0
            active_today = 0
            
            for stats in user_stats.values():
                try:
                    last_seen = datetime.fromisoformat(stats["last_seen"]).date()
                    if last_seen.isoformat() == today:
                        active_today += 1
                        today_searches += stats.get("search_count", 0)
                        today_downloads += stats.get("download_count", 0)
                except:
                    continue
            
            # Get temp files count
            temp_files = len([f for f in os.listdir(TEMP_DIR) if os.path.isfile(os.path.join(TEMP_DIR, f))])
            
            text = (
                f"**📊 FILMZI BOT STATISTICS**\n\n"
                f"**👥 Total Users:** {total_users:,}\n"
                f"**🔥 Active Today:** {active_today:,}\n"
                f"**🔍 Today's Searches:** {today_searches:,}\n"
                f"**📥 Today's Downloads:** {today_downloads:,}\n\n"
                f"**📁 Processing Files:** {temp_files}\n"
                f"**📤 Max File Size:** 2GB\n"
                f"**⚡ Direct Sending:** Enabled\n"
                f"**🔄 Auto Cleanup:** Active\n\n"
                f"**🎭 Movie Updates:** [Join @filmzi2](https://t.me/filmzi2)\n"
                f"**🌐 Status:** Online & Fast\n"
                f"**💾 Database:** Live & Updated\n\n"
                "**Created By:** [Zero Creations](https://t.me/zerocreations)"
            )
        
        await callback_query.answer()
        await callback_query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Back to Home", callback_data="back_to_start")]
            ])
        )
    
    elif data == "back_to_start":
        user_name = callback_query.from_user.first_name or "User"
        greeting = get_greeting()
        
        welcome_message = (
            f"ʜᴇʏ {user_name}, {greeting}\n\n"
            "🎭 **Welcome to Filmzi - Premium Auto Filter Bot**\n\n"
            "**✨ Features:**\n"
            "• 🎬 Movies & TV Shows\n"
            "• 📁 Direct File Sending (Up to 2GB)\n"
            "• 🎥 Multiple Quality Options\n"
            "• ⚡ Fast Download & Upload\n"
            "• 🔄 Auto File Cleanup\n\n"
            "**💡 Just type any movie or TV show name to search!**\n"
            "**🎭 All files sent directly to your chat!**"
        )
        
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🛡️ ADD ME TO YOUR GROUP 🛡️", url=f"https://t.me/FilmziBot?startgroup=true")],
            [
                InlineKeyboardButton("TOP SEARCHING ⭐", callback_data="top_searches"),
                InlineKeyboardButton("HELP 📢", callback_data="help")
            ],
            [InlineKeyboardButton("📊 BOT STATS", callback_data="bot_stats")]
        ])
        
        await callback_query.edit_message_text(welcome_message, reply_markup=keyboard)
        await callback_query.answer()
    
    elif data.startswith("rate_"):
        await callback_query.answer("⭐ Thank you for your feedback!", show_alert=True)
    
    elif data == "noop":
        await callback_query.answer()

# Group message handler for auto-filter in groups
@app.on_message(filters.text & filters.group & ~filters.command(["start", "plan", "stats"]))
async def group_auto_filter(client: Client, message: Message):
    # Only respond if bot is mentioned or message is a reply to bot
    bot_mentioned = False

    # Check if bot is mentioned
    if message.entities:
        for entity in message.entities:
            if entity.type == "mention":
                username = message.text[entity.offset:entity.offset + entity.length]
                if username.lower() == "@filmzibot":
                    bot_mentioned = True
                    break
    
    # Check if it's a reply to bot
    if message.reply_to_message and message.reply_to_message.from_user.is_self:
        bot_mentioned = True
    
    if not bot_mentioned:
        return
    
    user_id = message.from_user.id
    track_user(user_id, "search")
    
    # Extract query (remove bot mention if present)
    query = message.text.strip()
    if query.startswith("@filmzibot"):
        query = query[11:].strip()
    
    if len(query) < 2:
        await message.reply_text(
            "**Please enter at least 2 characters to search.**\n"
            "**Example:** @FilmziBot spider man"
        )
        return
    
    # Get all media and filter locally
    all_media = await get_all_media()
    if not all_media or not isinstance(all_media, list):
        await message.reply_text("**❌ Database connection failed. Please try again later.**")
        return
    
    results = filter_media_by_query(all_media, query)
    if not results:
        await message.reply_text(
            f"**❌ No results found for '{query}'**\n\n"
            "**💡 Try different keywords or spelling**"
        )
        return
    
    # For groups, show only first 5 results with inline buttons
    limited_results = results[:5]
    
    message_text = f"**🔍 Search Results for '{query}':**\n\n"
    buttons = []
    
    for i, media in enumerate(limited_results):
        media_type = "🎬" if media["type"] == "movie" else "📺"
        message_text += f"**{i+1}.** {media_type} {media.get('title', 'N/A')} ({media.get('release_date', 'N/A')[:4]})\n"
        buttons.append([InlineKeyboardButton(
            f"{media_type} {media.get('title', 'N/A')[:30]}...",
            url=f"https://t.me/FilmziBot?start=movie_{media['id']}"
        )])
    
    if len(results) > 5:
        message_text += f"\n**... and {len(results) - 5} more results**"
    
    message_text += f"\n\n**📱 Click any movie/show to get files directly in private chat**\n**📁 Files up to 2GB sent instantly!**"
    
    # Add group join button
    buttons.append([InlineKeyboardButton("🎬 JOIN MOVIE UPDATES", url=MOVIE_GROUP_LINK)])
    
    await message.reply_text(
        message_text,
        reply_markup=InlineKeyboardMarkup(buttons)
    )

# Handle deep links from groups
@app.on_message(filters.command("start") & filters.regex(r"movie_\d+"))
async def handle_deep_link(client: Client, message: Message):
    user_id = message.from_user.id

    # Check membership first
    is_member = await check_user_membership(client, user_id)
    if not is_member:
        await message.reply_text(
            "**❌ Please join our movie updates group first to access movies!**",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🎬 JOIN GROUP", url=MOVIE_GROUP_LINK)],
                [InlineKeyboardButton("✅ CHECK MEMBERSHIP", callback_data="check_membership")]
            ])
        )
        return
    
    # Extract media ID from command
    command_args = message.text.split("_")
    if len(command_args) != 2:
        await start_command(client, message)
        return
    
    try:
        media_id = int(command_args[1])
    except ValueError:
        await start_command(client, message)
        return
    
    # Get media details
    media = await get_media_by_id(media_id)
    if not media:
        await message.reply_text("**❌ Movie/Show not found!**")
        return
    
    # Display media details
    message_text = create_media_message(media)
    message_text += "\n\n**📁 All files will be sent directly to this chat!**"
    
    # Create buttons
    buttons = []
    if media["type"] == "movie":
        buttons.append([InlineKeyboardButton("🎬 SELECT QUALITY", callback_data=f"select_{media['id']}")])
    else:
        buttons.append([InlineKeyboardButton("📺 SELECT SEASON", callback_data=f"select_{media['id']}")])
    
    # Add IMDb button if available
    if media.get("imdb_id"):
        buttons.append([InlineKeyboardButton("🔍 View on IMDb", url=f"https://www.imdb.com/title/{media['imdb_id']}")])
    
    # Try to send with poster
    try:
        poster_url = media.get("poster_url")
        if poster_url:
            await message.reply_photo(
                photo=poster_url,
                caption=message_text,
                reply_markup=InlineKeyboardMarkup(buttons)
            )
            return
    except Exception as e:
        logger.error(f"Error sending photo: {e}")
    
    # Fallback to text
    await message.reply_text(message_text, reply_markup=InlineKeyboardMarkup(buttons))

# Helper function to get memory usage
def get_memory_usage():
    try:
        import psutil
        process = psutil.Process(os.getpid())
        return round(process.memory_info().rss / (1024 * 1024), 2)
    except ImportError:
        return "N/A"

# Additional cleanup for old user data
async def cleanup_user_data():
    """Clean up old user data to prevent memory issues"""
    while True:
        try:
            # Clean user data older than 1 hour
            current_time = datetime.now().timestamp()
            users_to_remove = []
            
            for user_id, data in user_data.items():
                # If user data is older than 1 hour, mark for removal
                if 'last_activity' in data:
                    if current_time - data['last_activity'] > 3600:
                        users_to_remove.append(user_id)
                else:
                    # If no last_activity, add it
                    user_data[user_id]['last_activity'] = current_time
            
            # Remove old user data
            for user_id in users_to_remove:
                del user_data[user_id]
                logger.info(f"Cleaned up old user data for user {user_id}")
                
        except Exception as e:
            logger.error(f"Error during user data cleanup: {e}")
        
        await asyncio.sleep(1800)  # Run every 30 minutes

# Enhanced error handler
async def handle_download_error(client: Client, chat_id: int, error_msg: str, media: Dict, quality: str, video_url: str):
    """Handle download errors gracefully"""
    error_message = (
        f"❌ **Download Failed**\n\n"
        f"**Movie:** {media.get('title', 'N/A')}\n"
        f"**Quality:** {quality.upper()}\n"
        f"**Error:** {error_msg}\n\n"
        "**📱 Alternative Options:**\n"
        "• Use the direct download link below\n"
        "• Try a different quality if available\n"
        "• Contact support if problem persists\n\n"
        "**💡 The direct link works in browsers and download managers**"
    )
    
    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("🚀 DIRECT DOWNLOAD", url=video_url)],
        [InlineKeyboardButton("🔄 Try Again", callback_data=f"quality_{quality}_{media['id']}")],
        [InlineKeyboardButton("📞 Support", url="https://t.me/zerocreations")]
    ])
    
    await client.send_message(
        chat_id=chat_id,
        text=error_message,
        reply_markup=buttons
    )

# Add disk space check
def check_disk_space():
    """Check available disk space"""
    try:
        import shutil
        total, used, free = shutil.disk_usage(TEMP_DIR)
        free_gb = free / (1024**3)
        return free_gb > 1.0  # At least 1GB free space required
    except Exception:
        return True  # Assume space is available if check fails

# Enhanced startup message
async def send_startup_message():
    """Send startup notification to admin"""
    if ADMIN_ID:
        try:
            startup_message = (
                "🚀 **Filmzi Bot Started Successfully!**\n\n"
                f"**⚡ Features Enabled:**\n"
                f"• Direct File Sending (Up to 2GB)\n"
                f"• Real-time Progress Tracking\n"
                f"• Auto File Cleanup\n"
                f"• Multi-quality Support\n\n"
                f"**📊 System Info:**\n"
                f"• Temp Directory: {TEMP_DIR}\n"
                f"• Health Server: Port {PORT}\n"
                f"• Auto-delete: 15 minutes\n\n"
                f"**🔧 Status:** All systems operational!"
            )
            
            await app.send_message(ADMIN_ID, startup_message)
        except Exception as e:
            logger.error(f"Failed to send startup message: {e}")

# Run the bot
if __name__ == "__main__":
    logger.info("Starting Enhanced Filmzi Bot with Direct File Sending...")
    start_time = datetime.now()

    # Load statistics
    load_stats()
    
    # Check disk space
    if not check_disk_space():
        logger.warning("Low disk space detected!")
    
    # Start health check server in a separate thread
    health_thread = threading.Thread(target=start_health_server, daemon=True)
    health_thread.start()
    
    # Create event loop and start cleanup tasks
    async def main():
        # Start cleanup tasks
        asyncio.create_task(cleanup_temp_files())
        asyncio.create_task(cleanup_user_data())
        
        # Send startup message
        await send_startup_message()
        
        logger.info("🎬 Filmzi Bot is now running with enhanced file sending capabilities!")
        logger.info("📁 Direct file sending: UP TO 2GB supported")
        logger.info("⚡ Features: Progress tracking, auto-cleanup, multi-quality")
        
        # Run the bot
        await app.start()
        await asyncio.Event().wait()  # Keep running
    
    # Run with proper async handling
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Bot crashed: {e}")
    finally:
        logger.info("Cleaning up resources...")
        # Clean up temp files on shutdown
        try:
            for filename in os.listdir(TEMP_DIR):
                file_path = os.path.join(TEMP_DIR, filename)
                if os.path.isfile(file_path):
                    os.remove(file_path)
        except Exception as e:
            logger.error(f"Error during cleanup: {e}")
        
        logger.info("🎬 Filmzi Bot stopped gracefully")
        logger.error(f"Error loading stats: {e}")

# Save statistics
def save_stats():
    try:
        with open(STATS_FILE, 'w') as f:
            json.dump(user_stats, f)
    except Exception as e:
        logger.error(f"Error saving stats: {e}")

# Track user activity
def track_user(user_id: int, action: str):
    try:
        user_id = str(user_id)
        if user_id not in user_stats:
            user_stats[user_id] = {
                "first_seen": datetime.now().isoformat(),
                "last_seen": datetime.now().isoformat(),
                "search_count": 0,
                "download_count": 0
            }

        user_stats[user_id]["last_seen"] = datetime.now().isoformat()
        
        if action == "search":
            user_stats[user_id]["search_count"] = user_stats[user_id].get("search_count", 0) + 1
        elif action == "download":
            user_stats[user_id]["download_count"] = user_stats[user_id].get("download_count", 0) + 1
        
        save_stats()
    except Exception as e:
        logger.error(f"Error tracking user: {e}")

# Check if user is member of movie group
async def check_user_membership(client: Client, user_id: int) -> bool:
    try:
        member = await client.get_chat_member(MOVIE_GROUP_ID, user_id)
        return member.status not in ["left", "kicked"]
    except UserNotParticipant:
        return False
    except Exception as e:
        logger.error(f"Error checking membership: {e}")
        return False

# Enhanced URL processing for direct file access
def process_video_url(url: str) -> str:
    """
    Process different URL formats to make them suitable for direct file downloading
    """
    if not url:
        return url
    
    # Handle PixelDrain URLs
    if "pixeldrain.com" in url or "pixeldrain.dev" in url:
        if "/api/file/" in url:
            if "?download" not in url:
                url += "?download"
        elif "/u/" in url:
            file_id = url.split("/u/")[-1].split("?")[0]
            url = f"https://pixeldrain.com/api/file/{file_id}?download"
    
    # Handle Google Drive URLs
    elif "drive.google.com" in url:
        if "/file/d/" in url:
            file_id = url.split("/file/d/")[1].split("/")[0]
            url = f"https://drive.google.com/uc?export=download&id={file_id}"
    
    # Handle Dropbox URLs
    elif "dropbox.com" in url:
        if "dl=0" in url:
            url = url.replace("dl=0", "dl=1")
    
    return url

# Enhanced file downloader with progress tracking
async def download_file_with_progress(url: str, filename: str, chat_id: int, progress_msg) -> str:
    """
    Download file with progress updates
    Returns the local file path if successful, None if failed
    """
    try:
        # Process URL for better compatibility
        url = process_video_url(url)
        
        # Create session with proper headers
        timeout = aiohttp.ClientTimeout(total=3600)  # 1 hour timeout
        connector = aiohttp.TCPConnector(limit=100, limit_per_host=10)
        
        async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                'Accept': '*/*',
                'Accept-Language': 'en-US,en;q=0.5',
                'Accept-Encoding': 'identity',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1',
            }
            
            async with session.get(url, headers=headers) as response:
                if response.status != 200:
                    logger.error(f"HTTP {response.status} when downloading {url}")
                    return None
                
                # Get file size
                file_size = int(response.headers.get('content-length', 0))
                if file_size > MAX_FILE_SIZE:
                    await progress_msg.edit_text(
                        f"❌ File too large ({format_file_size(file_size)}). Maximum supported: {format_file_size(MAX_FILE_SIZE)}"
                    )
                    return None
                
                # Create file path
                file_path = os.path.join(TEMP_DIR, filename)
                downloaded = 0
                last_progress = 0
                
                # Download with progress updates
                async with aiofiles.open(file_path, 'wb') as file:
                    async for chunk in response.content.iter_chunked(CHUNK_SIZE):
                        await file.write(chunk)
                        downloaded += len(chunk)
                        
                        # Update progress every 5%
                        if file_size > 0:
                            progress = int((downloaded / file_size) * 100)
                            if progress - last_progress >= 5:
                                last_progress = progress
                                progress_bar = "█" * (progress // 5) + "░" * (20 - progress // 5)
                                try:
                                    await progress_msg.edit_text(
                                        f"📥 **Downloading {filename}**\n\n"
                                        f"**Progress:** {progress}%\n"
                                        f"`{progress_bar}`\n"
                                        f"**Downloaded:** {format_file_size(downloaded)} / {format_file_size(file_size)}\n"
                                        f"**Status:** Downloading..."
                                    )
                                except Exception:
                                    pass  # Ignore edit errors during download
                
                return file_path
                
    except asyncio.TimeoutError:
        logger.error(f"Timeout downloading {url}")
        return None
    except Exception as e:
        logger.error(f"Error downloading {url}: {e}")
        return None

# Enhanced video sending function with actual file download
async def send_video_file(client: Client, chat_id: int, video_url: str, 
                         media: Dict, quality: str = None, episode_info: Dict = None) -> bool:
    """
    Enhanced function to download and send video files of any size
    Returns True if successful, False otherwise
    """
    try:
        logger.info(f"Starting file send process for chat {chat_id}")
        
        # Create filename
        if episode_info:
            filename = f"{media.get('title', 'Show')}_S{episode_info['season']}E{episode_info['episode']}"
        else:
            filename = media.get('title', 'Movie')
        
        # Clean filename and add extension
        filename = re.sub(r'[^\w\s-]', '', filename.strip())
        filename = re.sub(r'[-\s]+', '_', filename)
        filename += f"_{quality or 'auto'}.mp4"
        
        # Send initial progress message
        progress_msg = await client.send_message(
            chat_id=chat_id,
            text=f"🚀 **Preparing {filename}**\n\n**Status:** Starting download..."
        )
        
        # Download the file
        file_path = await download_file_with_progress(video_url, filename, chat_id, progress_msg)
        
        if not file_path or not os.path.exists(file_path):
            await progress_msg.edit_text(
                f"❌ **Download Failed**\n\n"
                f"**File:** {filename}\n"
                f"**Error:** Unable to download from source\n\n"
                f"**📱 Try the direct download link instead:**"
            )
            return False
        
        # Get file size
        file_size = os.path.getsize(file_path)
        
        # Prepare caption
        if episode_info:
            caption = (
                f"**📺 {media.get('title', 'N/A')} - S{episode_info['season']}E{episode_info['episode']}**\n"
                f"**📝 Episode:** {episode_info.get('title', 'N/A')}\n"
                f"**🎥 Quality:** {quality.upper() if quality else 'Auto'}\n"
            )
        else:
            caption = (
                f"**🎬 {media.get('title', 'N/A')}**\n"
                f"**🎥 Quality:** {quality.upper() if quality else 'N/A'}\n"
            )
        
        caption += (
            f"**📁 Size:** {format_file_size(file_size)}\n"
            f"**📅 Release:** {media.get('release_date', 'N/A')[:4]}\n"
            "**⚠️ This file will be auto-deleted in 15 minutes**\n\n"
            "**🎭 Powered by:** @filmzi2\n"
            "**Created By:** [Zero Creations](https://t.me/zerocreations)"
        )
        
        # Prepare reply markup
        buttons = InlineKeyboardMarkup([
            [InlineKeyboardButton("🚀 DIRECT DOWNLOAD", url=video_url)],
            [InlineKeyboardButton("⭐ RATE", callback_data=f"rate_{media['id']}_{quality or 'auto'}"),
             InlineKeyboardButton("📢 UPDATES", url=MOVIE_GROUP_LINK)]
        ])
        
        # Update progress message
        await progress_msg.edit_text(
            f"📤 **Uploading {filename}**\n\n"
            f"**Size:** {format_file_size(file_size)}\n"
            f"**Status:** Preparing upload..."
        )
        
        # Send the file based on size and type
        sent_msg = None
        
        # Method 1: Try as video if it's smaller than 50MB
        if file_size < 50 * 1024 * 1024:
            try:
                logger.info("Attempting to send as video...")
                sent_msg = await client.send_video(
                    chat_id=chat_id,
                    video=file_path,
                    caption=caption,
                    reply_markup=buttons,
                    supports_streaming=True,
                    duration=0,
                    width=0,
                    height=0,
                    progress=upload_progress,
                    progress_args=(progress_msg, filename)
                )
                logger.info("Successfully sent as video")
            except Exception as e:
                logger.warning(f"Failed to send as video: {e}")
        
        # Method 2: Send as document (works for any size)
        if not sent_msg:
            try:
                logger.info("Attempting to send as document...")
                sent_msg = await client.send_document(
                    chat_id=chat_id,
                    document=file_path,
                    caption=caption,
                    reply_markup=buttons,
                    progress=upload_progress,
                    progress_args=(progress_msg, filename)
                )
                logger.info("Successfully sent as document")
            except Exception as e:
                logger.error(f"Failed to send as document: {e}")
                await progress_msg.edit_text(
                    f"❌ **Upload Failed**\n\n"
                    f"**File:** {filename}\n"
                    f"**Error:** {str(e)[:100]}\n\n"
                    f"**📱 Use the direct download link instead**"
                )
                return False
        
        # Clean up: Delete the temporary file
        try:
            os.remove(file_path)
            logger.info(f"Cleaned up temporary file: {file_path}")
        except Exception as e:
            logger.error(f"Error cleaning up file: {e}")
        
        # Delete progress message
        try:
            await progress_msg.delete()
        except Exception:
            pass
        
        if sent_msg:
            # Auto delete after 15 minutes
            asyncio.create_task(auto_delete_message(client, chat_id, sent_msg.id, delay=900))
            return sent_msg
        
        return False
        
    except Exception as e:
        logger.error(f"Error in send_video_file: {e}")
        return False

# Upload progress callback
async def upload_progress(current, total, progress_msg, filename):
    """Progress callback for file uploads"""
    try:
        if total > 0:
            progress = int((current / total) * 100)
            progress_bar = "█" * (progress // 5) + "░" * (20 - progress // 5)
            
            await progress_msg.edit_text(
                f"📤 **Uploading {filename}**\n\n"
                f"**Progress:** {progress}%\n"
                f"`{progress_bar}`\n"
                f"**Uploaded:** {format_file_size(current)} / {format_file_size(total)}\n"
                f"**Status:** Uploading to Telegram..."
            )
    except Exception:
        pass  # Ignore errors during progress updates

# Helper function to format file size
def format_file_size(size_bytes: int) -> str:
    """Convert bytes to human readable format"""
    if size_bytes == 0:
        return "Unknown"
    
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.1f} TB"

# Auto delete message function
async def auto_delete_message(client: Client, chat_id: int, message_id: int, delay: int = 900):
    """Auto delete message after specified delay (default 15 minutes)"""
    await asyncio.sleep(delay)
    try:
        await client.delete_messages(chat_id, message_id)
        logger.info(f"Auto-deleted message {message_id} from chat {chat_id}")
    except Exception as e:
        logger.error(f"Error deleting message: {e}")

# Clean up old temporary files
async def cleanup_temp_files():
    """Clean up temporary files older than 1 hour"""
    while True:
        try:
            current_time = datetime.now().timestamp()
            for filename in os.listdir(TEMP_DIR):
                file_path = os.path.join(TEMP_DIR, filename)
                if os.path.isfile(file_path):
                    file_age = current_time - os.path.getctime(file_path)
                    if file_age > 3600:  # 1 hour
                        os.remove(file_path)
                        logger.info(f"Cleaned up old temp file: {filename}")
        except Exception as e:
            logger.error(f"Error during temp file cleanup: {e}")
        
        await asyncio.sleep(1800)  # Run every 30 minutes

# Simple health check server
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/health':
            self.send_response(200)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
            self.wfile.write(b'OK')
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        # Suppress HTTP server logs
        pass

def get_greeting():
    """Get greeting based on current time"""
    current_hour = datetime.now().hour
    if 5 <= current_hour < 12:
        return "ɢᴏᴏᴅ ᴍᴏʀɴɪɴɢ 🌞"
    elif 12 <= current_hour < 17:
        return "ɢᴏᴏᴅ ᴀғᴛᴇʀɴᴏᴏɴ ☀️"
    elif 17 <= current_hour < 21:
        return "ɢᴏᴏᴅ ᴇᴠᴇɴɪɴɢ 🌅"
    else:
        return "ɢᴏᴏᴅ ɴɪɢʜᴛ 🌙"

def start_health_server():
    """Start a simple HTTP server for health checks"""
    server = HTTPServer(('0.0.0.0', PORT), HealthCheckHandler)
    logger.info(f"Health check server running on port {PORT}")
    server.serve_forever()

# Helper functions
async def get_all_media() -> Union[List[Dict], None]:
    try:
        response = requests.get(f"{BASE_URL}{MEDIA_ENDPOINT}", timeout=10)
        if response.status_code == 200:
            return response.json()
        return None
    except Exception as e:
        logger.error(f"Error getting all media: {e}")
        return None

async def get_media_by_id(media_id: int) -> Union[Dict, None]:
    try:
        response = requests.get(f"{BASE_URL}{MEDIA_ENDPOINT}/{media_id}", timeout=10)
        if response.status_code == 200:
            return response.json()
        return None
    except Exception as e:
        logger.error(f"Error getting media by ID: {e}")
        return None

def create_media_message(media: Dict) -> str:
    message = f"🎬 {media.get('title', 'N/A')}\n\n"
    message += f"📅 Release Date: {media.get('release_date', 'N/A')}\n"
    message += f"🌐 Language: {media.get('language', 'N/A').upper()}\n"
    message += f"⭐ Rating: {media.get('rating', 'N/A')}\n"
    message += f"⏱️ Duration: {media.get('duration', 'N/A')}\n\n"
    message += f"📝 Description: {media.get('description', 'No description available.')}\n\n"
    message += "🎭 Powered by: @filmzi2\n"
    message += "Created By: Zero Creations"
    return message

def create_quality_buttons(media: Dict) -> InlineKeyboardMarkup:
    buttons = []

    if media["type"] == "movie":
        video_links = media.get("video_links", {})
        if "1080p" in video_links:
            buttons.append([InlineKeyboardButton("📥 1080p", callback_data=f"quality_1080p_{media['id']}")])
        if "720p" in video_links:
            buttons.append([InlineKeyboardButton("📥 720p", callback_data=f"quality_720p_{media['id']}")])
        if "480p" in video_links:
            buttons.append([InlineKeyboardButton("📥 480p", callback_data=f"quality_480p_{media['id']}")])
    elif media["type"] == "tv":
        seasons = media.get("seasons", {})
        for season in seasons:
            season_num = season.split("_")[1]
            buttons.append([InlineKeyboardButton(f"📺 Season {season_num}", callback_data=f"season_{season_num}_{media['id']}")])

    buttons.append([InlineKeyboardButton("🔙 Back", callback_data="back_to_search")])
    return InlineKeyboardMarkup(buttons)

def create_episode_buttons(season_data: Dict, media_id: int, season_num: str) -> InlineKeyboardMarkup:
    buttons = []
    for episode in season_data["episodes"]:
        ep_num = episode["episode_number"]
        buttons.append([InlineKeyboardButton(f"▶️ Episode {ep_num}", callback_data=f"episode_{season_num}_{ep_num}_{media_id}")])
    buttons.append([InlineKeyboardButton("🔙 Back", callback_data=f"back_to_seasons_{media_id}")])
    return InlineKeyboardMarkup(buttons)

def filter_media_by_query(all_media: List[Dict], query: str) -> List[Dict]:
    """Enhanced search function that matches titles and handles common variations"""
    query = query.lower().strip()
    if not query:
        return all_media

    filtered = []
    query_words = query.split()
    
    for media in all_media:
        title = media.get('title', '').lower()
        
        # Exact match
        if query in title:
            filtered.append(media)
            continue
        
        # Word-by-word match
        title_words = title.split()
        if all(any(query_word in title_word for title_word in title_words) for query_word in query_words):
            filtered.append(media)
            continue
        
        # Check if all query words are present in title
        if all(word in title for word in query_words):
            filtered.append(media)
            continue
        
        # Partial match for single words
        if len(query_words) == 1 and query in title:
            filtered.append(media)
            continue
        
        # Check keywords if available
        if 'keywords' in media and media['keywords']:
            if any(query in kw.lower() for kw in media['keywords']):
                filtered.append(media)
                continue
        
        # Check alternative titles if available
        if 'alternative_titles' in media and media['alternative_titles']:
            for alt_title in media['alternative_titles']:
                if query in alt_title.lower():
                    filtered.append(media)
                    break
    
    return filtered

async def display_result_page(client: Client, user_id: int, message_id: int, page: int, chat_id: int = None):
    if user_id not in user_data:
        return

    results = user_data[user_id]["results"]
    total_pages = len(results)
    query = user_data[user_id]["query"]
    
    if page < 0 or page >= total_pages:
        return
    
    user_data[user_id]["current_page"] = page
    media = results[page]
    
    # Prepare message
    message_text = create_media_message(media)
    message_text += f"\n\n**🔍 Search:** '{query}' | **📄 Page:** {page+1}/{total_pages}"
    
    # Prepare buttons
    buttons = []
    
    # Navigation buttons
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("⬅️ Previous", callback_data=f"result_page_{page-1}"))
    
    nav_buttons.append(InlineKeyboardButton(f"📄 {page+1}/{total_pages}", callback_data="noop"))
    
    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton("Next ➡️", callback_data=f"result_page_{page+1}"))
    
    if nav_buttons:
        buttons.append(nav_buttons)
    
    # Select button
    if media["type"] == "movie":
        buttons.append([InlineKeyboardButton("🎬 SELECT QUALITY", callback_data=f"select_{media['id']}")])
    else:
        buttons.append([InlineKeyboardButton("📺 SELECT SEASON", callback_data=f"select_{media['id']}")])
    
    # Add IMDb button if available
    if media.get("imdb_id"):
        buttons.append([InlineKeyboardButton("🔍 View on IMDb", url=f"https://www.imdb.com/title/{media['imdb_id']}")])
    
    # Try to include poster if available
    try:
        poster_url = media.get("poster_url")
        if poster_url:
            if chat_id:  # New message
                await client.send_photo(
                    chat_id=chat_id,
                    photo=poster_url,
                    caption=message_text,
                    reply_markup=InlineKeyboardMarkup(buttons)
                )
            else:  # Edit existing message
                await client.send_photo(
                    chat_id=user_id,
                    photo=poster_url,
                    caption=message_text,
                    reply_markup=InlineKeyboardMarkup(buttons)
                )
            return
    except Exception as e:
        logger.error(f"Error sending photo: {e}")
    
    # Fallback to text message if photo fails
    if message_id and not chat_id:
        await client.edit_message_text(
            chat_id=user_id,
            message_id=message_id,
            text=message_text,
            reply_markup=InlineKeyboardMarkup(buttons)
        )
    else:
        await client.send_message(
            chat_id=chat_id or user_id,
            text=message_text,
            reply_markup=InlineKeyboardMarkup(buttons)
        )

# Command handlers
@app.on_message(filters.command("start"))
async def start_command(client: Client, message: Message):
    user_id = message.from_user.id
    track_user(user_id, "search")
    user_name = message.from_user.first_name or "User"
    greeting = get_greeting()

    # Check if user is member of movie group
    is_member = await check_user_membership(client, user_id)
    
    if not is_member:
        welcome_message = (
            f"ʜᴇʏ {user_name}, {greeting}\n\n"
            "🎬 **Welcome to Filmzi Bot!**\n\n"
            "**⚠️ To use this bot, you must join our movie updates group first!**\n\n"
            "**📢 After joining the group, come back and click 'Check Membership' to continue.**\n\n"
            "**🎥 Get latest movie updates, quality releases, and more!**"
        )
        
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🎬 JOIN MOVIE UPDATES GROUP", url=MOVIE_GROUP_LINK)],
            [InlineKeyboardButton("✅ CHECK MEMBERSHIP", callback_data="check_membership")],
            [InlineKeyboardButton("❓ HELP", callback_data="help")]
        ])
    else:
        welcome_message = (
            f"ʜᴇʏ {user_name}, {greeting}\n\n"
            "🎭 **Welcome to Filmzi - Premium Auto Filter Bot**\n\n"
            "**✨ Features:**\n"
            "• 🎬 Movies & TV Shows\n"
            "• 📁 Direct File Sending (Up to 2GB)\n"
            "• 🎥 Multiple Quality Options\n"
            "• ⚡ Fast Download & Upload\n"
            "• 🔄 Auto File Cleanup\n\n"
            "**💡 Just type any movie or TV show name to search!**\n"
            "**🎭 All files sent directly to your chat!**"
        )
        
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🛡️ ADD ME TO YOUR GROUP 🛡️", url=f"https://t.me/FilmziBot?startgroup=true")],
            [
                InlineKeyboardButton("TOP SEARCHING ⭐", callback_data="top_searches"),
                InlineKeyboardButton("HELP 📢", callback_data="help")
            ],
            [InlineKeyboardButton("📊 BOT STATS", callback_data="bot_stats")]
        ])
    
    # Send welcome image with caption
    try:
        await message.reply_photo(
            photo="https://ar-hosting.pages.dev/1754324374997.jpg",
            caption=welcome_message,
            reply_markup=keyboard
        )
    except Exception as e:
