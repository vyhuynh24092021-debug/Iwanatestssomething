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
import warnings, logging
logging.getLogger("mediafire").setLevel(logging.ERROR)
try:
    from mediafire.client import MediaFireClient
    HAS_MEDIAFIRE = True
except ImportError:
    HAS_MEDIAFIRE = False

with open("config.json", "r") as f:
    config = json.load(f)

USER_TOKEN = config["user_token"]
BOT_TOKEN = config["bot_token"]
MF_EMAIL = config.get("mediafire_email", "")
MF_PASSWORD = config.get("mediafire_password", "")
DELAY_MSG = config.get("delay_between_messages", 1.0)
DELAY_THREAD = config.get("delay_between_threads", 2.0)
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
    """Lay tat ca threads, paginate bang archive_timestamp."""
    threads = []
    before = None
    while True:
        url = f"{DISCORD_API}/channels/{channel_id}/threads/archived/public?limit=100"
        if before:
            url += f"&before={before}"
        try:
            data = await get(session, url, user_headers())
            batch = data.get("threads", [])
            threads.extend(batch)
            print(f"  Da lay {len(threads)} threads...", end="\r")
            if not data.get("has_more", False) or not batch:
                break
            ts = batch[-1].get("thread_metadata", {}).get("archive_timestamp", "")
            if not ts:
                break
            # Fix: doi +00:00 thanh Z
            before = ts.replace("+00:00", "Z")
            await asyncio.sleep(0.5)
        except Exception as e:
            print(f"\n  [!] Loi lay threads: {e}")
            break
    return threads

async def fetch_messages(session, thread_id):
    """Lay toan bo tin nhan trong thread, tu cu den moi."""
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

async def download_file(session, url, filepath, retries=3):
    """Download 1 file voi retry."""
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
                print(f"\n  [!] Khong tai duoc file: {e}")
                return False

async def download_attachments(session, attachments, thread_id, msg_id):
    paths = []
    for att in attachments:
        filename = f"{thread_id}_{msg_id}_{att['filename']}"
        filepath = TEMP_DIR / filename
        ok = await download_file(session, att["url"], filepath)
        if ok:
            paths.append((filepath, att["filename"]))
    return paths

def cleanup_files(paths):
    for filepath, _ in paths:
        try:
            os.remove(filepath)
        except Exception:
            pass

def upload_to_mediafire(filepath, filename):
    """Upload file len Mediafire, tra ve link download."""
    if not HAS_MEDIAFIRE:
        print("  [!] Chua cai mediafire SDK. Chay: pip install mediafire --break-system-packages")
        return None
    if not MF_EMAIL or not MF_PASSWORD:
        print("  [!] Chua co mediafire_email/mediafire_password trong config.json")
        return None
    try:
        from mediafire.client import MediaFireClient, File
        client = MediaFireClient()
        client.login(email=MF_EMAIL, password=MF_PASSWORD, app_id="42511")
        dest = f"mf:/{filename}"
        client.upload_file(str(filepath), dest)
        # Lay link tu folder root
        for item in client.get_folder_contents_iter("mf:/"):
            if isinstance(item, File) and item.get("filename") == filename:
                qk = item.get("quickkey")
                if qk:
                    return f"https://www.mediafire.com/file/{qk}/{filename}/file"
        # Fallback neu khong tim thay
        return f"https://www.mediafire.com/?{filename}"
    except Exception as e:
        print(f"  [!] Mediafire upload loi: {e}")
        return None

async def create_dest_thread(session, dest_channel_id, thread_name, content, files):
    """Tao thread moi. Neu co file, tao thread truoc roi gui file sau."""
    url = f"{DISCORD_API}/channels/{dest_channel_id}/threads"
    form = aiohttp.FormData()
    payload = {
        "name": thread_name,
        "message": {"content": content or "\u200b"}
    }
    form.add_field("payload_json", json.dumps(payload), content_type="application/json")
    result = await post(session, url, bot_headers(), data=form)
    return result

async def send_file(session, thread_id, content, filepath, filename):
    """Gui 1 file. Fallback Mediafire neu 413."""
    url = f"{DISCORD_API}/channels/{thread_id}/messages"
    try:
        form = aiohttp.FormData()
        payload = {"content": content or "\u200b"}
        form.add_field("payload_json", json.dumps(payload), content_type="application/json")
        async with aiofiles.open(filepath, "rb") as f:
            data = await f.read()
        form.add_field("files[0]", data, filename=filename)
        await post(session, url, bot_headers(), data=form)
    except Exception as e:
        if "413" in str(e):
            print(f"  [!] File qua lon cho Discord, upload Mediafire...")
            mf_link = upload_to_mediafire(filepath, filename)
            if mf_link:
                msg = f"{content}\n{mf_link}".strip() if content else mf_link
                await post(session, url, bot_headers(), json={"content": msg})
                print(f"  [Mediafire] {filename} -> {mf_link}")
            else:
                print(f"  [!] Khong upload duoc Mediafire, bo qua file nay")
        else:
            raise

