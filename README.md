# Discord Channel/Forum Cloner

Clone messages từ Discord channels (regular hoặc forum) sang channel khác, kèm files, ảnh.

## Features

✓ Clone forum threads (với chế độ lọc chủ thread)  
✓ Clone regular channels (tất cả messages)  
✓ Tự động download ảnh/file đính kèm  
✓ Fallback lên Mediafire khi file > 25MB  
✓ Resume tự động (không bao giờ trùng lặp)  
✓ Rate limit handling  
✓ Logging đầy đủ  

## Requirements

- Python 3.8+
- Discord account (selfbot)
- Discord bot token (for destination server)
- Mediafire account (optional, for large files)

## Installation

```bash
git clone https://github.com/vyhuynh24092021-debug/Iwanatestssomething.git
cd Iwanatestssomething
pip install -r requirements.txt --break-system-packages
```

## Setup

### 1. Get User Token (Selfbot)

**Desktop:**
1. Open Discord in browser
2. Press F12 → Console
3. Paste:
```javascript
webpackChunkdiscord_app.push([[Math.random()],{},e=>{m=[];for(let c in e.c)m.push(e.c[c])}]);m.filter(m=>m?.exports?.default?.getToken!==void 0).map(m=>m.exports.default.getToken())
```
4. Copy token that appears

### 2. Get Bot Token

1. Go to https://discord.com/developers/applications
2. New Application → set name
3. Bot → Reset Token → Copy
4. Enable "Message Content Intent"
5. OAuth2 → URL Generator → select `bot` and permissions
6. Copy generated URL → paste in browser → invite bot

### 3. Get Channel IDs

1. Enable Developer Mode in Discord
2. Right-click channel → Copy ID

### 4. Configure

```bash
cp config.example.json config.json
nano config.json
```

Fill in:
- `user_token`: your Discord account token
- `bot_token`: bot token
- `mediafire_email` / `mediafire_password`: (optional, for large files)

### 5. Run

```bash
python main.py <source_channel_id> <dest_channel_id>
```

You'll be prompted to choose mode:
```
1. Forum Channel (threads)
2. Regular Channel (messages)
```

## Modes

### Forum Channel Mode
- Clones threads từ forum source
- Filters: only thread author messages + files
- Customizable via `filter.py`

### Regular Channel Mode
- Clones ALL messages từ channel
- No filtering
- Preserves message order

## Customization

### Message Filtering

Edit `filter.py` để tùy chỉnh điều kiện lọc:

```python
class MessageFilter:
    def should_include(self, msg, thread_author_id=None):
        """Override this để thay đổi logic lọc"""
        # your custom logic
```

### Delays & Config

Trong `config.json`:
- `delay_between_messages`: delay giữa tin nhắn (seconds)
- `delay_between_threads`: delay giữa threads (seconds)
- `temp_dir`: folder chứa file tạm

## Troubleshooting

### "Expecting ',' delimiter" JSON error
→ Check `config.json` syntax, missing commas?

### Rate limit errors
→ Increase `delay_between_messages` / `delay_between_threads`

### Mediafire upload fails
→ Check email/password, may have 2FA enabled

### "No module named 'mediafire'"
```bash
pip install mediafire --break-system-packages
```

## Legal

⚠️ Selfbots violate Discord ToS - use at own risk  
✓ Educational purpose only  
✓ Minecraft/game map files (fair use)  

## License

MIT
