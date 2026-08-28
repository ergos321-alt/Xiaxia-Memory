from flask import Flask, jsonify
from .config import Config
from .db import Database
from .domain_repository import DomainRepository
from .memory_engine import MemoryEngine


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.from_object(Config)
    if test_config:
        app.config.update(test_config)
    db = app.config.get("DB_INSTANCE") or Database(app.config["DATABASE_URL"], app.config["DB_POOL_MIN"], app.config["DB_POOL_MAX"])
    if app.config.get("OPEN_DB_ON_START", True):
        db.open()
    app.extensions["db"] = db
    repository = app.config.get("REPOSITORY_INSTANCE") or DomainRepository(db)
    app.extensions["memory_engine"] = app.config.get("ENGINE_INSTANCE") or MemoryEngine(repository, app.config)
    from .api import bp as api_bp
    from .admin import bp as admin_bp
    app.register_blueprint(api_bp); app.register_blueprint(admin_bp)

    @app.get("/health")
    def health():
        return jsonify({"status": "ok", "service": "xiaxia-memory-v1"})

    @app.errorhandler(413)
    def too_large(_):
        return jsonify({"error": "payload too large"}), 413

    return app
