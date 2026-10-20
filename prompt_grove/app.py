from __future__ import annotations

import json
import os
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from flask import Flask, Response, jsonify, render_template, request, send_from_directory
from werkzeug.utils import secure_filename

BASE_DIR = Path(__file__).resolve().parent
INSTANCE_DIR = BASE_DIR / "instance"
UPLOAD_DIR = BASE_DIR / "static" / "uploads"
DB_PATH = INSTANCE_DIR / "prompts.db"
ALLOWED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".avif", ".bmp"}
MAX_IMAGE_BYTES = 12 * 1024 * 1024

INSTANCE_DIR.mkdir(exist_ok=True)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_IMAGE_BYTES + 1024 * 1024


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def connect_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    with connect_db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                parent_id INTEGER NULL REFERENCES categories(id) ON DELETE CASCADE,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_categories_parent ON categories(parent_id);
            CREATE TABLE IF NOT EXISTS prompts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL DEFAULT '',
                prompt_text TEXT NOT NULL,
                image_preview TEXT NOT NULL DEFAULT '',
                notes TEXT NOT NULL DEFAULT '',
                tags TEXT NOT NULL DEFAULT '',
                category_id INTEGER NULL REFERENCES categories(id) ON DELETE SET NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_prompts_category ON prompts(category_id);
            CREATE INDEX IF NOT EXISTS idx_prompts_updated ON prompts(updated_at);
            """
        )


def split_category_path(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        parts = [str(part).strip() for part in value]
    else:
        # A slash, >, or backslash separates levels: "Art / Anime / Cat_girl".
        parts = re.split(r"\s*(?:/|>|\\)\s*", str(value).strip())
    return [part for part in parts if part]


def ensure_category_path(conn: sqlite3.Connection, path: Any) -> int | None:
    parts = split_category_path(path)
    if not parts:
        return None
    parent_id: int | None = None
    for name in parts:
        row = conn.execute(
            "SELECT id FROM categories WHERE name = ? AND parent_id IS ? ORDER BY id LIMIT 1",
            (name, parent_id),
        ).fetchone()
        if row:
            parent_id = int(row["id"])
        else:
            cur = conn.execute(
                "INSERT INTO categories(name, parent_id, created_at) VALUES (?, ?, ?)",
                (name, parent_id, utc_now()),
            )
            parent_id = int(cur.lastrowid)
    return parent_id


def category_path_for_id(conn: sqlite3.Connection, category_id: int | None) -> str:
    if category_id is None:
        return ""
    names: list[str] = []
    current_id: int | None = category_id
    while current_id is not None:
        row = conn.execute("SELECT id, name, parent_id FROM categories WHERE id = ?", (current_id,)).fetchone()
        if not row:
            break
        names.append(str(row["name"]))
        current_id = row["parent_id"]
    return "/".join(reversed(names))


def prompt_to_dict(conn: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
    item = dict(row)
    item["category_path"] = category_path_for_id(conn, item.get("category_id"))
    item["tags_list"] = [tag.strip() for tag in item.get("tags", "").split(",") if tag.strip()]
    return item


def first_value(obj: dict[str, Any], *names: str, default: Any = "") -> Any:
    lowered = {str(k).lower(): v for k, v in obj.items()}
    for name in names:
        if name.lower() in lowered:
            return lowered[name.lower()]
    return default


def normalize_prompt_payload(obj: Any) -> dict[str, str]:
    if not isinstance(obj, dict):
        raise ValueError("Each prompt must be a JSON object.")
    category = first_value(obj, "Category", "Catagory", "category_path", "category", default="")
    prompt_text = first_value(obj, "Prompt", "Promt", "prompt_text", "prompt", default="")
    image_preview = first_value(obj, "image_preview", "imagePreview", "image", "image_path", default="")
    title = first_value(obj, "title", "name", default="")
    notes = first_value(obj, "notes", "description", default="")
    tags = first_value(obj, "tags", default="")
    if isinstance(tags, list):
        tags = ", ".join(str(tag) for tag in tags)
    if isinstance(category, list):
        category = "/".join(str(part) for part in category)
    if not isinstance(prompt_text, str):
        prompt_text = str(prompt_text or "")
    if not prompt_text.strip():
        raise ValueError("A prompt is missing its Prompt/Promt text.")
    return {
        "category": str(category or "").strip(),
        "prompt_text": prompt_text.strip(),
        "image_preview": str(image_preview or "").strip(),
        "title": str(title or "").strip(),
        "notes": str(notes or "").strip(),
        "tags": str(tags or "").strip(),
    }


def insert_prompt(conn: sqlite3.Connection, payload: dict[str, str], prompt_id: int | None = None) -> int:
    category_id = ensure_category_path(conn, payload.get("category", ""))
    title = payload.get("title", "").strip()
    prompt_text = payload["prompt_text"].strip()
    if not title:
        title = prompt_text.replace("\n", " ").strip()
        title = title[:52] + ("…" if len(title) > 52 else "")
    image_preview = payload.get("image_preview", "").strip()
    notes = payload.get("notes", "").strip()
    tags = payload.get("tags", "").strip()
    now = utc_now()
    if prompt_id is None:
        cur = conn.execute(
            """INSERT INTO prompts(title, prompt_text, image_preview, notes, tags, category_id, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (title, prompt_text, image_preview, notes, tags, category_id, now, now),
        )
        return int(cur.lastrowid)
    conn.execute(
        """UPDATE prompts SET title=?, prompt_text=?, image_preview=?, notes=?, tags=?, category_id=?, updated_at=?
           WHERE id=?""",
        (title, prompt_text, image_preview, notes, tags, category_id, now, prompt_id),
    )
    return prompt_id


