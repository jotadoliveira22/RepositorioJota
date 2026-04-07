"""
Vercel FastAPI entrypoint.
Vercel's static detector requires FastAPI() to appear in this file.
"""
from fastapi import FastAPI
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import the real app (FastAPI() instance defined in backend/main.py)
from backend.main import app  # noqa: F401

# Fallback so this file always exposes a valid FastAPI() app
if not isinstance(app, FastAPI):
    app = FastAPI()
