# Iwanatestssomething
Clone channel forum discord
# Discord Forum Cloner - Setup Guide

## 1. Cài dependencies
```
pip install -r requirements.txt
```

## 2. Tạo file config.json
Tạo file `config.json` với nội dung:
```json
{
  "user_token": "YOUR_USER_TOKEN_HERE",
  "bot_token": "YOUR_BOT_TOKEN_HERE",
  "delay_between_messages": 1.5,
  "delay_between_threads": 3.0,
  "temp_dir": "temp"
}
```

## 3. Tạo file state.json
Tạo file `state.json` với nội dung:
```json
{}
```

## 4. Tạo file .gitignore
Tạo file `.gitignore` với nội dung:
```
config.json
state.json
temp/
__pycache__/
*.pyc
.env
```

## 5. Chạy
```
python main.py <source_channel_id> <dest_channel_id>
```

---

## Lấy User Token
1. Mở Discord trên trình duyệt
2. F12 → Console
3. Dán: `webpackChunkdiscord_app.push([[Math.random()],{},e=>{m=[];for(let c in e.c)m.push(e.c[c])}]);m.filter(m=>m?.exports?.default?.getToken!==void 0).map(m=>m.exports.default.getToken())`
4. Copy token hiện ra

## Lấy Channel ID
Discord → Cài đặt → Chế độ nhà phát triển → Bật
Chuột phải vào channel → Copy ID
