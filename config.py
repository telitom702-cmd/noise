"""Bot configuration. Every value can be overridden with an environment variable."""
import os


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, "").strip() or default)
    except ValueError:
        return default


# =====================================
# TELEGRAM BOT CONFIGURATION
# =====================================
# Never hard-code the token: set TELEGRAM_BOT_TOKEN in the hosting dashboard.
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()

# =====================================
# WEB SERVICE CONFIGURATION
# =====================================
# Render / Railway / Fly provide PORT automatically.
PORT = _int("PORT", 10000)

# =====================================
# VIDEO CONFIGURATION
# =====================================
# Telegram Bot API cannot download files larger than 20 MB.
MAX_VIDEO_MB = min(_int("MAX_VIDEO_MB", 20), 20)
MAX_VIDEO_SECONDS = _int("MAX_VIDEO_SECONDS", 300)
# Telegram Bot API cannot upload files larger than 50 MB.
MAX_OUTPUT_MB = min(_int("MAX_OUTPUT_MB", 49), 49)

# =====================================
# PROCESSING CONFIGURATION
# =====================================
PROCESSING_TIMEOUT_SECONDS = _int("PROCESSING_TIMEOUT_SECONDS", 2700)
MAX_CONCURRENT_PROCESSING = max(1, _int("MAX_CONCURRENT_PROCESSING", 1))

# =====================================
# BOT MESSAGES
# =====================================
WELCOME_TEXT = (
    "ভিডিও পাঠান—আমি ব্যাকগ্রাউন্ড মিউজিক কমিয়ে "
    "কথা/কণ্ঠ যতটা সম্ভব রেখে ভিডিও ফেরত দেব।\n\n"
    f"সর্বোচ্চ ভিডিও সাইজ: {MAX_VIDEO_MB} MB\n"
    f"সর্বোচ্চ দৈর্ঘ্য: {MAX_VIDEO_SECONDS} সেকেন্ড।"
)

HELP_TEXT = (
    "ভিডিও বা ভিডিও ফাইল পাঠান।\n"
    "AI দিয়ে ব্যাকগ্রাউন্ড মিউজিক কমানোর চেষ্টা করা হবে।\n\n"
    f"সর্বোচ্চ সাইজ: {MAX_VIDEO_MB} MB\n"
    f"সর্বোচ্চ দৈর্ঘ্য: {MAX_VIDEO_SECONDS} সেকেন্ড।"
)
