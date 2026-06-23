"""
Discord API wrapper - HTTP utilities
"""

import asyncio
import logging

logger = logging.getLogger("discord_api")

DISCORD_API = "https://discord.com/api/v10"


def user_headers(token):
    """Selfbot user headers"""
    return {
        "Authorization": token,
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "X-Discord-Locale": "en-US",
    }


def bot_headers(token):
    """Bot token headers"""
    return {"Authorization": f"Bot {token}"}


async def get(session, url, headers, retries=3):
    """GET request với retry rate limit"""
    for attempt in range(retries):
        try:
            async with session.get(url, headers=headers) as r:
                if r.status == 429:
                    data = await r.json()
                    retry_after = float(data.get("retry_after", 5))
                    logger.warning(f"Rate limited, retry after {retry_after}s")
                    await asyncio.sleep(retry_after)
                    continue
                r.raise_for_status()
                return await r.json()
        except Exception as e:
            if attempt < retries - 1:
                await asyncio.sleep(2 ** attempt)
            else:
                raise
    return None


async def post(session, url, headers, retries=3, **kwargs):
    """POST request với retry rate limit"""
    for attempt in range(retries):
        try:
            async with session.post(url, headers=headers, **kwargs) as r:
                if r.status == 429:
                    data = await r.json()
                    retry_after = float(data.get("retry_after", 5))
                    logger.warning(f"Rate limited, retry after {retry_after}s")
                    await asyncio.sleep(retry_after)
                    continue
                r.raise_for_status()
                return await r.json()
        except Exception as e:
            if attempt < retries - 1:
                await asyncio.sleep(2 ** attempt)
            else:
                raise
    return None


async def fetch_messages(session, user_token, channel_id):
    """Lấy toàn bộ tin nhắn từ channel, từ cũ đến mới"""
    messages = []
    before = None
    
    while True:
        url = f"{DISCORD_API}/channels/{channel_id}/messages?limit=100"
        if before:
            url += f"&before={before}"
        
        batch = await get(session, url, user_headers(user_token))
        if not batch:
            break
        
        messages.extend(batch)
        if len(batch) < 100:
            break
        
        before = batch[-1]["id"]
        await asyncio.sleep(0.5)
    
    messages.reverse()
    return messages


async def fetch_all_threads(session, user_token, channel_id):
    """Lấy tất cả threads (archived) trong forum channel"""
    threads = []
    before = None
    
    while True:
        url = f"{DISCORD_API}/channels/{channel_id}/threads/archived/public?limit=100"
        if before:
            url += f"&before={before}"
        
        try:
            data = await get(session, url, user_headers(user_token))
            batch = data.get("threads", []) if data else []
            threads.extend(batch)
            
            if not data or not data.get("has_more", False) or not batch:
                break
            
            ts = batch[-1].get("thread_metadata", {}).get("archive_timestamp", "")
            if ts:
                before = ts.replace("+00:00", "Z")
            else:
                break
            
            await asyncio.sleep(0.5)
        except Exception as e:
            logger.error(f"Error fetching threads: {e}")
            break
    
    return threads
