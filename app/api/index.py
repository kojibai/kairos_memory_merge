# Vercel Function entrypoint (ASGI)
# This must export `app`

from app.main import app  # <-- your FastAPI instance lives here
