# Prompt Grove

A local-first prompt hosting/library web app built with Python, Flask, HTML, CSS, and vanilla JavaScript. Save prompt text with related image references, copy prompts, organize categories and nested subcategories, import/export JSON, and inspect the full hierarchy as a tree graph.

## Features

- **Prompt library:** search, sort, edit, delete, and one-click copy prompt text.
- **Image previews:** reference images from a URL/path or upload a local image (PNG, JPG, WEBP, GIF, AVIF, BMP; 12 MB max).
- **Category trees:** use a category path like `Character art / Anime / Cat_girl`; each slash creates a subcategory.
- **Tree graph:** visualize category/subcategory branches and prompt nodes. Select a prompt node to edit it.
- **JSON import/export:** import one JSON object or an array. Both the original key spellings (`Catagory`, `Promt`) and corrected spellings (`Category`, `Prompt`) are accepted. Export uses the original field names to match the example format.
- **Local persistence:** prompt data is stored in `instance/prompts.db`; uploaded images are saved in `static/uploads/`.

## Quick start

Requires Python 3.10+.

1. Unzip the project.
2. Open a terminal in the `prompt_grove` folder.
3. Create and activate a virtual environment (recommended):

   ```bash
   python -m venv .venv
   ```

   Windows PowerShell:

   ```powershell
   .\.venv\Scripts\Activate.ps1
   ```

   macOS/Linux:

   ```bash
   source .venv/bin/activate
   ```

4. Install dependencies and start the app:

   ```bash
   pip install -r requirements.txt
   python app.py
   ```

5. Open **http://127.0.0.1:5000** in your browser.

The app is configured for local use and binds to `127.0.0.1` by default. Keep it local unless you add suitable authentication and deployment hardening.

## JSON format

The app accepts your original format (standard JSON requires commas between properties):

```json
{
  "Catagory": "Cat_girl",
  "Promt": "masterpiece, 1girl, solo, catgirl",
  "image_preview": "/static/uploads/reference.png"
}
```

Correct spellings are accepted too:

```json
{
  "Category": "Character art / Anime / Cat_girl",
  "Prompt": "masterpiece, 1girl, solo, catgirl",
  "image_preview": "https://example.com/reference.png",
  "title": "Soft-lit cat girl",
  "notes": "Optional notes",
  "tags": ["character", "anime"]
}
```

A JSON array can contain multiple prompt objects. The importer is also forgiving of the semicolon separators in the sample syntax, although standard commas are recommended. The `image_preview` value should be a browser-accessible URL or path; uploading an image from the editor stores it in this project's `static/uploads/` directory.

## Data files

- `instance/prompts.db` — created automatically at first launch; contains prompts and category hierarchy.
- `static/uploads/` — uploaded reference images.
- `examples/prompts.example.json` — small import-ready example.

Back up both the database and uploaded image folder to preserve your library. This is intended as a personal/local web app, not a public multi-user service.
