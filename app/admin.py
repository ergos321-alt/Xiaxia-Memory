import hmac
from flask import Blueprint, current_app, flash, redirect, render_template, request, session, url_for
from .auth import admin_auth_required

bp = Blueprint("admin", __name__, url_prefix="/admin")


@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        expected = current_app.config.get("ADMIN_PASSWORD", "")
        if expected and hmac.compare_digest(request.form.get("password", ""), expected):
            session["memory_admin"] = True
            return redirect(url_for("admin.index"))
        flash("密码不正确")
    return render_template("login.html")


@bp.get("/logout")
def logout():
    session.clear()
    return redirect(url_for("admin.login"))


@bp.get("/")
@admin_auth_required
def index():
    q = request.args.get("q", "").strip()
    category = request.args.get("category", "")
    status = request.args.get("status", "")
    date_from = request.args.get("from", "")
    date_to = request.args.get("to", "")
    rows = current_app.extensions["memory_engine"].list_admin({"q": q, "category": category, "status": status, "from": date_from, "to": date_to}, 100)
    return render_template("index.html", memories=rows)


@bp.route("/memory/<uuid:memory_id>/edit", methods=["GET", "POST"])
@admin_auth_required
def edit(memory_id):
    engine = current_app.extensions["memory_engine"]
    if request.method == "POST":
        engine.update(memory_id, request.form["memory_text"], {
            "category": request.form["category"], "subtype": request.form.get("subtype") or None,
            "importance": int(request.form["importance"]), "occurred_at": request.form["occurred_at"],
            "status": request.form["status"], "source": request.form["source"],
        }, actor="viewer")
        flash("Memory 与 embedding 已通过 Mem0 同步更新")
        return redirect(url_for("admin.index"))
    row = engine.get(memory_id)
    if not row:
        return "Not found", 404
    return render_template("edit.html", memory=row)


@bp.post("/memory/<uuid:memory_id>/delete")
@admin_auth_required
def delete(memory_id):
    current_app.extensions["memory_engine"].delete(memory_id, actor="viewer")
    flash("Memory 已从 Mem0 删除，Xiaxia ledger 保留审计墓碑")
    return redirect(url_for("admin.index"))


@bp.get("/memory/<uuid:memory_id>/history")
@admin_auth_required
def history(memory_id):
    rows = current_app.extensions["memory_engine"].history(memory_id)
    return render_template("history.html", memories=rows)
