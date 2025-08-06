import os
import re
import asyncio
import threading
import json
import logging
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
import requests
from typing import Dict, List, Union
import tempfile
import urllib.parse

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

# Initialize the bot
app = Client("Filmzi", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# User data cache (for pagination and state management)
user_data = {}
user_stats = {}
start_time = datetime.now()

# File download session
download_session = None

async def init_download_session():
    """Initialize aiohttp session for downloads"""
    global download_session
    if download_session is None:
        timeout = aiohttp.ClientTimeout(total=3600)  # 1 hour timeout
        download_session = aiohttp.ClientSession(
            timeout=timeout,
            headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }
        )

async def close_download_session():
    """Close aiohttp session"""
    global download_session
    if download_session:
        await download_session.close()
        download_session = None

def get_filename_from_url(url: str, title: str = "video") -> str:
    """Extract filename from URL or create one"""
    try:
        # Try to get filename from URL
        parsed_url = urllib.parse.urlparse(url)
        filename = os.path.basename(parsed_url.path)
        
        # If no filename in URL, create one from title
        if not filename or '.' not in filename:
            # Clean title for filename
            clean_title = re.sub(r'[^\w\s-]', '', title)
            clean_title = re.sub(r'[-\s]+', '_', clean_title)
            filename = f"{clean_title}.mp4"
        
        return filename
    except:
        return f"{title}.mp4"

async def download_and_send_file(client: Client, chat_id: int, url: str, title: str, quality: str = "", file_size: str = ""):
    """Download file from URL and send to user"""
    try:
        await init_download_session()
        
        # Send initial message
        status_msg = await client.send_message(
            chat_id=chat_id,
            text=f"📥 **Downloading {title}**\n\n⏳ Please wait, this may take a few minutes..."
        )
        
        filename = get_filename_from_url(url, title)
        
        # Create temporary file
        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(filename)[1]) as temp_file:
            temp_path = temp_file.name
            
            # Download file with progress tracking
            async with download_session.get(url) as response:
                if response.status != 200:
                    raise Exception(f"HTTP {response.status}: Unable to download file")
                
                total_size = int(response.headers.get('content-length', 0))
                downloaded = 0
                chunk_size = 8192 * 16  # 128KB chunks for faster download
                
                last_progress_update = 0
                
                async for chunk in response.content.iter_chunked(chunk_size):
                    temp_file.write(chunk)
                    downloaded += len(chunk)
                    
                    # Update progress every 5MB or 10% (whichever is smaller)
                    if total_size > 0:
                        progress = (downloaded / total_size) * 100
                        if progress - last_progress_update >= 10:  # Update every 10%
                            try:
                                await status_msg.edit_text(
                                    f"📥 **Downloading {title}**\n\n"
                                    f"📊 Progress: {progress:.1f}%\n"
                                    f"📦 Downloaded: {downloaded // (1024*1024)} MB"
                                    f"{f' / {total_size // (1024*1024)} MB' if total_size > 0 else ''}"
                                )
                                last_progress_update = progress
                            except:
                                pass  # Ignore edit errors
        
        # Update status to uploading
        try:
            await status_msg.edit_text(
                f"📤 **Uploading {title}**\n\n⬆️ Preparing to send file..."
            )
        except:
            pass
        
        # Prepare caption
        caption = f"🎬 **{title}**"
        if quality:
            caption += f" - **{quality.upper()}**"
        if file_size:
            caption += f"\n📁 **Size:** {file_size}"
        
        caption += f"\n\n⚡ **Fast Download Complete**\n"
        caption += f"📱 **File:** {filename}\n\n"
        caption += "**Created By:** [Zero Creations](https://t.me/zerocreations)"
        
        # Send file as document
        try:
            sent_msg = await client.send_document(
                chat_id=chat_id,
                document=temp_path,
                file_name=filename,
                caption=caption,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("⭐ Rate This", callback_data=f"rate_{title[:20]}")]
                ])
            )
            
            # Delete status message
            try:
                await status_msg.delete()
            except:
                pass
            
            # Schedule file deletion after 30 minutes
            asyncio.create_task(auto_delete_message(client, chat_id, sent_msg.id, 1800))
            
        except Exception as e:
            logger.error(f"Error sending document: {e}")
            # If document send fails, try as video
            try:
                sent_msg = await client.send_video(
                    chat_id=chat_id,
                    video=temp_path,
                    file_name=filename,
                    caption=caption,
                    supports_streaming=True,
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("⭐ Rate This", callback_data=f"rate_{title[:20]}")]
                    ])
                )
                
                # Delete status message
                try:
                    await status_msg.delete()
                except:
                    pass
                
                # Schedule file deletion after 30 minutes
                asyncio.create_task(auto_delete_message(client, chat_id, sent_msg.id, 1800))
                
            except Exception as video_error:
                logger.error(f"Error sending video: {video_error}")
                # Final fallback - send download link
                await status_msg.edit_text(
                    f"❌ **Upload Failed**\n\n"
                    f"**File was downloaded but couldn't be uploaded to Telegram.**\n"
                    f"**This might be due to file size limits.**\n\n"
                    f"**Direct Download Link:**\n{url}\n\n"
                    "**Note:** Link may expire soon, download quickly!",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔗 Direct Download", url=url)]
                    ])
                )
        
        # Clean up temporary file
        try:
            os.unlink(temp_path)
        except:
            pass
            
    except Exception as e:
        logger.error(f"Error downloading file: {e}")
        try:
            await status_msg.edit_text(
                f"❌ **Download Failed**\n\n"
                f"**Error:** {str(e)}\n\n"
                f"**Try the direct link instead:**",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔗 Direct Download", url=url)]
                ])
            )
        except:
            await client.send_message(
                chat_id=chat_id,
                text=f"❌ **Download Failed**\n\n**Error:** {str(e)}\n\n**Direct Link:** {url}"
            )

