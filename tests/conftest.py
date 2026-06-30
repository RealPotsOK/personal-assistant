from __future__ import annotations

import os

os.environ.setdefault("AI_API_KEY", "test-internal-ai-key-that-is-long-enough")
os.environ.setdefault("PA_CLIENT_TOKEN", "test-pc-client-token-that-is-long-enough")
os.environ.setdefault("DATABASE_PATH", "/tmp/personal-assistant-tests.sqlite")
