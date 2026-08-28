import os


class Config:
    DATABASE_URL = os.getenv("DATABASE_URL", "")
    MEMORY_API_TOKEN = os.getenv("MEMORY_API_TOKEN", "")
    ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")
    SECRET_KEY = os.getenv("FLASK_SECRET_KEY", "dev-only-change-me")
    QWEN_API_KEY = os.getenv("QWEN_API_KEY", "")
    QWEN_BASE_URL = os.getenv("QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
    QWEN_CHAT_MODEL = os.getenv("QWEN_CHAT_MODEL", "qwen-flash")
    QWEN_EMBEDDING_MODEL = os.getenv("QWEN_EMBEDDING_MODEL", "text-embedding-v4")
    EMBEDDING_DIMENSIONS = int(os.getenv("EMBEDDING_DIMENSIONS", "1024"))
    MEM0_COLLECTION = os.getenv("MEM0_COLLECTION", "xiaxia_mem0_memories")
    MEM0_USER_ID = os.getenv("MEM0_USER_ID", "xiaxia_shared_life")
    MEM0_HISTORY_DB_PATH = os.getenv("MEM0_HISTORY_DB_PATH", "/tmp/xiaxia_mem0_history.db")
    DB_POOL_MIN = int(os.getenv("DB_POOL_MIN", "1"))
    DB_POOL_MAX = int(os.getenv("DB_POOL_MAX", "1"))
    MEM0_DB_POOL_MIN = int(os.getenv("MEM0_DB_POOL_MIN", "1"))
    MEM0_DB_POOL_MAX = int(os.getenv("MEM0_DB_POOL_MAX", "2"))
    MAX_RAW_TEXT_CHARS = int(os.getenv("MAX_RAW_TEXT_CHARS", "24000"))
    MAX_CONTENT_LENGTH = 2 * 1024 * 1024
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SECURE = True
    SESSION_COOKIE_SAMESITE = "Lax"