def is_streamable_url(url: str) -> bool:
    """Check if URL is likely to be streamable/downloadable"""
    try:
        parsed = urllib.parse.urlparse(url)
        domain = parsed.netloc.lower()
        
        # Known file hosting services
        streamable_domains = [
            'pixeldrain.com',
            'pixeldrain.dev',
            'drive.google.com',
            'dropbox.com',
            'mediafire.com',
            'mega.nz',
            'wetransfer.com',
            'sendspace.com',
            'zippyshare.com',
            'rapidgator.net',
            'uploaded.net',
            'file.io',
            'gofile.io',
            '1fichier.com',
            'uptobox.com',
            'nitroflare.com',
        ]
        
        # Check if it's a direct file URL (has file extension)
        file_extensions = ['.mp4', '.mkv', '.avi', '.mov', '.wmv', '.flv', '.webm', '.m4v', '.3gp', '.ts']
        if any(url.lower().endswith(ext) for ext in file_extensions):
            return True
            
        # Check known domains
        if any(domain in streamable_domain for streamable_domain in streamable_domains):
            return True
            
        # Check for download parameter
        if 'download' in parsed.query.lower():
            return True
            
        return False
    except:
        return False

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
    message += "Powered By: Filmzi 🎥\n"
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
        # If TV series, directly show seasons without quality check
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

async def auto_delete_message(client: Client, chat_id: int, message_id: int, delay: int = 600):
    """Auto delete message after specified delay (default 10 minutes)"""
    await asyncio.sleep(delay)
    try:
        await client.delete_messages(chat_id, message_id)
    except Exception as e:
        logger.error(f"Error deleting message: {e}")

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
            "ɪ ᴀᴍ ᴛʜᴇ ᴍᴏsᴛ ᴘᴏᴡᴇʀғᴜʟ ᴀᴜᴛᴏ ғɪʟᴛᴇʀ ʙᴏᴛ ᴡɪᴛʜ ᴘʀᴇᴍɪᴜᴍ\n"
            "I ᴄᴀɴ ᴘʀᴏᴠɪᴅᴇ ᴍᴏᴠɪᴇs ᴊᴜsᴛ ᴀᴅᴅ ᴍᴇ ᴛᴏ ʏᴏᴜʀ ɢʀᴏᴜᴘ ᴏʀ sᴇɴᴅ ᴍᴏᴠɪᴇ ɴᴀᴍᴇ ᴀɴᴅ ᴇɴᴊᴏʏ\n\n"
            "ɴᴇᴇᴅ ᴘʀᴇᴍɪᴜᴍ 👉 /plan\n\n"
            "**💡 Just type any movie or TV show name to search!**"
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