async def send_message(session, thread_id, content, files):
    """Gui tin nhan + file vao thread dich, tung file 1."""
    url = f"{DISCORD_API}/channels/{thread_id}/messages"
    if files:
        # Gui tung file 1 de tranh 413
        for idx, (filepath, filename) in enumerate(files):
            msg_content = (content or "\u200b") if idx == 0 else "\u200b"
            await send_file(session, thread_id, msg_content, filepath, filename)
            if idx < len(files) - 1:
                await asyncio.sleep(0.5)
    else:
        if not content:
            return
        await post(session, url, bot_headers(), json={"content": content})

async def clone_thread(session, src_thread, dest_channel_id, state, state_key):
    thread_id = src_thread["id"]
    thread_name = src_thread["name"]
    print(f"\n[Thread] {thread_name} ({thread_id})")

    messages = await fetch_messages(session, thread_id)
    if not messages:
        print("  Khong co tin nhan, bo qua.")
        return

    thread_author_id = messages[0].get("author", {}).get("id", "")
    done_msgs = state.get(state_key, {}).get(thread_id, {}).get("done_messages", [])
    dest_thread_id = state.get(state_key, {}).get(thread_id, {}).get("dest_thread_id")

    pending = [m for m in messages if m["id"] not in done_msgs]
    if not pending:
        print("  Da clone xong thread nay truoc do.")
        return

    # Bo loc: chi lay tin cua chu thread
    filtered = []
    for i, m in enumerate(pending):
        author_id = m.get("author", {}).get("id", "")
        is_author = author_id == thread_author_id
        has_files = bool(m.get("attachments"))
        if is_author or has_files:
            filtered.append((i, m))

    print(f"  Tong: {len(messages)} tin | Sau loc: {len(filtered)} tin")

    for idx, (i, msg) in enumerate(filtered):
        author_id = msg.get("author", {}).get("id", "")
        is_author = author_id == thread_author_id
        # Neu la chu thread: lay ca content + file
        # Neu nguoi khac: chi lay file, bo text
        content = msg.get("content", "") if is_author else ""
        attachments = msg.get("attachments", [])
        embeds = msg.get("embeds", [])

        files = []
        if attachments:
            files = await download_attachments(session, attachments, thread_id, msg["id"])

        if embeds and not files and not content:
            for embed in embeds:
                if embed.get("url"):
                    content = (content + "\n" + embed["url"]).strip()

        if not content and not files:
            if state_key not in state: state[state_key] = {}
            if thread_id not in state[state_key]: state[state_key][thread_id] = {"done_messages": []}
            state[state_key][thread_id]["done_messages"].append(msg["id"])
            save_state(state)
            continue

        try:
            if not dest_thread_id:
                # Tao thread truoc (khong kem file de tranh 413)
                result = await create_dest_thread(session, dest_channel_id, thread_name, content if not files else "")
                dest_thread_id = result["id"]
                print(f"  Tao thread dich: {dest_thread_id}")
                if state_key not in state: state[state_key] = {}
                if thread_id not in state[state_key]: state[state_key][thread_id] = {}
                state[state_key][thread_id]["dest_thread_id"] = dest_thread_id
                # Gui file sau neu co
                if files:
                    await send_message(session, dest_thread_id, content, files)
            else:
                await send_message(session, dest_thread_id, content, files)

            cleanup_files(files)

            if state_key not in state: state[state_key] = {}
            if thread_id not in state[state_key]: state[state_key][thread_id] = {"done_messages": []}
            if "done_messages" not in state[state_key][thread_id]: state[state_key][thread_id]["done_messages"] = []
            state[state_key][thread_id]["done_messages"].append(msg["id"])
            save_state(state)

            print(f"  [{idx+1}/{len(filtered)}] v msg {msg['id']}")
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
        print(f"\nTim thay {len(all_threads)} threads\n")

        if not all_threads:
            print("[!] Khong tim thay thread nao.")
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
    asyncio.run(main(sys.argv[1], sys.argv[2]))
