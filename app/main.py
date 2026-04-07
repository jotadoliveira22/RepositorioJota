"""
Vercel FastAPI entrypoint.
Vercel's FastAPI preset looks for `app = FastAPI()` in app/main.py.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.main import app  # noqa: F401