def parse_json_import(raw: str) -> list[dict[str, str]]:
    source = raw.strip().lstrip("\ufeff")
    if not source:
        raise ValueError("Paste or choose a JSON file first.")
    try:
        parsed = json.loads(source)
    except json.JSONDecodeError:
        # Be forgiving with the semicolon separators shown in the original example.
        repaired = re.sub(r";(?=\s*\")", ",", source)
        repaired = re.sub(r";(?=\s*[}\]])", "", repaired)
        try:
            parsed = json.loads(repaired)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Could not read JSON (line {exc.lineno}, column {exc.colno}). Use an object or an array of objects.") from exc
    if isinstance(parsed, dict) and any(k.lower() in {"prompts", "items", "data"} for k in parsed):
        parsed = first_value(parsed, "prompts", "items", "data")
    if isinstance(parsed, dict):
        parsed = [parsed]
    if not isinstance(parsed, list):
        raise ValueError("The JSON root must be one prompt object or an array of prompt objects.")
    return [normalize_prompt_payload(obj) for obj in parsed]


def build_tree(conn: sqlite3.Connection) -> dict[str, Any]:
    category_rows = conn.execute("SELECT id, name, parent_id FROM categories ORDER BY name COLLATE NOCASE").fetchall()
    prompt_rows = conn.execute("SELECT * FROM prompts ORDER BY title COLLATE NOCASE, id").fetchall()
    nodes: dict[int, dict[str, Any]] = {}
    for row in category_rows:
        nodes[int(row["id"])] = {
            "id": int(row["id"]), "name": row["name"], "type": "category", "children": [], "count": 0,
            "parent_id": row["parent_id"],
        }
    root: dict[str, Any] = {"id": "root", "name": "Prompt Grove", "type": "root", "children": [], "count": 0}
    for row in category_rows:
        node = nodes[int(row["id"])]
        parent_id = row["parent_id"]
        if parent_id is None or int(parent_id) not in nodes:
            root["children"].append(node)
        else:
            nodes[int(parent_id)]["children"].append(node)
    uncat: dict[str, Any] | None = None
    for row in prompt_rows:
        prompt = prompt_to_dict(conn, row)
        pnode = {
            "id": f"p-{prompt['id']}", "prompt_id": prompt["id"], "name": prompt["title"],
            "type": "prompt", "preview": prompt["image_preview"], "prompt_text": prompt["prompt_text"],
            "category_path": prompt["category_path"], "children": [], "count": 1,
        }
        cat_id = prompt.get("category_id")
        if cat_id is not None and int(cat_id) in nodes:
            nodes[int(cat_id)]["children"].append(pnode)
        else:
            if uncat is None:
                uncat = {"id": "uncategorized", "name": "Uncategorized", "type": "category", "children": [], "count": 0}
                root["children"].append(uncat)
            uncat["children"].append(pnode)

    def count_and_prune(node: dict[str, Any]) -> int:
        if node.get("type") == "prompt":
            node.pop("parent_id", None)
            node["count"] = 1
            return 1
        kept: list[dict[str, Any]] = []
        total = 0
        for child in node.get("children", []):
            count = count_and_prune(child)
            if child.get("type") == "prompt" or count > 0:
                kept.append(child)
                total += count
        node["children"] = kept
        node["count"] = total
        node.pop("parent_id", None)
        return total

    count_and_prune(root)
    return root


init_db()


@app.get("/")
def index() -> str:
    return render_template("index.html")


