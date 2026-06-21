"""
Discord Forum Channel Cloner
Usage: python main.py <source_channel_id> <dest_channel_id>
"""

import asyncio
import json
import os
import sys
import aiohttp
import aiofiles
from pathlib import Path
from datetime import datetime

with open("config.json", "r") as f:
    config = json.load(f)

USER_TOKEN = config["user_token"]
BOT_TOKEN = config["bot_token"]
DELAY_MSG = config.get("delay_between_messages", 1.5)
DELAY_THREAD = config.get("delay_between_threads", 3.0)
TEMP_DIR = Path(config.get("temp_dir", "temp"))
TEMP_DIR.mkdir(exist_ok=True)

STATE_FILE = Path("state.json")
DISCORD_API = "https://discord.com/api/v10"

def load_state():
    if STATE_FILE.exists():
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    return {}

def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

def user_headers():
    return {
        "Authorization": USER_TOKEN,
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "X-Discord-Locale": "en-US",
    }

def bot_headers():
    return {"Authorization": f"Bot {BOT_TOKEN}"}

async def get(session, url, headers):
    async with session.get(url, headers=headers) as r:
        if r.status == 429:
            data = await r.json()
            retry = data.get("retry_after", 5)
            print(f"  [Rate limit] Retry after {retry}s")
            await asyncio.sleep(retry)
            return await get(session, url, headers)
        r.raise_for_status()
        return await r.json()

async def post(session, url, headers, **kwargs):
    async with session.post(url, headers=headers, **kwargs) as r:
        if r.status == 429:
            data = await r.json()
            retry = data.get("retry_after", 5)
            print(f"  [Rate limit] Retry after {retry}s")
            await asyncio.sleep(retry)
            return await post(session, url, headers, **kwargs)
        r.raise_for_status()
        return await r.json()

async def get_guild_id(session, channel_id):
    url = f"{DISCORD_API}/channels/{channel_id}"
    data = await get(session, url, user_headers())
    return data["guild_id"]

async def fetch_all_threads(session, channel_id):
    """Lấy tất cả threads (active + archived) qua endpoint public."""
    threads = []
    before = None

    # Archived public threads
    while True:
        url = f"{DISCORD_API}/channels/{channel_id}/threads/archived/public?limit=100"
        if before:
            url += f"&before={before}"
        try:
            data = await get(session, url, user_headers())
            batch = data.get("threads", [])
            threads.extend(batch)
            if not data.get("has_more", False) or not batch:
                break
            before = batch[-1]["id"]
            await asyncio.sleep(0.5)
        except Exception as e:
            print(f"  [!] Lỗi lấy archived threads: {e}")
            break

    # Archived private threads (nếu có quyền)
    before = None
    while True:
        url = f"{DISCORD_API}/channels/{channel_id}/threads/archived/private?limit=100"
        if before:
            url += f"&before={before}"
        try:
            data = await get(session, url, user_headers())
            batch = data.get("threads", [])
            threads.extend(batch)
            if not data.get("has_more", False) or not batch:
                break
            before = batch[-1]["id"]
            await asyncio.sleep(0.5)
        except Exception:
            break  # Không có quyền, bỏ qua

    return threads

async def fetch_messages(session, thread_id):
    """Lấy toàn bộ tin nhắn trong thread, từ cũ đến mới."""
    messages = []
    before = None
    while True:
        url = f"{DISCORD_API}/channels/{thread_id}/messages?limit=100"
        if before:
            url += f"&before={before}"
        batch = await get(session, url, user_headers())
        if not batch:
            break
        messages.extend(batch)
        before = batch[-1]["id"]
        if len(batch) < 100:
            break
        await asyncio.sleep(0.5)
    messages.reverse()
    return messages

async def download_attachments(session, attachments, thread_id, msg_id):
    paths = []
    for att in attachments:
        filename = f"{thread_id}_{msg_id}_{att['filename']}"
        filepath = TEMP_DIR / filename
        async with session.get(att["url"]) as r:
            r.raise_for_status()
            async with aiofiles.open(filepath, "wb") as f:
                await f.write(await r.read())
        paths.append((filepath, att["filename"]))
    return paths

def cleanup_files(paths):
    for filepath, _ in paths:
        try:
            os.remove(filepath)
        except Exception:
            pass

async def create_dest_thread(session, dest_channel_id, thread_name, first_message_content, files):
    url = f"{DISCORD_API}/channels/{dest_channel_id}/threads"
    form = aiohttp.FormData()
    payload = {
        "name": thread_name,
        "message": {"content": first_message_content or "\u200b"}
    }
    form.add_field("payload_json", json.dumps(payload), content_type="application/json")
    for i, (filepath, filename) in enumerate(files):
        async with aiofiles.open(filepath, "rb") as f:
            data = await f.read()
        form.add_field(f"files[{i}]", data, filename=filename)
    result = await post(session, url, bot_headers(), data=form)
    return result

