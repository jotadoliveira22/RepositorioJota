"""
Vercel entry point — exposes the FastAPI app as an ASGI handler.
Vercel's @vercel/python builder picks up `app` from this file.
"""
import sys
import os

# Ensure the repo root is on the path so `backend.*` imports resolve.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.main import app  # noqa: F401  (Vercel needs `app` in scope)
