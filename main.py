"""
Discord Channel/Forum Cloner
Clone messages from Discord channels (regular or forum) to another channel
"""

import asyncio
import json
import os
import sys
import logging
import aiohttp
import aiofiles
from pathlib import Path
from datetime import datetime
import sqlite3

from filter import MessageFilter
from mediafire_uploader import MediaFireUploader
from discord_api import (
    DISCORD_API, user_headers, bot_headers,
    get, post, fetch_messages, fetch_all_threads
)

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("discord_cloner")

# Suppress mediafire warnings
logging.getLogger("mediafire").setLevel(logging.ERROR)




class StateManager:
    """Manage clone progress with SQLite"""
    
    def __init__(self, db_file="clone_state.db"):
        self.db_file = db_file
        self._init_db()
    
    def _init_db(self):
        """Initialize database"""
        with sqlite3.connect(self.db_file) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS clones (
                    id INTEGER PRIMARY KEY,
                    src_channel TEXT,
                    dest_channel TEXT,
                    thread_id TEXT,
                    msg_id TEXT,
                    processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(src_channel, dest_channel, thread_id, msg_id)
                )
            """)
            conn.commit()
    
    def is_processed(self, src_channel, dest_channel, thread_id, msg_id):
        """Check if message already cloned"""
        with sqlite3.connect(self.db_file) as conn:
            result = conn.execute(
                "SELECT 1 FROM clones WHERE src_channel=? AND dest_channel=? AND thread_id=? AND msg_id=?",
                (src_channel, dest_channel, thread_id, msg_id)
            ).fetchone()
            return result is not None
    
    def mark_processed(self, src_channel, dest_channel, thread_id, msg_id):
        """Mark message as cloned"""
        with sqlite3.connect(self.db_file) as conn:
            conn.execute(
                "INSERT OR IGNORE INTO clones (src_channel, dest_channel, thread_id, msg_id) VALUES (?,?,?,?)",
                (src_channel, dest_channel, thread_id, msg_id)
            )
            conn.commit()
    
    def get_processed_count(self, src_channel, dest_channel):
        """Get total processed messages"""
        with sqlite3.connect(self.db_file) as conn:
            result = conn.execute(
                "SELECT COUNT(*) FROM clones WHERE src_channel=? AND dest_channel=?",
                (src_channel, dest_channel)
            ).fetchone()
            return result[0] if result else 0
    
    def clear_session(self, src_channel, dest_channel):
        """Clear session data"""
        with sqlite3.connect(self.db_file) as conn:
            conn.execute(
                "DELETE FROM clones WHERE src_channel=? AND dest_channel=?",
                (src_channel, dest_channel)
            )
            conn.commit()


class DiscordCloner:
    """Main cloner class"""
    
    def __init__(self, config_file="config.json"):
        self.config = self._load_config(config_file)
        self.user_token = self.config["user_token"]
        self.bot_token = self.config["bot_token"]
        self.temp_dir = Path(self.config.get("temp_dir", "temp"))
        self.temp_dir.mkdir(exist_ok=True)
        
        self.delay_msg = self.config.get("delay_between_messages", 1.0)
        self.delay_thread = self.config.get("delay_between_threads", 2.0)
        
        # Mediafire setup
        mf_email = self.config.get("mediafire_email", "")
        mf_password = self.config.get("mediafire_password", "")
        self.mf_uploader = MediaFireUploader(mf_email, mf_password)
        
        self.mode = None  # "forum" hoặc "channel"
        self.message_filter = None
        self.state = StateManager()
    
    def _load_config(self, config_file):
        """Load config từ file"""
        try:
            with open(config_file, "r") as f:
                return json.load(f)
        except FileNotFoundError:
            logger.error(f"Config file not found: {config_file}")
            sys.exit(1)
        except json.JSONDecodeError:
            logger.error(f"Invalid JSON in {config_file}")
            sys.exit(1)
    
    async def _select_mode(self):
        """Yêu cầu người dùng chọn chế độ"""
        print("\n=== Discord Cloner - Mode Selection ===")
        print("1. Forum Channel (threads)")
        print("2. Regular Channel (messages)")
        
        while True:
            choice = input("\nSelect mode (1 or 2): ").strip()
            if choice == "1":
                self.mode = MessageFilter.FORUM_MODE
                self.message_filter = MessageFilter(MessageFilter.FORUM_MODE)
                print("✓ Mode: Forum Channel\n")
                break
            elif choice == "2":
                self.mode = MessageFilter.CHANNEL_MODE
                self.message_filter = MessageFilter(MessageFilter.CHANNEL_MODE)
                print("✓ Mode: Regular Channel\n")
                break
            else:
                print("Invalid choice. Please enter 1 or 2.")
    
    async def _download_file(self, session, url, filepath, retries=3):
        """Download file với retry"""
        for attempt in range(retries):
            try:
                async with session.get(url) as r:
                    r.raise_for_status()
                    async with aiofiles.open(filepath, "wb") as f:
                        await f.write(await r.read())
                return True
            except Exception as e:
                if attempt < retries - 1:
                    await asyncio.sleep(2 ** attempt)
                else:
                    logger.error(f"Failed to download {url}: {e}")
                    return False
        return False
    
    async def _download_attachments(self, session, attachments, prefix):
        """Download tất cả attachment"""
        paths = []
        for att in attachments:
            filename = f"{prefix}_{att['filename']}"
            filepath = self.temp_dir / filename
            ok = await self._download_file(session, att["url"], filepath)
            if ok:
                paths.append((filepath, att["filename"]))
        return paths
    
    def _cleanup_files(self, paths):
        """Xóa file tạm"""
        for filepath, _ in paths:
            try:
                os.remove(filepath)
            except:
                pass
    
    async def _create_dest_thread(self, session, dest_channel_id, thread_name, content, files=None):
        """Tạo thread mới (forum mode)"""
        url = f"{DISCORD_API}/channels/{dest_channel_id}/threads"
        form = aiohttp.FormData()
        
        payload = {
            "name": thread_name,
            "message": {"content": content or "\u200b"}
        }
        
        form.add_field("payload_json", json.dumps(payload), content_type="application/json")
        
        if files:
            for i, (filepath, filename) in enumerate(files):
                async with aiofiles.open(filepath, "rb") as f:
                    data = await f.read()
                form.add_field(f"files[{i}]", data, filename=filename)
        
        result = await post(session, url, bot_headers(self.bot_token), data=form)
        return result
    
    async def _send_message(self, session, channel_id, content, files=None):
        """Gửi tin nhắn"""
        url = f"{DISCORD_API}/channels/{channel_id}/messages"
        
        if files:
            # Gửi từng file riêng lẻ để tránh 413
            for idx, (filepath, filename) in enumerate(files):
                msg_content = (content or "\u200b") if idx == 0 else "\u200b"
                try:
                    form = aiohttp.FormData()
                    payload = {"content": msg_content}
                    form.add_field("payload_json", json.dumps(payload), content_type="application/json")
                    async with aiofiles.open(filepath, "rb") as f:
                        data = await f.read()
                    form.add_field("files[0]", data, filename=filename)
                    await post(session, url, bot_headers(self.bot_token), data=form)
                except Exception as e:
                    if "413" in str(e):
                        logger.warning(f"File too large for Discord, uploading to Mediafire...")
                        mf_link = self.mf_uploader.upload(filepath, filename)
                        if mf_link:
                            msg = f"{content}\n{mf_link}".strip() if content else mf_link
                            await post(session, url, bot_headers(self.bot_token), json={"content": msg})
                            logger.info(f"[Mediafire] {filename}")
                    else:
                        raise
                if idx < len(files) - 1:
                    await asyncio.sleep(0.5)
        else:
            if content:
                await post(session, url, bot_headers(self.bot_token), json={"content": content})
    
    async def _clone_forum_thread(self, session, src_thread, dest_channel_id, src_channel_id):
        """Clone 1 forum thread"""
        thread_id = src_thread["id"]
        thread_name = src_thread["name"]
        
        logger.info(f"[Thread] {thread_name} ({thread_id})")
        
        messages = await fetch_messages(session, self.user_token, thread_id)
        if not messages:
            logger.info("  No messages in thread")
            return
        
        thread_author_id = messages[0].get("author", {}).get("id", "")
        
        # Filter messages
        filtered = []
        for msg in messages:
            if self.message_filter.should_include(msg, thread_author_id):
                filtered.append(msg)
        
        if not filtered:
            logger.info("  No messages to clone after filtering")
            return
        
        logger.info(f"  Total: {len(messages)} | After filter: {len(filtered)}")
        
        # Create dest thread
        first_msg = filtered[0]
        content = self.message_filter.get_content(first_msg, thread_author_id)
        
        # Tải ảnh từ first message để làm thumbnail
        attachments = first_msg.get("attachments", [])
        image_files = []
        if attachments:
            image_attachments = [a for a in attachments if a.get("content_type", "").startswith("image/")]
            if image_attachments:
                image_files = await self._download_attachments(session, image_attachments, f"{thread_id}_thumb")
        
        try:
            result = await self._create_dest_thread(session, dest_channel_id, thread_name, content, image_files)
            dest_thread_id = result["id"]
            logger.info(f"  Created thread: {dest_thread_id}")
            
            self._cleanup_files(image_files)
            
            # Send remaining messages
            for idx, msg in enumerate(filtered[1:], 1):
            # Skip if already processed
            if self.state.is_processed(str(src_channel_id), str(dest_channel_id), thread_id, msg['id']):
                logger.info(f"  [{idx+1}/{len(filtered)}] ⊘ msg {msg['id']} (already processed)")
                continue
                content = self.message_filter.get_content(msg, thread_author_id)
                attachments = msg.get("attachments", [])
                
                files = []
                if attachments:
                    files = await self._download_attachments(session, attachments, f"{thread_id}_{msg['id']}")
                
                if content or files:
                    await self._send_message(session, dest_thread_id, content, files)
                    self.state.mark_processed(str(src_channel_id), str(dest_channel_id), thread_id, msg['id'])
                    logger.info(f"  [{idx+1}/{len(filtered)}] ✓ msg {msg['id']}")
                
                self._cleanup_files(files)
                await asyncio.sleep(self.delay_msg)
        
        except Exception as e:
            logger.error(f"  Error creating thread: {e}")
            self._cleanup_files(image_files)
    
    async def _clone_regular_channel(self, session, src_channel_id, dest_channel_id):
        """Clone regular channel (tất cả messages)"""
        logger.info(f"Cloning channel {src_channel_id}")
        
        messages = await fetch_messages(session, self.user_token, src_channel_id)
        if not messages:
            logger.info("No messages in channel")
            return
        
        logger.info(f"Total messages: {len(messages)}")
        
        for idx, msg in enumerate(messages, 1):
            content = self.message_filter.get_content(msg)
            attachments = msg.get("attachments", [])
            
            files = []
            if attachments:
                files = await self._download_attachments(session, attachments, f"msg_{msg['id']}")
            
            if content or files:
                try:
                    await self._send_message(session, dest_channel_id, content, files)
                    self.state.mark_processed(str(src_channel_id), str(dest_channel_id), "", msg['id'])
                    logger.info(f"  [{idx}/{len(messages)}] ✓ msg {msg['id']}")
                except Exception as e:
                    logger.error(f"  Error sending msg {msg['id']}: {e}")
            
            self._cleanup_files(files)
            await asyncio.sleep(self.delay_msg)
    
    async def clone(self, src_channel_id, dest_channel_id):
        # Show resume info
        processed = self.state.get_processed_count(str(src_channel_id), str(dest_channel_id))
        if processed > 0:
            logger.warning(f"Resume: {processed} messages already cloned")
        """Main clone function"""
        await self._select_mode()
        
        logger.info("=== Discord Cloner ===")
        logger.info(f"Source: {src_channel_id}")
        logger.info(f"Destination: {dest_channel_id}")
        logger.info(f"Mode: {self.mode}")
        logger.info(f"Started: {datetime.now().strftime('%H:%M:%S')}\n")
        
        async with aiohttp.ClientSession() as session:
            if self.mode == MessageFilter.FORUM_MODE:
                threads = await fetch_all_threads(session, self.user_token, src_channel_id)
                logger.info(f"Found {len(threads)} threads\n")
                
                for idx, thread in enumerate(threads, 1):
                    logger.info(f"--- Thread {idx}/{len(threads)} ---")
                    await self._clone_forum_thread(session, thread, dest_channel_id, src_channel_id)
                    await asyncio.sleep(self.delay_thread)
            
            else:  # CHANNEL_MODE
                await self._clone_regular_channel(session, src_channel_id, dest_channel_id)
        
        logger.info(f"\n=== Completed! {datetime.now().strftime('%H:%M:%S')} ===")


def main():
    """Entry point"""
    if len(sys.argv) != 3:
        print("Usage: python main.py <source_channel_id> <dest_channel_id>")
        sys.exit(1)
    
    src_channel = sys.argv[1]
    dest_channel = sys.argv[2]
    
    cloner = DiscordCloner()
    asyncio.run(cloner.clone(src_channel, dest_channel))


if __name__ == "__main__":
    main()
