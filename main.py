import os
import re
import asyncio
import threading
import json
import logging
import difflib
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from pyrogram import Client, filters
from pyrogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    Message,
    CallbackQuery,
)
import requests
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

# API configuration
MEDIA_ENDPOINT = "/media"
STATS_FILE = "user_stats.json"

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
    message = f"**🎬 {media.get('title', 'N/A')}**\n\n"
    release_date = media.get('release_date', 'N/A')
    if release_date != 'N/A' and len(release_date) > 4:
        release_date = release_date[:4]  # Extract year only
    message += f"**📅 Year:** {release_date}\n"
    message += f"**🌐 Language:** {media.get('language', 'N/A').upper()}\n"
    message += f"**⭐ Rating:** {media.get('rating', 'N/A')}\n"
    message += f"**⏱️ Duration:** {media.get('duration', 'N/A')}\n\n"
    message += f"**📝 Description:** {media.get('description', 'No description available.')}\n\n"
    message += "**Powered By:** Filmzi 🎥\n"
    message += "**Created By:** [Zero Creations](https://t.me/zerocreations)"
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
        # If TV series, directly show seasons without quality check
        for season in seasons:
            season_num = season.split("_")[1]
            buttons.append([InlineKeyboardButton(f"📺 Season {season_num}", callback_data=f"season_{season_num}_{media['id']}")])
    
    buttons.append([InlineKeyboardButton("🔙 Back to Results", callback_data="back_to_search")])
    return InlineKeyboardMarkup(buttons)

def create_episode_buttons(season_data: Dict, media_id: int, season_num: str) -> InlineKeyboardMarkup:
    buttons = []
    for episode in season_data["episodes"]:
        ep_num = episode["episode_number"]
        buttons.append([InlineKeyboardButton(f"▶️ Episode {ep_num}", callback_data=f"episode_{season_num}_{ep_num}_{media_id}")])
    buttons.append([InlineKeyboardButton("🔙 Back to Seasons", callback_data=f"back_to_seasons_{media_id}")])
    return InlineKeyboardMarkup(buttons)

def filter_media_by_query(all_media: List[Dict], query: str) -> List[Dict]:
    query = query.lower().strip()
    if not query:
        return all_media
    
    filtered = []
    for media in all_media:
        if query in media.get('title', '').lower():
            filtered.append(media)
        elif 'keywords' in media and any(query in kw.lower() for kw in media['keywords']):
            filtered.append(media)
    
    return filtered

def get_suggestions(query: str, all_titles: List[str]) -> List[str]:
    """Get spelling suggestions for search query"""
    suggestions = difflib.get_close_matches(query, all_titles, n=3, cutoff=0.6)
    return suggestions

async def auto_delete_message(client: Client, chat_id: int, message_id: int, delay: int = 600):
    """Auto delete message after specified delay (default 10 minutes)"""
    await asyncio.sleep(delay)
    try:
        await client.delete_messages(chat_id, message_id)
    except Exception as e:
        logger.error(f"Error deleting message: {e}")

# New function to display search results in grid format
async def display_search_results_grid(client: Client, user_id: int, results: List[Dict], chat_id: int, query: str):
    if not results:
        all_media = await get_all_media()
        all_titles = [media['title'].lower() for media in all_media]
        suggestions = get_suggestions(query.lower(), all_titles)
        
        message_text = f"**❌ No results found for '{query}'**"
        if suggestions:
            message_text += "\n\n**Did you mean?**\n"
            for i, suggestion in enumerate(suggestions, 1):
                message_text += f"{i}. `{suggestion}`\n"
        
        await client.send_message(
            chat_id=chat_id,
            text=message_text,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Search Again", callback_data="back_to_start")]
            ])
        )
        return
    
    # Store results for pagination
    user_data[user_id] = {
        "results": results,
        "current_page": 0,
        "query": query
    }
    
    # Create media grid buttons
    buttons = []
    for i, media in enumerate(results[:10]):  # First 10 results
        release_year = media.get('release_date', 'N/A')
        if release_year != 'N/A' and len(release_year) > 4:
            release_year = release_year[:4]  # Extract year only
        
        # Create button with title and year
        button_text = f"{media['title']} ({release_year})"
        buttons.append(
            [InlineKeyboardButton(button_text, callback_data=f"select_{media['id']}")]
        )
    
    # Add navigation buttons if more than 10 results
    if len(results) > 10:
        buttons.append([
            InlineKeyboardButton("⬅️", callback_data="grid_page_prev"),
            InlineKeyboardButton("1/1", callback_data="noop"),
            InlineKeyboardButton("➡️", callback_data="grid_page_next")
        ])
    
    buttons.append([InlineKeyboardButton("🔙 New Search", callback_data="back_to_start")])
    
    # Try to send grid with poster if available
    try:
        # Use first result's poster as grid header
        poster_url = results[0].get("poster_url", "https://ar-hosting.pages.dev/1754324374997.jpg")
        await client.send_photo(
            chat_id=chat_id,
            photo=poster_url,
            caption=f"**🎬 Found {len(results)} results for '{query}'**\n"
                    "Select a movie or series to see details:",
            reply_markup=InlineKeyboardMarkup(buttons)
        )
    except Exception as e:
        logger.error(f"Error sending photo grid: {e}")
        # Fallback to text message
        await client.send_message(
            chat_id=chat_id,
            text=f"**🎬 Found {len(results)} results for '{query}'**\n"
                 "Select a movie or series to see details:",
            reply_markup=InlineKeyboardMarkup(buttons)
        )

