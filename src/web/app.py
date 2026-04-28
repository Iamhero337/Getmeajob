"""
Job Application Dashboard — Flask web UI.
Run via: python main.py dashboard
"""
import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, PROJECT_ROOT)

from flask import Flask, jsonify, request, render_template, send_file, abort
from sqlalchemy import desc, or_
from src.database.tracker import Tracker, Job

app = Flask(__name__, template_folder="templates")
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0

tracker = Tracker()


def _resolve_path(path: str) -> str:
    """Return absolute path regardless of whether DB stored relative or absolute."""
    if not path:
        return ""
    if os.path.isabs(path):
        return path
    return os.path.join(PROJECT_ROOT, path)


def _job_to_dict(j: Job) -> dict:
    cl_pdf = _resolve_path(j.cover_letter_path or "")
    cl_txt = cl_pdf.replace("_cover.pdf", "_cover.txt") if cl_pdf else ""
    resume = _resolve_path(j.resume_path or "")
    return {
        "id": j.job_id,
        "board": j.board,
        "title": j.title or "",
        "company": j.company or "",
        "location": j.location or "",
        "is_remote": bool(j.is_remote),
        "url": j.url or "",
        "score": j.score or 0,
        "status": j.status or "found",
        "company_type": j.company_type or "unknown",
        "found_at": j.found_at.strftime("%Y-%m-%d %H:%M") if j.found_at else "",
        "applied_at": j.applied_at.strftime("%Y-%m-%d %H:%M") if j.applied_at else "",
        "resume_path": resume if os.path.exists(resume) else "",
        "cover_letter_pdf": cl_pdf if os.path.exists(cl_pdf) else "",
        "cover_letter_txt": cl_txt if os.path.exists(cl_txt) else "",
        "notes": j.notes or "",
    }


@app.route("/")
def dashboard():
    return render_template("dashboard.html")


@app.route("/api/stats")
def stats():
    return jsonify(tracker.stats())


@app.route("/api/jobs")
def jobs():
    status_filter = request.args.get("status", "all")
    search = request.args.get("search", "").strip()
    page = max(1, int(request.args.get("page", 1)))
    per_page = min(100, int(request.args.get("per_page", 50)))

    with tracker.session() as s:
        q = s.query(Job)
        if status_filter != "all":
            q = q.filter(Job.status == status_filter)
        if search:
            pat = f"%{search}%"
            q = q.filter(or_(Job.title.ilike(pat), Job.company.ilike(pat)))
        q = q.order_by(desc(Job.score), desc(Job.found_at))
        total = q.count()
        rows = q.offset((page - 1) * per_page).limit(per_page).all()
        result = [_job_to_dict(j) for j in rows]

    return jsonify({"jobs": result, "total": total, "page": page, "per_page": per_page})


@app.route("/api/jobs/status", methods=["POST"])
def update_status():
    data = request.json or {}
    job_id = data.get("job_id", "")
    new_status = data.get("status", "")
    notes = data.get("notes", "")
    if not job_id or new_status not in ("found", "queued", "applied", "skipped", "failed"):
        return jsonify({"error": "invalid params"}), 400
    tracker.update_status(job_id, new_status, notes=notes)
    return jsonify({"ok": True})


@app.route("/files/<path:filepath>")
def serve_file(filepath):
    full = os.path.abspath(os.path.join(PROJECT_ROOT, filepath))
    if not full.startswith(PROJECT_ROOT):
        abort(403)
    if not os.path.exists(full):
        abort(404)
    return send_file(full)


@app.route("/files/abs")
def serve_abs():
    """Serve a file by absolute path (passed as query param)."""
    path = request.args.get("path", "")
    if not path:
        abort(400)
    full = os.path.abspath(path)
    if not full.startswith(PROJECT_ROOT):
        abort(403)
    if not os.path.exists(full):
        abort(404)
    return send_file(full)


def run_dashboard(host="127.0.0.1", port=5050, debug=False):
    print(f"\n  Dashboard: http://{host}:{port}\n")
    app.run(host=host, port=port, debug=debug)
