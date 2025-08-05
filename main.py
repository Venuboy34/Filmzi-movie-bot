import os
import re
import asyncio
import threading
import json
import logging
import difflib
from datetime import datetime, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler
from pyrogram import Client, filters, idle
from pyrogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    Message,
    CallbackQuery,
)
import requests
from typing import Dict, List, Union, Tuple

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Environment variables
API_ID = os.getenv('API_ID', 26091026)
API_HASH = os.getenv('API_HASH', "f608d185d836e0405775833c6888922f")
BOT_TOKEN = os.getenv('BOT_TOKEN', "7613692613:AAGkBg5_PDJkNSVf_a0uU0nYNS09GceDltw")
BASE_URL = os.getenv('BASE_URL', "https://v0-flask-movie-database-nine.vercel.app")
PORT = int(os.getenv('PORT', 8000))
ADMIN_ID = int(os.getenv('ADMIN_ID', 0))

# API configuration
MEDIA_ENDPOINT = "/media"
STATS_FILE = "user_stats.json"

# Initialize the bot
app = Client("Filmzi", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# Data storage
user_data = {}
user_stats = {}
media_cache = {
    "last_updated": None,
    "data": [],
    "titles": []
}

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
            user_stats[user_id]["search_count"] += 1
        elif action == "download":
            user_stats[user_id]["download_count"] += 1
        save_stats()
    except Exception as e:
        logger.error(f"Error tracking user: {e}")

# Health check server
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
        pass

def start_health_server():
    server = HTTPServer(('0.0.0.0', PORT), HealthCheckHandler)
    logger.info(f"Health check server running on port {PORT}")
    server.serve_forever()

# Greeting based on time
def get_greeting():
    current_hour = datetime.now().hour
    if 5 <= current_hour < 12: return "ɢᴏᴏᴅ ᴍᴏʀɴɪɴɢ 🌞"
    elif 12 <= current_hour < 17: return "ɢᴏᴏᴅ ᴀғᴛᴇʀɴᴏᴏɴ ☀️"
    elif 17 <= current_hour < 21: return "ɢᴏᴏᴅ ᴇᴠᴇɴɪɴɢ 🌅"
    else: return "ɢᴏᴏᴅ ɴɪɢʜᴛ 🌙"

# Media functions
async def get_all_media() -> Tuple[List[Dict], List[str]]:
    global media_cache
    if media_cache["data"] and media_cache["last_updated"]:
        if datetime.now() - media_cache["last_updated"] < timedelta(minutes=5):
            return media_cache["data"], media_cache["titles"]
    
    try:
        response = requests.get(f"{BASE_URL}{MEDIA_ENDPOINT}", timeout=15)
        if response.status_code == 200:
            all_media = response.json()
            titles = [media.get('title', '').lower() for media in all_media]
            media_cache = {
                "last_updated": datetime.now(),
                "data": all_media,
                "titles": titles
            }
            return all_media, titles
        return [], []
    except Exception as e:
        logger.error(f"Error getting all media: {e}")
        return [], []

async def get_media_by_id(media_id: int) -> Union[Dict, None]:
    try:
        response = requests.get(f"{BASE_URL}{MEDIA_ENDPOINT}/{media_id}", timeout=15)
        if response.status_code == 200:
            return response.json()
        return None
    except Exception as e:
        logger.error(f"Error getting media by ID: {e}")
        return None

def create_media_message(media: Dict) -> str:
    release_date = media.get('release_date', 'N/A')
    if release_date != 'N/A' and len(release_date) > 4:
        release_date = release_date[:4]
    return (
        f"**🎬 {media.get('title', 'N/A')}**\n\n"
        f"**📅 Year:** {release_date}\n"
        f"**🌐 Language:** {media.get('language', 'N/A').upper()}\n"
        f"**⭐ Rating:** {media.get('rating', 'N/A')}\n"
        f"**⏱️ Duration:** {media.get('duration', 'N/A')}\n\n"
        f"**📝 Description:** {media.get('description', 'No description available.')}\n\n"
        "**Powered By:** Filmzi 🎥\n"
        "**Created By:** [Zero Creations](https://t.me/zerocreations)"
    )

def create_quality_buttons(media: Dict) -> InlineKeyboardMarkup:
    buttons = []
    if media["type"] == "movie":
        for quality in ["1080p", "720p", "480p"]:
            if quality in media.get("video_links", {}):
                buttons.append([InlineKeyboardButton(f"📥 {quality}", callback_data=f"quality_{quality}_{media['id']}")])
    elif media["type"] == "tv":
        for season in media.get("seasons", {}):
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
        return []
    
    exact_matches = []
    partial_matches = []
    
    for media in all_media:
        title = media.get('title', '').lower()
        if query == title:
            exact_matches.append(media)
        elif query in title:
            partial_matches.append(media)
    
    if exact_matches:
        return exact_matches
    
    if not partial_matches:
        titles = [m.get('title', '').lower() for m in all_media]
        for media in all_media:
            title = media.get('title', '').lower()
            if difflib.SequenceMatcher(None, query, title).ratio() > 0.6:
                partial_matches.append(media)
    
    return partial_matches

def get_suggestions(query: str, all_titles: List[str]) -> List[str]:
    return difflib.get_close_matches(query, all_titles, n=3, cutoff=0.5)

async def auto_delete_message(client: Client, chat_id: int, message_id: int, delay: int = 600):
    await asyncio.sleep(delay)
    try:
        await client.delete_messages(chat_id, message_id)
    except Exception as e:
        logger.error(f"Error deleting message: {e}")

async def display_search_results_grid(client: Client, user_id: int, results: List[Dict], chat_id: int, query: str):
    if not results:
        all_media, all_titles = await get_all_media()
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
    
    user_data[user_id] = {
        "results": results,
        "current_page": 0,
        "query": query
    }
    
    buttons = []
    for media in results[:10]:
        release_year = media.get('release_date', 'N/A')[:4] if media.get('release_date', 'N/A') != 'N/A' else 'N/A'
        buttons.append([InlineKeyboardButton(
            f"{media['title']} ({release_year})", 
            callback_data=f"select_{media['id']}"
        )])
    
    if len(results) > 10:
        buttons.append([
            InlineKeyboardButton("⬅️", callback_data="grid_page_prev"),
            InlineKeyboardButton("1/1", callback_data="noop"),
            InlineKeyboardButton("➡️", callback_data="grid_page_next")
        ])
    
    buttons.append([InlineKeyboardButton("🔙 New Search", callback_data="back_to_start")])
    
    poster_url = results[0].get("poster_url", "https://ar-hosting.pages.dev/1754324374997.jpg")
    try:
        await client.send_photo(
            chat_id=chat_id,
            photo=poster_url,
            caption=f"**🎬 Found {len(results)} results for '{query}'**\nSelect a movie or series:",
            reply_markup=InlineKeyboardMarkup(buttons)
        )
    except Exception as e:
        logger.error(f"Error sending photo grid: {e}")
        await client.send_message(
            chat_id=chat_id,
            text=f"**🎬 Found {len(results)} results for '{query}'**\nSelect a movie or series:",
            reply_markup=InlineKeyboardMarkup(buttons)
        )

# Command handlers
@app.on_message(filters.command("start"))
async def start_command(client: Client, message: Message):
    user_name = message.from_user.first_name or "User"
    welcome_message = (
        f"ʜᴇʏ {user_name}, {get_greeting()}\n\n"
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
    
    try:
        await message.reply_photo(
            photo="https://ar-hosting.pages.dev/1754324374997.jpg",
            caption=welcome_message,
            reply_markup=keyboard
        )
    except Exception as e:
        logger.error(f"Error sending photo: {e}")
        await message.reply_text(welcome_message, reply_markup=keyboard)

@app.on_message(filters.command("plan"))
async def plan_command(client: Client, message: Message):
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

@app.on_message(filters.text & filters.private & ~filters.command(["start", "plan", "stats"]))
async def auto_filter(client: Client, message: Message):
    query = message.text.strip()
    if len(query) < 3:
        await message.reply_text("**Please enter at least 3 characters to search.**")
        return
    
    try:
        await message.react("🔍")
    except Exception as e:
        logger.error(f"Error adding reaction: {e}")
    
    search_msg = await message.reply_text(f"🔍 Searching for '{query}'...")
    all_media, all_titles = await get_all_media()
    
    if not all_media:
        await search_msg.edit_text("**❌ Failed to load media database. Please try again later.**")
        return
    
    results = filter_media_by_query(all_media, query)
    
    try:
        await search_msg.delete()
    except:
        pass
    
    await display_search_results_grid(client, message.from_user.id, results, message.chat.id, query)

# Callback query handlers
@app.on_callback_query()
async def handle_callback_query(client: Client, callback_query: CallbackQuery):
    data = callback_query.data
    user_id = callback_query.from_user.id
    
    if data.startswith("select_"):
        media_id = int(data.split("_")[1])
        media = await get_media_by_id(media_id)
        if not media:
            await callback_query.answer("❌ Media not found", show_alert=True)
            return
        
        message_text = create_media_message(media)
        buttons = []
        
        if media["type"] == "movie":
            buttons.append([InlineKeyboardButton("🎬 SELECT QUALITY", callback_data=f"select_{media_id}")])
        else:
            buttons.append([InlineKeyboardButton("📺 SELECT SEASON", callback_data=f"select_{media_id}")])
        
        if media.get("imdb_id"):
            buttons.append([InlineKeyboardButton("🔍 View on IMDb", url=f"https://www.imdb.com/title/{media['imdb_id']}")])
        
        buttons.append([InlineKeyboardButton("🔙 Back to Results", callback_data="back_to_search")])
        
        poster_url = media.get("poster_url", "https://ar-hosting.pages.dev/1754324374997.jpg")
        try:
            await callback_query.message.reply_photo(
                photo=poster_url,
                caption=message_text,
                reply_markup=InlineKeyboardMarkup(buttons)
            )
            await callback_query.message.delete()
        except Exception as e:
            logger.error(f"Error sending photo: {e}")
            await callback_query.edit_message_text(
                message_text,
                reply_markup=InlineKeyboardMarkup(buttons)
            )
        await callback_query.answer()
    
    elif data.startswith("quality_"):
        quality = data.split("_")[1]
        media_id = int(data.split("_")[2])
        media = await get_media_by_id(media_id)
        
        if not media or "video_links" not in media:
            await callback_query.answer("❌ Download link not available", show_alert=True)
            return
        
        video_url = media["video_links"].get(quality)
        if not video_url:
            await callback_query.answer("❌ Download link not available", show_alert=True)
            return
        
        message_text = (
            f"**🎬 {media.get('title', 'N/A')} - {quality.upper()}**\n\n"
            f"**📁 Size:** {media.get('size', 'N/A')}\n"
            f"**🎥 Quality:** {quality.upper()}\n\n"
            "**⚠️ LINK EXPIRES IN 10 MINUTES**\n\n"
            "**Created By:** [Zero Creations](https://t.me/zerocreations)"
        )
        
        buttons = InlineKeyboardMarkup([
            [InlineKeyboardButton("🚀 FAST DOWNLOAD", url=video_url)],
            [InlineKeyboardButton("🔙 Back", callback_data=f"back_to_quality_{media_id}")]
        ])
        
        await callback_query.edit_message_text(
            message_text,
            reply_markup=buttons
        )
        
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
    
    # Simplified other handlers for brevity
    # Add your other callback handlers here...

# Keep alive function
async def keep_alive():
    while True:
        logger.info("Keep alive ping")
        await asyncio.sleep(300)

# Main async function
async def main():
    # Start health server in separate thread
    health_thread = threading.Thread(target=start_health_server, daemon=True)
    health_thread.start()
    
    # Load statistics
    load_stats()
    
    # Start the bot
    await app.start()
    logger.info("Filmzi Bot is running...")
    
    # Start keep alive task
    asyncio.create_task(keep_alive())
    
    # Run until stopped
    await idle()
    
    # Stop the bot
    await app.stop()

# Run the bot
if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    try:
        loop.run_until_complete(main())
    except KeyboardInterrupt:
        pass
    finally:
        loop.close()
