# Waifu Playground — Phase 1 (LM Studio)

A local Python web UI inspired by the supplied reference. Phase 1 supports **LM Studio's OpenAI-compatible Local Server only**. Ollama and raw `llama-server` adapters are intentionally left for later phases.

## Features

- Screenshot-inspired scene, translucent chat panel, navigation rail, settings drawer, and character inspector.
- Select the roleplay model from LM Studio's `/v1/models` list, or type a model ID.
- Custom character name, persona, RP system prompt, temperature, and editable state-JSON template.
- Each RP turn requests one JSON object with `reply` and `state`; the current state is passed into the next turn to help continuity.
- A separate emotion-analysis call runs after each RP reply. It can use the same model or a different model available through the same LM Studio server.
- Inspect/download the latest state and inspect emotion metrics or raw output.
- Connection settings are stored in browser local storage. Conversations are kept in the current browser tab session and are not written to a database.

## Requirements

- Python 3.10+
- LM Studio with a model loaded and its Local Server started

## Run

```bash
cd waifu_playground
python -m venv .venv
```

Activate the virtual environment, then install and start the app:

**Windows PowerShell**

```powershell
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app:app --host 127.0.0.1 --port 8000
```

**macOS / Linux**

```bash
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app:app --host 127.0.0.1 --port 8000
```

Open <http://127.0.0.1:8000>. In LM Studio, load a chat/instruct model, start the Local Server, and keep its OpenAI-compatible base URL at `http://localhost:1234/v1` unless you changed the port. Click the gear, click **Refresh models**, choose a roleplay model, and save. Leave the emotion model blank to use the same model, or enter a second served model ID.

## RP response contract

The RP system prompt requests this shape on every turn:

```json
{
  "reply": "The character's in-character message.",
  "state": {
    "mood": "happy",
    "emotion_intensity": 65,
    "affection": 24,
    "energy": 76,
    "relationship": "getting to know each other",
    "inner_thought": "She is pleased the user came back.",
    "actions": ["smiles"],
    "memories": []
  }
}
```

This is a starter schema because the original request did not contain the intended JSON format. You can edit the template in Settings. The `reply` key is displayed as dialogue; the `state` object is stored and supplied back to the roleplay model on the next turn. If the RP model ignores the JSON contract, the UI reports that and the raw output is available in the inspector.

## Emotion sub-agent output

After each RP response, a second completion is asked to return `primary_emotion`, `secondary_emotions`, `valence` (-100 to 100), `arousal` (0 to 100), `confidence` (0 to 100), `signals`, and `note`. These are estimates based on the current user message, character reply, and updated state—not ground truth. A failure in the emotion call does not discard a valid RP reply.

## API endpoints

- `GET /api/health` — app status
- `POST /api/models` — lists models from the configured LM Studio server
- `POST /api/chat` — roleplay call followed by emotion tracking

## Troubleshooting

- If model discovery fails, check LM Studio's Local Server is running and that the base URL includes `/v1`.
- If you see HTTP 401, enter the API key configured in LM Studio (otherwise leave it blank).
- Some models are poor at strict JSON. Try a model with good instruction following; use the inspector's Raw output tab to debug the output contract.
- A different emotion model may increase GPU/RAM use because it needs to be loaded/served and adds a second completion per turn.