# Command handlers
@app.on_message(filters.command("start"))
async def start_command(client: Client, message: Message):
    user_id = message.from_user.id
    track_user(user_id, "search")
    user_name = message.from_user.first_name or "User"
    greeting = get_greeting()
    
    welcome_message = (
        f"ʜᴇʏ {user_name}, {greeting}\n\n"
        "ɪ ᴀᴍ ᴛʜᴇ ᴍᴏsᴛ ᴘᴏᴡᴇʀғᴜʟ ᴀᴜᴛᴏ ғɪʟᴛᴇʀ ʙᴏᴛ ᴡɪᴛʜ ᴘʀᴇᴍɪᴜᴍ\n"
        "I ᴄᴀɴ ᴘʀᴏᴠɪᴅᴇ ᴍᴏᴠɪᴇs ᴊᴜsᴛ ᴀᴅᴅ ᴍᴇ ᴛᴏ ʏᴏᴜʀ ɢʀᴏᴜᴘ ᴏʀ sᴇɴᴅ ᴍᴏᴠɪᴇ ɴᴀᴍᴇ ᴀɴᴅ ᴇɴᴊᴏʏ\n\n"
        "ɴᴇᴇᴅ ᴘʀᴇᴍɪᴜᴍ 👉 /plan"
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
        logger.error(f"Error sending photo: {e}")
        # Fallback to text message if photo fails
        await message.reply_text(welcome_message, reply_markup=keyboard)

# Add command handler for /plan
@app.on_message(filters.command("plan"))
async def plan_command(client: Client, message: Message):
    track_user(message.from_user.id, "search")
    plan_message = (
        "**💎 PREMIUM PLANS 💎**\n\n"
        "**🔥 Premium Features:**\n"
        "• Unlimited downloads\n"
        "• No ads\n"
        "• Priority support\n"
        "• Early access to new movies\n"
        "• Multiple download links\n"
        "• HD & 4K quality options\n\n"
        "**💰 Pricing:**\n"
        "• 1 Month - $5\n"
        "• 3 Months - $12\n"
        "• 6 Months - $20\n"
        "• 1 Year - $35\n\n"
        "**Contact for Premium:** [Zero Creations](https://t.me/zerocreations)"
    )
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("💎 GET PREMIUM", url="https://t.me/zerocreations")],
        [InlineKeyboardButton("🔙 Back to Home", callback_data="back_to_start")]
    ])
    
    await message.reply_text(plan_message, reply_markup=keyboard)

# Auto-filter handler (text-based search)
@app.on_message(filters.text & filters.private & ~filters.command(["start", "plan", "stats"]))
async def auto_filter(client: Client, message: Message):
    user_id = message.from_user.id
    track_user(user_id, "search")
    query = message.text.strip()
    if len(query) < 3:
        await message.reply_text("**Please enter at least 3 characters to search.**")
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
        await search_msg.edit_text(f"**❌ No results found for '{query}'**")
        return
    
    results = filter_media_by_query(all_media, query)
    
    # Delete the searching message
    try:
        await search_msg.delete()
    except:
        pass
    
    # Display results in grid format
    await display_search_results_grid(client, user_id, results, message.chat.id, query)

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
    
    # Prepare buttons
    buttons = []
    
    # Navigation buttons
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("⬅️ Back", callback_data=f"result_page_{page-1}"))
    
    nav_buttons.append(InlineKeyboardButton(f"{page+1}/{total_pages}", callback_data="noop"))
    
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
    
    # Add back to grid button
    buttons.append([InlineKeyboardButton("🔙 Back to Results", callback_data="back_to_search")])
    
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

