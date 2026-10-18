# Noise Remover Telegram Bot

Telegram-এ ভিডিও পাঠালে AI (Demucs) দিয়ে ব্যাকগ্রাউন্ড মিউজিক কমিয়ে ভিডিও ফেরত দেয়।
Web Service হিসেবে চলে: `/health` endpoint সহ HTTP পোর্ট খোলা রাখে।

## Environment variables
| নাম | দরকার | বিবরণ |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | হ্যাঁ | @BotFather থেকে পাওয়া টোকেন |
| `PORT` | না | প্ল্যাটফর্ম নিজে দেয় (ডিফল্ট 10000) |
| `MAX_VIDEO_MB` / `MAX_VIDEO_SECONDS` | না | ডিফল্ট 20 MB / 300 সেকেন্ড |

## Render-এ deploy
1. কোড GitHub-এ push করুন।
2. Render → New → Web Service → repo বেছে নিন (Runtime: Docker)।
3. Environment-এ `TELEGRAM_BOT_TOKEN` দিন।
4. Health Check Path: `/health`
5. কমপক্ষে ২ GB RAM-এর প্ল্যান নিন।

Free প্ল্যানে সার্ভিস ১৫ মিনিট নিষ্ক্রিয় থাকলে ঘুমিয়ে যায়, তখন বট উত্তর দেবে না।
UptimeRobot দিয়ে `/health` প্রতি ৫ মিনিটে ping করুন, অথবা পেইড প্ল্যান নিন।

## লোকালি চালানো
```bash
docker build -t noise-remover-bot .
docker run -d -p 10000:10000 -e TELEGRAM_BOT_TOKEN=xxx --name noise-remover-bot noise-remover-bot
```

## টেস্ট
```bash
python -m unittest discover -s tests -t .
```

## মনে রাখুন
- একই টোকেনে একসাথে দুটি instance চালাবেন না (Conflict error হবে)।
- Telegram Bot API-তে ডাউনলোড সীমা 20 MB, আপলোড সীমা 50 MB।
