from pathlib import Path
from dotenv import load_dotenv
import os

BASE_DIR = Path(__file__).resolve().parents[1]
load_dotenv(BASE_DIR / ".env")

DB_HOST = os.getenv("DB_HOST", "127.0.0.1")
DB_PORT = int(os.getenv("DB_PORT", "3306"))
DB_USER = os.getenv("DB_USER", "gpstracker")
DB_PASSWORD = os.getenv("DB_PASSWORD", "gpstracker123")
DB_NAME = os.getenv("DB_NAME", "ocr_ktp_npwp")

UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", str(BASE_DIR / "uploads"))).resolve()
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "10"))
WORKER_SLEEP_SECONDS = int(os.getenv("WORKER_SLEEP_SECONDS", "3"))

# OCR runtime settings
TESSERACT_LANG = os.getenv("TESSERACT_LANG", "ind+eng")
PADDLE_LANG = os.getenv("PADDLE_LANG", "en")
PYTHONUNBUFFERED = os.getenv("PYTHONUNBUFFERED", "1")

ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp", ".pdf"}
