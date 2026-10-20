---
name: comfyui-local-workflow
description: Run the project's ComfyUI API workflow and return generated images.
---

For image generation, run `python comfy_bionic.py --prompt "..."`. It submits `Anima_API.json` to `COMFYUI_URL` (default `http://127.0.0.1:8188`), waits, then downloads images to `./generated`. Optional: `--negative "..."`, `--url URL`. Keep workflow settings unchanged unless asked. Requires the workflow's models and custom nodes, including `UnloadAllModels`. Report errors exactly; don't claim success without output.