async def send_message(session, thread_id, content, files):
    url = f"{DISCORD_API}/channels/{thread_id}/messages"
    if files:
        form = aiohttp.FormData()
        payload = {"content": content or "\u200b"}
        form.add_field("payload_json", json.dumps(payload), content_type="application/json")
        for i, (filepath, filename) in enumerate(files):
            async with aiofiles.open(filepath, "rb") as f:
                data = await f.read()
            form.add_field(f"files[{i}]", data, filename=filename)
        await post(session, url, bot_headers(), data=form)
    else:
        if not content:
            return
        payload = {"content": content}
        await post(session, url, bot_headers(), json=payload)

async def clone_thread(session, src_thread, dest_channel_id, state, state_key):
    thread_id = src_thread["id"]
    thread_name = src_thread["name"]

    print(f"\n[Thread] {thread_name} ({thread_id})")

    messages = await fetch_messages(session, thread_id)
    if not messages:
        print("  Không có tin nhắn, bỏ qua.")
        return

    done_msgs = state.get(state_key, {}).get(thread_id, {}).get("done_messages", [])
    dest_thread_id = state.get(state_key, {}).get(thread_id, {}).get("dest_thread_id")

    pending = [m for m in messages if m["id"] not in done_msgs]
    if not pending:
        print("  Đã clone xong thread này trước đó.")
        return

    print(f"  Tổng: {len(messages)} tin | Còn lại: {len(pending)} tin")

    for i, msg in enumerate(pending):
        content = msg.get("content", "")
        attachments = msg.get("attachments", [])
        embeds = msg.get("embeds", [])

        files = []
        if attachments:
            files = await download_attachments(session, attachments, thread_id, msg["id"])

        if embeds and not files:
            for embed in embeds:
                if embed.get("url"):
                    content = (content + "\n" + embed["url"]).strip()

        try:
            if i == 0 and not dest_thread_id:
                result = await create_dest_thread(session, dest_channel_id, thread_name, content, files)
                dest_thread_id = result["id"]
                print(f"  Tạo thread đích: {dest_thread_id}")
                if state_key not in state:
                    state[state_key] = {}
                if thread_id not in state[state_key]:
                    state[state_key][thread_id] = {}
                state[state_key][thread_id]["dest_thread_id"] = dest_thread_id
            else:
                await send_message(session, dest_thread_id, content, files)

            cleanup_files(files)

            if state_key not in state:
                state[state_key] = {}
            if thread_id not in state[state_key]:
                state[state_key][thread_id] = {"done_messages": []}
            if "done_messages" not in state[state_key][thread_id]:
                state[state_key][thread_id]["done_messages"] = []
            state[state_key][thread_id]["done_messages"].append(msg["id"])
            save_state(state)

            print(f"  [{i+1}/{len(pending)}] v msg {msg['id']}")
            await asyncio.sleep(DELAY_MSG)

        except Exception as e:
            cleanup_files(files)
            print(f"  [!] Loi msg {msg['id']}: {e}")
            await asyncio.sleep(2)

async def main(src_channel_id, dest_channel_id):
    state = load_state()
    state_key = f"{src_channel_id}->{dest_channel_id}"

    print(f"=== Discord Forum Cloner ===")
    print(f"Nguon : {src_channel_id}")
    print(f"Dich  : {dest_channel_id}")
    print(f"Bat dau: {datetime.now().strftime('%H:%M:%S')}\n")

    async with aiohttp.ClientSession() as session:
        print("Dang lay danh sach threads...")
        all_threads = await fetch_all_threads(session, src_channel_id)
        print(f"Tim thay {len(all_threads)} threads\n")

        if not all_threads:
            print("[!] Khong tim thay thread nao. Kiem tra lai channel ID va quyen truy cap.")
            return

        for idx, thread in enumerate(all_threads):
            print(f"--- Thread {idx+1}/{len(all_threads)} ---")
            await clone_thread(session, thread, dest_channel_id, state, state_key)
            await asyncio.sleep(DELAY_THREAD)

    print(f"\n=== Hoan thanh! {datetime.now().strftime('%H:%M:%S')} ===")

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python main.py <source_channel_id> <dest_channel_id>")
        sys.exit(1)

    src = sys.argv[1]
    dest = sys.argv[2]
    asyncio.run(main(src, dest))
