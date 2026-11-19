import os
import json
import uuid
import threading
from concurrent.futures import ThreadPoolExecutor
import pandas as pd
from flask import Flask, render_template, request, jsonify
from core.writer import process_article_job

app = Flask(__name__)

SITES_FILE = "sites.json"
JOBS_LOCK = threading.Lock()
JOBS = {}  # row_id -> {"status": str, "state": "idle|running|done|error", "post_url": str, "error": str}
EXECUTOR = ThreadPoolExecutor(max_workers=2)


def load_sites() -> list[dict]:
    if not os.path.exists(SITES_FILE):
        return []
    with open(SITES_FILE, "r", encoding="utf-8") as f:
        return json.load(f).get("sites", [])


def save_sites(sites: list[dict]) -> None:
    with open(SITES_FILE, "w", encoding="utf-8") as f:
        json.dump({"sites": sites}, f, indent=2)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/sites", methods=["GET", "POST"])
def api_sites():
    if request.method == "POST":
        data = request.get_json(force=True)
        sites = data.get("sites", [])
        save_sites(sites)
        return jsonify({"ok": True, "sites": sites})
    return jsonify({"sites": load_sites()})


@app.route("/api/import", methods=["POST"])
def api_import():
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    file = request.files["file"]
    filename = (file.filename or "").lower()

    try:
        if filename.endswith(".csv"):
            df = pd.read_csv(file)
        elif filename.endswith((".xlsx", ".xls")):
            df = pd.read_excel(file)
        else:
            return jsonify({"error": "Please upload a .csv, .xlsx, or .xls file"}), 400
    except Exception as e:
        return jsonify({"error": f"Could not parse spreadsheet: {e}"}), 400

    df = df.fillna("")
    col_map = {}
    for col in df.columns:
        norm = str(col).strip().lower()
        if norm in ("main keyword", "main_keyword", "keyword", "primary keyword"):
            col_map["main_keyword"] = col
        elif norm in ("title", "article title", "h1"):
            col_map["title"] = col
        elif norm in ("keywords", "secondary keywords", "nlp keywords", "tags"):
            col_map["keywords"] = col
        elif norm in ("outline", "outline notes", "headings", "notes"):
            col_map["outline"] = col

    if "main_keyword" not in col_map:
        # Fallback: treat first column as main_keyword
        col_map["main_keyword"] = df.columns[0]

    rows = []
    for _, r in df.iterrows():
        kw = str(r[col_map["main_keyword"]]).strip()
        if not kw:
            continue
        rows.append({
            "id": str(uuid.uuid4())[:8],
            "main_keyword": kw,
            "title": str(r[col_map["title"]]).strip() if "title" in col_map else "",
            "keywords": str(r[col_map["keywords"]]).strip() if "keywords" in col_map else "",
            "outline": str(r[col_map["outline"]]).strip() if "outline" in col_map else "",
        })

    return jsonify({"rows": rows})


def _run_single_row(row: dict, settings: dict, site: dict):
    row_id = row["id"]

    def status_cb(msg: str):
        with JOBS_LOCK:
            if row_id in JOBS:
                JOBS[row_id]["status"] = msg

    with JOBS_LOCK:
        JOBS[row_id] = {
            "status": "Starting...",
            "state": "running",
            "post_url": "",
            "error": "",
        }

    try:
        result = process_article_job(row, settings, site, status_cb=status_cb)
        with JOBS_LOCK:
            JOBS[row_id] = {
                "status": f"Published ({result['status']})",
                "state": "done",
                "post_url": result.get("post_url", ""),
                "error": "",
            }
    except Exception as e:
        with JOBS_LOCK:
            JOBS[row_id] = {
                "status": "Failed",
                "state": "error",
                "post_url": "",
                "error": str(e),
            }


@app.route("/api/run", methods=["POST"])
def api_run():
    data = request.get_json(force=True)
    rows = data.get("rows", [])
    settings = data.get("settings", {})
    site_index = int(data.get("site_index", 0))

    sites = load_sites()
    if not sites or site_index >= len(sites):
        return jsonify({"error": "No valid LocalWP site selected in sites.json"}), 400

    site = sites[site_index]
    queued = 0

    for row in rows:
        if not row.get("main_keyword", "").strip():
            continue
        row_id = row.get("id") or str(uuid.uuid4())[:8]
        row["id"] = row_id
        with JOBS_LOCK:
            JOBS[row_id] = {
                "status": "Queued",
                "state": "running",
                "post_url": "",
                "error": "",
            }
        EXECUTOR.submit(_run_single_row, row, settings, site)
        queued += 1

    return jsonify({"ok": True, "queued": queued})


@app.route("/api/jobs", methods=["GET"])
def api_jobs():
    with JOBS_LOCK:
        return jsonify({"jobs": JOBS})


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5050, debug=True)