# Add command handler for /stats (admin only)
@app.on_message(filters.command("stats") & filters.user(ADMIN_ID))
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
    
    stats_message = (
        f"**📊 BOT STATISTICS**\n\n"
        f"**👥 Total Users:** {total_users}\n"
        f"**🔍 Today's Searches:** {today_searches}\n"
        f"**📥 Today's Downloads:** {today_downloads}\n\n"
        f"**🚀 Server Uptime:** {datetime.now() - start_time}\n"
        f"**💾 Memory Usage:** {get_memory_usage()} MB"
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
                "ɪ ᴀᴍ ᴛʜᴇ ᴍᴏsᴛ ᴘᴏᴡᴇʀғᴜʟ ᴀᴜᴛᴏ ғɪʟᴛᴇʀ ʙᴏᴛ ᴡɪᴛʜ ᴘʀᴇᴍɪᴜᴍ\n"
                "I ᴄᴀɴ ᴘʀᴏᴠɪᴅᴇ ᴍᴏᴠɪᴇs ᴊᴜsᴛ ᴀᴅᴅ ᴍᴇ ᴛᴏ ʏᴏᴜʀ ɢʀᴏᴜᴘ ᴏʀ sᴇɴᴅ ᴍᴏᴠɪᴇ ɴᴀᴍᴇ ᴀɴᴅ ᴇɴᴊᴏʏ\n\n"
                "ɴᴇᴇᴅ ᴘʀᴇᴍɪᴜᴍ 👉 /plan\n\n"
                "**💡 Just type any movie or TV show name to search!**"
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
        
        # Check if URL is streamable and send directly
        if is_streamable_url(video_url):
            await callback_query.answer("📥 Starting download...", show_alert=True)
            
            # Start download and send task
            asyncio.create_task(download_and_send_file(
                client,
                user_id,
                video_url,
                media.get('title', 'Movie'),
                quality,
                media.get('size', '')
            ))
            
        else:
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
            "**Select an episode:**",
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
        
        # Check if URL is streamable and send directly
        if is_streamable_url(video_url):
            await callback_query.answer("📥 Starting download...", show_alert=True)
            
            episode_title = f"{media.get('title', 'Series')} S{season_num}E{episode_num}"
            if episode.get('title'):
                episode_title += f" - {episode['title']}"
            
            # Start download and send task
            asyncio.create_task(download_and_send_file(
                client,
                user_id,
                video_url,
                episode_title,
                quality,
                episode.get('size', '')
            ))
            
        else:
            # Fallback to download link message
            message_text = (
                f"**📺 {media.get('title', 'N/A')} - S{season_num}E{episode_num}**\n\n"
                f"**📁 Size:** {episode.get('size', 'N/A')}\n"
                f"**🎥 Quality:** {quality.upper()}\n"
                f"**📝 Episode Title:** {episode.get('title', 'N/A')}\n\n"
                "**⚠️ LINK EXPIRES IN 10 MINUTES**\n\n"
                "**Created By:** [Zero Creations](https://t.me/zerocreations)"
            )
            
            buttons = InlineKeyboardMarkup([
                [InlineKeyboardButton("🚀 FAST DOWNLOAD", url=video_url)],
                [InlineKeyboardButton("⭐ RATE THIS EPISODE", callback_data=f"rate_{media_id}_{season_num}_{episode_num}"),
                 InlineKeyboardButton("🔙 Back", callback_data=f"season_{season_num}_{media_id}")]
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
                "**🎬 Movies:**\n"
                "1. Spider-Man: No Way Home\n"
                "2. The Matrix\n"
                "3. Inception\n"
                "4. Interstellar\n"
                "5. Avengers: Endgame\n\n"
                "**📺 TV Shows:**\n"
                "1. Breaking Bad\n"
                "2. Stranger Things\n"
                "3. Game of Thrones\n"
                "4. The Office\n"
                "5. Friends\n\n"
                "**💡 Search Tips:**\n"
                "• Use exact movie names\n"
                "• Try different spellings\n"
                "• Include release year if needed"
            )
        elif data == "help":
            text = (
                "**📢 HELP - HOW TO USE FILMZI BOT**\n\n"
                "**🔍 Search Movies/TV Shows:**\n"
                "• Type the name of any movie or TV show\n"
                "• Bot will search the database automatically\n"
                "• Use 2+ characters for better results\n\n"
                "**🎬 For Movies:**\n"
                "• Browse through search results\n"
                "• Select quality (480p, 720p, 1080p)\n"
                "• Get direct file or download link\n\n"
                "**📺 For TV Shows:**\n"
                "• Choose season\n"
                "• Select episode\n"
                "• Auto quality selection\n\n"
                "**⚠️ Important Notes:**\n"
                "• Must join movie updates group\n"
                "• Files auto-delete in 30 minutes\n"
                "• Save files to your device quickly\n"
                "• Bot works in groups too!\n\n"
                "**🎥 Movie Updates:** [Join Group](https://t.me/filmzi2)\n"
                "**💎 Need Premium?** Contact: [Zero Creations](https://t.me/zerocreations)"
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
            
            text = (
                f"**📊 FILMZI BOT STATISTICS**\n\n"
                f"**👥 Total Users:** {total_users:,}\n"
                f"**🔥 Active Today:** {active_today:,}\n"
                f"**🔍 Today's Searches:** {today_searches:,}\n"
                f"**📥 Today's Downloads:** {today_downloads:,}\n\n"
                f"**🎬 Movie Updates:** [Join Group](https://t.me/filmzi2)\n"
                f"**⚡ Status:** Online & Fast\n"
                f"**🌐 Database:** Live & Updated\n\n"
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
            "ɪ ᴀᴍ ᴛʜᴇ ᴍᴏsᴛ ᴘᴏᴡᴇʀғᴜʟ ᴀᴜᴛᴏ ғɪʟᴛᴇʀ ʙᴏᴛ ᴡɪᴛʜ ᴘʀᴇᴍɪᴜᴍ\n"
            "I ᴄᴀɴ ᴘʀᴏᴠɪᴅᴇ ᴍᴏᴠɪᴇs ᴊᴜsᴛ ᴀᴅᴅ ᴍᴇ ᴛᴏ ʏᴏᴜʀ ɢʀᴏᴜᴘ ᴏʀ sᴇɴᴅ ᴍᴏᴠɪᴇ ɴᴀᴍᴇ ᴀɴᴅ ᴇɴᴊᴏʏ\n\n"
            "ɴᴇᴇᴅ ᴘʀᴇᴍɪᴜᴍ 👉 /plan\n\n"
            "**💡 Just type any movie or TV show name to search!**"
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
    
    message_text += f"\n\n**📱 Click any movie/show to get download links in private chat**"
    
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

# Run the bot
if __name__ == "__main__":
    logger.info("Starting Filmzi Bot...")
    start_time = datetime.now()

    # Load statistics
    load_stats()
    
    # Start health check server in a separate thread
    health_thread = threading.Thread(target=start_health_server, daemon=True)
    health_thread.start()
    
    # Set up cleanup on exit
    import atexit
    atexit.register(lambda: asyncio.run(close_download_session()) if download_session else None)
    
    logger.info("Filmzi Bot is running...")
    app.run()
