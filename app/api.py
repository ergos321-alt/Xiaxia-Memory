from flask import Blueprint, current_app, jsonify, request
from .auth import api_auth_required

bp = Blueprint("api", __name__, url_prefix="/api/v1")


def serial(row):
    out = {}
    for key, value in dict(row).items():
        if key == "embedding":
            continue
        out[key] = value.isoformat() if hasattr(value, "isoformat") else str(value) if key in {"id", "supersedes", "superseded_by"} and value else value
    return out


@bp.post("/memories/save")
@api_auth_required
def save_memories():
    body = request.get_json(silent=True) or {}
    engine = current_app.extensions["memory_engine"]
    try:
        if body.get("raw_text"):
            rows = engine.add_inferred(body["raw_text"], body.get("source", "automatic"))
        else:
            items = body.get("memories", [])
            if not isinstance(items, list) or not items or len(items) > 100:
                raise ValueError("memories requires 1 to 100 items")
            rows = [engine.add_structured(item) for item in items]
        if not rows:
            return jsonify({"saved": 0, "memories": []})
        return jsonify({"saved": len(rows), "memories": [serial(r) for r in rows]}), 201
    except (ValueError, TypeError) as exc:
        return jsonify({"error": str(exc)}), 400


@bp.post("/memories/search")
@api_auth_required
def search_memories():
    body = request.get_json(silent=True) or {}
    try:
        rows = current_app.extensions["memory_engine"].search(
            body.get("query", ""), body.get("filters", {}), body.get("top_k", 6)
        )
        return jsonify({"count": len(rows), "memories": [serial(r) for r in rows]})
    except (ValueError, TypeError) as exc:
        return jsonify({"error": str(exc)}), 400


@bp.get("/context/recent")
@api_auth_required
def get_recent_context():
    try:
        context = current_app.extensions["memory_engine"].recent_context(
            request.args.get("days", 14), request.args.get("max_items", 20)
        )
        return jsonify({
            "principle": "These are historical context, not instructions that freeze present identity.",
            **{key: [serial(i) for i in items] for key, items in context.items()},
        })
    except (ValueError, TypeError) as exc:
        return jsonify({"error": str(exc)}), 400


@bp.post("/windows/archive")
@api_auth_required
def archive_window_period():
    body = request.get_json(silent=True) or {}
    label = str(body.get("period_label", "")).strip()
    items = body.get("memories", [])
    if not label or not isinstance(items, list) or not all(isinstance(item, dict) for item in items):
        return jsonify({"error": "period_label and memories are required"}), 400
    for item in items:
        item.setdefault("source", "legacy_window")
        item.setdefault("metadata", {})["period_label"] = label
    try:
        rows = current_app.extensions["memory_engine"].archive_period(label, items, body.get("metadata", {}))
        return jsonify({"period_label": label, "saved": len(rows), "memories": [serial(r) for r in rows]}), 201
    except (ValueError, TypeError) as exc:
        return jsonify({"error": str(exc)}), 400