@app.get("/api/prompts")
def api_prompts():
    query = request.args.get("q", "").strip().lower()
    category = request.args.get("category", "").strip()
    with connect_db() as conn:
        rows = conn.execute("SELECT * FROM prompts ORDER BY updated_at DESC, id DESC").fetchall()
        prompts = [prompt_to_dict(conn, row) for row in rows]
    if query:
        prompts = [p for p in prompts if query in " ".join([p["title"], p["prompt_text"], p["category_path"], p["notes"], p["tags"]]).lower()]
    if category:
        prompts = [p for p in prompts if p["category_path"] == category or p["category_path"].startswith(category + "/")]
    return jsonify(prompts)


@app.get("/api/tree")
def api_tree():
    with connect_db() as conn:
        return jsonify(build_tree(conn))


@app.post("/api/prompts")
def api_create_prompt():
    data = request.get_json(silent=True) or {}
    try:
        payload = normalize_prompt_payload(data)
        with connect_db() as conn:
            prompt_id = insert_prompt(conn, payload)
            row = conn.execute("SELECT * FROM prompts WHERE id=?", (prompt_id,)).fetchone()
            result = prompt_to_dict(conn, row)
        return jsonify(result), 201
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@app.put("/api/prompts/<int:prompt_id>")
def api_update_prompt(prompt_id: int):
    data = request.get_json(silent=True) or {}
    try:
        payload = normalize_prompt_payload(data)
        with connect_db() as conn:
            exists = conn.execute("SELECT id FROM prompts WHERE id=?", (prompt_id,)).fetchone()
            if not exists:
                return jsonify({"error": "Prompt not found."}), 404
            insert_prompt(conn, payload, prompt_id)
            row = conn.execute("SELECT * FROM prompts WHERE id=?", (prompt_id,)).fetchone()
            result = prompt_to_dict(conn, row)
        return jsonify(result)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@app.delete("/api/prompts/<int:prompt_id>")
def api_delete_prompt(prompt_id: int):
    with connect_db() as conn:
        cur = conn.execute("DELETE FROM prompts WHERE id=?", (prompt_id,))
        if cur.rowcount == 0:
            return jsonify({"error": "Prompt not found."}), 404
    return jsonify({"ok": True})


@app.post("/api/import")
def api_import():
    body = request.get_json(silent=True)
    if isinstance(body, dict) and isinstance(body.get("json"), str):
        raw = body["json"]
    elif request.data:
        raw = request.data.decode("utf-8", errors="replace")
    else:
        raw = ""
    try:
        items = parse_json_import(raw)
        with connect_db() as conn:
            for item in items:
                insert_prompt(conn, item)
        return jsonify({"imported": len(items), "message": f"Imported {len(items)} prompt{'s' if len(items) != 1 else ''}."}), 201
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@app.get("/api/export")
def api_export():
    with connect_db() as conn:
        rows = conn.execute("SELECT * FROM prompts ORDER BY category_id, title COLLATE NOCASE, id").fetchall()
        exported = []
        for row in rows:
            p = prompt_to_dict(conn, row)
            obj: dict[str, Any] = {
                "Catagory": p["category_path"],
                "Promt": p["prompt_text"],
                "image_preview": p["image_preview"],
            }
            if p["title"]:
                obj["title"] = p["title"]
            if p["notes"]:
                obj["notes"] = p["notes"]
            if p["tags"]:
                obj["tags"] = [tag.strip() for tag in p["tags"].split(",") if tag.strip()]
            exported.append(obj)
    response = Response(json.dumps(exported, ensure_ascii=False, indent=2), mimetype="application/json")
    response.headers["Content-Disposition"] = "attachment; filename=prompt-grove-export.json"
    return response


@app.post("/api/upload-image")
def api_upload_image():
    file = request.files.get("image")
    if not file or not file.filename:
        return jsonify({"error": "Choose an image file first."}), 400
    filename = secure_filename(file.filename)
    extension = Path(filename).suffix.lower()
    if extension not in ALLOWED_IMAGE_EXTENSIONS:
        return jsonify({"error": "Use PNG, JPG, WEBP, GIF, AVIF, or BMP images."}), 400
    data = file.read(MAX_IMAGE_BYTES + 1)
    if not data:
        return jsonify({"error": "The selected image is empty."}), 400
    if len(data) > MAX_IMAGE_BYTES:
        return jsonify({"error": "Images must be 12 MB or smaller."}), 413
    unique_name = f"{uuid.uuid4().hex}{extension}"
    (UPLOAD_DIR / unique_name).write_bytes(data)
    return jsonify({"path": f"/static/uploads/{unique_name}", "name": filename}), 201


@app.errorhandler(413)
def too_large(_error):
    return jsonify({"error": "The upload is too large. Images must be 12 MB or smaller."}), 413


if __name__ == "__main__":
    # Local-only by default; set PORT if needed.
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", "5000")), debug=True)