# Callback query handlers
@app.on_callback_query()
async def handle_callback_query(client: Client, callback_query: CallbackQuery):
    data = callback_query.data
    user_id = callback_query.from_user.id
    track_user(user_id, "search")
    
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
        
        # Display media details page
        message_text = create_media_message(media)
        
        # Prepare buttons
        buttons = []
        if media["type"] == "movie":
            buttons.append([InlineKeyboardButton("🎬 SELECT QUALITY", callback_data=f"select_{media_id}")])
        else:
            buttons.append([InlineKeyboardButton("📺 SELECT SEASON", callback_data=f"select_{media_id}")])
        
        # Add IMDb button if available
        if media.get("imdb_id"):
            buttons.append([InlineKeyboardButton("🔍 View on IMDb", url=f"https://www.imdb.com/title/{media['imdb_id']}")])
        
        buttons.append([InlineKeyboardButton("🔙 Back to Results", callback_data="back_to_search")])
        
        # Try to include poster
        try:
            poster_url = media.get("poster_url")
            if poster_url:
                await callback_query.message.reply_photo(
                    photo=poster_url,
                    caption=message_text,
                    reply_markup=InlineKeyboardMarkup(buttons)
                )
                await callback_query.message.delete()
                await callback_query.answer()
                return
        except Exception as e:
            logger.error(f"Error sending photo: {e}")
        
        # Fallback to text
        await callback_query.edit_message_text(
            message_text,
            reply_markup=InlineKeyboardMarkup(buttons)
        )
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
        
        # Send video file directly
        try:
            # Try to send as document first
            sent_msg = await client.send_document(
                chat_id=callback_query.from_user.id,
                document=video_url,
                caption=f"**🎬 {media.get('title', 'N/A')} - {quality.upper()}**\n\n"
                        f"**📁 Size:** {media.get('size', 'N/A')}\n"
                        f"**🎥 Quality:** {quality.upper()}\n\n"
                        "**⚠️ This file will be deleted in 10 minutes**\n\n"
                        "**Created By:** [Zero Creations](https://t.me/zerocreations)",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🚀 FAST DOWNLOAD", url=video_url)],
                    [InlineKeyboardButton("⭐ RATE THIS MOVIE", callback_data=f"rate_{media_id}_{quality}")]
                ])
            )
            
            # Auto delete after 10 minutes
            asyncio.create_task(auto_delete_message(
                client, 
                callback_query.from_user.id, 
                sent_msg.id
            ))
            
        except Exception as e:
            logger.error(f"Error sending document: {e}")
            # Fallback to download link message
            message_text = (
                f"**🎬 {media.get('title', 'N/A')} - {quality.upper()}**\n\n"
                f"**📁 Size:** {media.get('size', 'N/A')}\n"
                f"**🎥 Quality:** {quality.upper()}\n\n"
                "**⚠️ LINK EXPIRES IN 10 MINUTES**\n\n"
                "**Created By:** [Zero Creations](https://t.me/zerocreations)"
            )
            
            buttons = InlineKeyboardMarkup([
                [InlineKeyboardButton("🚀 FAST DOWNLOAD", url=video_url)],
                [InlineKeyboardButton("⭐ RATE THIS MOVIE", callback_data=f"rate_{media_id}_{quality}"),
                 InlineKeyboardButton("🔙 Back", callback_data=f"back_to_quality_{media_id}")]
            ])
            
            await callback_query.edit_message_text(
                message_text,
                reply_markup=buttons
            )
            
            # Auto delete after 10 minutes
            asyncio.create_task(auto_delete_message(
                client, 
                callback_query.message.chat.id, 
                callback_query.message.id
            ))
        
        await callback_query.answer()
    
    elif data == "back_to_search":
        if user_id in user_data:
            query = user_data[user_id]["query"]
            results = user_data[user_id]["results"]
            await display_search_results_grid(client, user_id, results, callback_query.message.chat.id, query)
            await callback_query.message.delete()
        await callback_query.answer()
    
    # Other handlers remain the same...

# Run the bot
if __name__ == "__main__":
    logger.info("Starting Filmzi Bot...")
    start_time = datetime.now()
    
    # Load statistics
    load_stats()
    
    # Start health check server in a separate thread
    health_thread = threading.Thread(target=start_health_server, daemon=True)
    health_thread.start()
    
    logger.info("Filmzi Bot is running...")
    app.run()
