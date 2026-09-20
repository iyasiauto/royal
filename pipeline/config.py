import os
from pathlib import Path
from dotenv import load_dotenv

# Base Directory Paths
ROYAL_DIR = Path(r"C:\Users\ninja\Downloads\X Colab Automation\Royal")
APIS_DIR = Path(r"C:\Users\ninja\Downloads\X Colab Automation\apis")
PIPELINE_DIR = ROYAL_DIR / "pipeline"

# Load environment variables
load_dotenv(ROYAL_DIR / ".env")
load_dotenv(APIS_DIR / "openrouter.env")
load_dotenv(APIS_DIR / "ai33pro.env")
load_dotenv(APIS_DIR / "openlux.env")
load_dotenv(APIS_DIR / "serper.env")

# API Keys
SUBTITLE_API_KEY = os.getenv("SUBTITLE_API_KEY", "")
VOICEOVER_API_KEY = os.getenv("VOICEOVER_API_KEY", "")
VOICEOVER_VOICE_ID = os.getenv("VOICEOVER_VOICE_ID", "elevenlabs_KoQQbl9zjAdLgKZjm8Ol")
THUMBNAIL_API_KEY = os.getenv("THUMBNAIL_API_KEY", "")

# Video Defaults
VIDEO_WIDTH = 1920
VIDEO_HEIGHT = 1080
VIDEO_FPS = 30
TRANSITION_DURATION = 0.5  # seconds
IMAGE_CLIP_DURATION = 5.0  # seconds per image clip

# Font & Subtitle Styling (Playbook section 8 & standard 1080p YouTube style)
SUBTITLE_FONT = "Arial"
SUBTITLE_FONT_SIZE = 54
COLOR_PRIMARY = "&H00FFFFFF"      # White
COLOR_HIGHLIGHT = "&H0000FFFF"    # Bright Yellow
COLOR_OUTLINE = "&H00000000"      # Black
COLOR_BACK = "&H80000000"         # Semi-transparent black

# Keyword entities for B-roll image searching
ROYAL_ENTITIES = [
    "King Charles III", "Prince William", "Queen Camilla", "Princess Diana",
    "Kate Middleton", "Princess Anne", "Clarence House", "Highgrove House",
    "Ray Mill House", "Balmoral Castle", "Buckingham Palace", "Kensington Palace",
    "Crown Jewels", "Windsor Castle"
]
