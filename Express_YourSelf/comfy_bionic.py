#!/usr/bin/env python3
"""Submit a ComfyUI API workflow, apply the supplied prompt, and download images."""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import uuid
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, quote
from urllib.request import Request, urlopen

HERE = Path(__file__).resolve().parent
DEFAULT_WORKFLOW = HERE / "Anima_API.json"


def request_json(url: str, *, method: str = "GET", payload: dict | None = None, timeout: float = 30) -> dict:
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {"Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = Request(url, data=data, headers=headers, method=method)
    with urlopen(req, timeout=timeout) as response:
        raw = response.read()
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Expected JSON from {url}, got a non-JSON response.") from exc
    if not isinstance(parsed, dict):
        raise RuntimeError(f"Unexpected response format from {url}.")
    return parsed


def is_node_link(value: object, workflow: dict) -> bool:
    return (
        isinstance(value, (list, tuple))
        and len(value) >= 2
        and isinstance(value[0], str)
        and value[0] in workflow
        and isinstance(value[1], int)
    )


def linked_node_ids(value: object, workflow: dict) -> list[str]:
    """Return node IDs referenced by an API-format input value."""
    if is_node_link(value, workflow):
        return [value[0]]
    if isinstance(value, (list, tuple)):
        found: list[str] = []
        for item in value:
            found.extend(linked_node_ids(item, workflow))
        return found
    return []


def is_text_encoder(node: dict) -> bool:
    class_type = str(node.get("class_type", "")).lower()
    inputs = node.get("inputs", {})
    return isinstance(inputs, dict) and isinstance(inputs.get("text"), str) and (
        "textencode" in class_type or "text encode" in str(node.get("_meta", {}).get("title", "")).lower()
    )


def upstream_text_encoders(workflow: dict, root_node_id: str) -> set[str]:
    """Find text encoder nodes upstream of a sampler input, through wrapper nodes too."""
    found: set[str] = set()
    seen: set[str] = set()
    pending = [root_node_id]
    while pending:
        node_id = pending.pop()
        if node_id in seen or node_id not in workflow:
            continue
        seen.add(node_id)
        node = workflow[node_id]
        if not isinstance(node, dict):
            continue
        if is_text_encoder(node):
            found.add(node_id)
            # Stop at the text encoder: its CLIP input is not another prompt.
            continue
        inputs = node.get("inputs", {})
        if isinstance(inputs, dict):
            for value in inputs.values():
                pending.extend(linked_node_ids(value, workflow))
    return found


def resolve_prompt_node(workflow: dict, branch: str) -> str:
    """Resolve the prompt node by following the sampler's positive/negative graph path."""
    samplers = []
    for node_id, node in workflow.items():
        if not isinstance(node, dict):
            continue
        class_type = str(node.get("class_type", "")).lower()
        inputs = node.get("inputs", {})
        if "sampler" in class_type and isinstance(inputs, dict) and branch in inputs:
            samplers.append((node_id, inputs[branch]))
    if not samplers:
        raise RuntimeError(f"Could not find a sampler node with a '{branch}' input.")

    candidates: set[str] = set()
    for _, value in samplers:
        for root_id in linked_node_ids(value, workflow):
            candidates.update(upstream_text_encoders(workflow, root_id))

    if not candidates:
        raise RuntimeError(f"Could not trace the sampler's '{branch}' input back to a text-encoder node.")
    if len(candidates) == 1:
        return next(iter(candidates))

    # If the graph intentionally has multiple encoders, prefer a node explicitly titled
    # for the requested branch. Otherwise stop instead of silently editing the wrong node.
    needle = "positive" if branch == "positive" else "negative"
    titled = {
        node_id for node_id in candidates
        if needle in str(workflow[node_id].get("_meta", {}).get("title", "")).lower()
    }
    if len(titled) == 1:
        return next(iter(titled))
    choices = ", ".join(sorted(candidates))
    raise RuntimeError(
        f"Found multiple possible '{branch}' prompt nodes ({choices}). "
        f"Specify --{branch}-node NODE_ID to choose one."
    )


def validate_prompt_node(workflow: dict, node_id: str, role: str) -> None:
    node = workflow.get(node_id)
    if not isinstance(node, dict) or not isinstance(node.get("inputs"), dict):
        raise RuntimeError(f"{role} prompt node {node_id!r} does not exist or has no inputs.")
    if not isinstance(node["inputs"].get("text"), str):
        raise RuntimeError(f"{role} prompt node {node_id!r} has no editable text input.")


def safe_filename(name: str) -> str:
    name = Path(name).name
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._")
    return name or "comfyui_output.png"


def download_image(base_url: str, image_info: dict, output_dir: Path, timeout: float) -> Path:
    params = {
        "filename": str(image_info.get("filename", "")),
        "subfolder": str(image_info.get("subfolder", "")),
        "type": str(image_info.get("type", "output")),
    }
    if not params["filename"]:
        raise RuntimeError("ComfyUI reported an image without a filename.")
    url = f"{base_url}/view?{urlencode(params)}"
    req = Request(url, headers={"Accept": "image/*"})
    with urlopen(req, timeout=timeout) as response:
        content = response.read()
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / safe_filename(params["filename"])
    if target.exists():
        stem, suffix = target.stem, target.suffix
        n = 2
        while (output_dir / f"{stem}_{n}{suffix}").exists():
            n += 1
        target = output_dir / f"{stem}_{n}{suffix}"
    target.write_bytes(content)
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=os.environ.get("COMFYUI_URL", "http://127.0.0.1:8188"),
                        help="ComfyUI base URL (default: COMFYUI_URL or http://127.0.0.1:8188)")
    parser.add_argument("--workflow", type=Path, default=DEFAULT_WORKFLOW,
                        help="API-format workflow JSON (default: Anima_API.json beside this script)")
    prompts = parser.add_mutually_exclusive_group()
    prompts.add_argument("--prompt", help="Exact positive prompt to send to ComfyUI")
    prompts.add_argument("--prompt-file", type=Path, help="Read the exact positive prompt from a UTF-8 text file")
    parser.add_argument("--use-workflow-prompt", action="store_true",
                        help="Explicitly keep the workflow's built-in prompt instead of supplying one")
    parser.add_argument("--negative", help="Optional replacement negative prompt")
    parser.add_argument("--positive-node", help="Override auto-detected positive text-encoder node ID")
    parser.add_argument("--negative-node", help="Override auto-detected negative text-encoder node ID")
    parser.add_argument("--inspect", action="store_true", help="Show detected prompt node IDs and exit")
    parser.add_argument("--dry-run", action="store_true", help="Apply prompt edits and optionally dump workflow, but do not contact ComfyUI")
    parser.add_argument("--dump-workflow", type=Path,
                        help="Save the exact edited API workflow JSON that will be submitted")
    parser.add_argument("--timeout", type=float, default=1800, help="Maximum generation wait in seconds (default: 1800)")
    parser.add_argument("--poll-interval", type=float, default=2.0, help="Seconds between status checks (default: 2)")
    parser.add_argument("--output-dir", type=Path, default=Path("generated"),
                        help="Where to download images (default: ./generated)")
    parser.add_argument("--no-download", action="store_true", help="Only report ComfyUI output filenames; don't download")
    args = parser.parse_args()

    base_url = args.url.rstrip("/")
    if args.timeout <= 0 or args.poll_interval <= 0:
        parser.error("--timeout and --poll-interval must be positive")
    if not args.workflow.is_file():
        print(f"ERROR: workflow file not found: {args.workflow}", file=sys.stderr)
        return 2
    if args.use_workflow_prompt and (args.prompt is not None or args.prompt_file is not None):
        parser.error("Use either --use-workflow-prompt or --prompt/--prompt-file, not both")
    if not args.inspect and not args.use_workflow_prompt and args.prompt is None and args.prompt_file is None:
        parser.error("No prompt supplied. Pass --prompt TEXT or --prompt-file FILE. The built-in prompt is used only with --use-workflow-prompt.")

    try:
        workflow = json.loads(args.workflow.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: cannot read workflow JSON: {exc}", file=sys.stderr)
        return 2
    if not isinstance(workflow, dict) or not workflow:
        print("ERROR: workflow must be a non-empty API-format JSON object.", file=sys.stderr)
        return 2

    try:
        positive_id = args.positive_node or resolve_prompt_node(workflow, "positive")
        validate_prompt_node(workflow, positive_id, "Positive")
        negative_id = args.negative_node or resolve_prompt_node(workflow, "negative")
        validate_prompt_node(workflow, negative_id, "Negative")
    except RuntimeError as exc:
        print(f"ERROR: prompt-node detection failed: {exc}", file=sys.stderr)
        return 2

    if args.inspect:
        print(f"Positive prompt: node {positive_id} ({workflow[positive_id].get('class_type')}; title={workflow[positive_id].get('_meta', {}).get('title', '')!r})")
        print(f"Negative prompt: node {negative_id} ({workflow[negative_id].get('class_type')}; title={workflow[negative_id].get('_meta', {}).get('title', '')!r})")
        sampler_nodes = [node_id for node_id, node in workflow.items()
                         if isinstance(node, dict) and "sampler" in str(node.get("class_type", "")).lower()]
        print("Sampler node(s): " + (", ".join(sampler_nodes) if sampler_nodes else "not found"))
        return 0

    try:
        if args.prompt_file is not None:
            prompt_text = args.prompt_file.read_text(encoding="utf-8")
        elif args.prompt is not None:
            prompt_text = args.prompt
        else:
            prompt_text = None
    except OSError as exc:
        print(f"ERROR: cannot read prompt file: {exc}", file=sys.stderr)
        return 2

    if prompt_text is not None:
        if not prompt_text.strip():
            print("ERROR: prompt is empty; refusing to submit an unintended workflow.", file=sys.stderr)
            return 2
        workflow[positive_id]["inputs"]["text"] = prompt_text
        if workflow[positive_id]["inputs"]["text"] != prompt_text:
            print("ERROR: positive prompt injection verification failed.", file=sys.stderr)
            return 2
        print(f"Positive prompt applied to node {positive_id} ({workflow[positive_id].get('_meta', {}).get('title', '')}).")
        print(f"Prompt length: {len(prompt_text)} characters; preview: {prompt_text[:240]!r}")
    else:
        print(f"Using workflow's built-in positive prompt from node {positive_id} by explicit request.")

    if args.negative is not None:
        if not args.negative.strip():
            print("ERROR: negative prompt is empty.", file=sys.stderr)
            return 2
        workflow[negative_id]["inputs"]["text"] = args.negative
        print(f"Negative prompt applied to node {negative_id} ({workflow[negative_id].get('_meta', {}).get('title', '')}).")

    if args.dump_workflow is not None:
        try:
            args.dump_workflow.parent.mkdir(parents=True, exist_ok=True)
            args.dump_workflow.write_text(json.dumps(workflow, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        except OSError as exc:
            print(f"ERROR: cannot save edited workflow: {exc}", file=sys.stderr)
            return 2
        print(f"Edited workflow saved: {args.dump_workflow.resolve()}")

    if args.dry_run:
        print("Dry run complete; no request was sent to ComfyUI.")
        return 0

    # Test connectivity before queueing.
    try:
        request_json(f"{base_url}/system_stats", timeout=min(10, args.timeout))
    except (HTTPError, URLError, TimeoutError, OSError, RuntimeError) as exc:
        print(f"ERROR: cannot reach ComfyUI at {base_url}: {exc}", file=sys.stderr)
        print("Start ComfyUI and check the URL/port, then try again.", file=sys.stderr)
        return 1

    client_id = str(uuid.uuid4())
    try:
        # This is the exact edited graph sent in the API request.
        submitted = request_json(
            f"{base_url}/prompt", method="POST",
            payload={"prompt": workflow, "client_id": client_id}, timeout=30,
        )
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        print(f"ERROR: ComfyUI rejected the workflow (HTTP {exc.code}).\n{body}", file=sys.stderr)
        return 1
    except (URLError, TimeoutError, OSError, RuntimeError) as exc:
        print(f"ERROR: failed to submit workflow: {exc}", file=sys.stderr)
        return 1

    prompt_id = submitted.get("prompt_id")
    if not prompt_id:
        print("ERROR: ComfyUI response did not include prompt_id:", json.dumps(submitted, indent=2, ensure_ascii=False), file=sys.stderr)
        return 1
    if submitted.get("node_errors"):
        print("WARNING: ComfyUI reported node errors:", json.dumps(submitted["node_errors"], indent=2, ensure_ascii=False), file=sys.stderr)
    print(f"Queued ComfyUI prompt: {prompt_id}")
    print("Waiting for generation...")

    deadline = time.monotonic() + args.timeout
    history_entry = None
    while time.monotonic() < deadline:
        try:
            history = request_json(f"{base_url}/history/{quote(str(prompt_id), safe='')}", timeout=15)
        except (HTTPError, URLError, TimeoutError, OSError, RuntimeError) as exc:
            print(f"WARNING: history check failed; retrying: {exc}", file=sys.stderr)
            time.sleep(args.poll_interval)
            continue
        candidate = history.get(str(prompt_id))
        if isinstance(candidate, dict):
            status = candidate.get("status") or {}
            status_str = str(status.get("status_str", "")).lower() if isinstance(status, dict) else ""
            messages = status.get("messages", []) if isinstance(status, dict) else []
            if status_str == "error":
                print("ERROR: ComfyUI execution failed.", file=sys.stderr)
                if messages:
                    print(json.dumps(messages, indent=2, ensure_ascii=False), file=sys.stderr)
                return 1
            if status.get("completed") is True or status_str in {"success", "completed"}:
                history_entry = candidate
                break
            if isinstance(candidate.get("outputs"), dict) and candidate.get("outputs") and not status:
                history_entry = candidate
                break
        time.sleep(args.poll_interval)

    if history_entry is None:
        print(f"ERROR: timed out after {args.timeout:g} seconds. Prompt ID: {prompt_id}", file=sys.stderr)
        print("Check ComfyUI's UI/console for the execution status.", file=sys.stderr)
        return 1

    images: list[dict] = []
    outputs = history_entry.get("outputs") or {}
    for node_id, node_output in outputs.items():
        if not isinstance(node_output, dict):
            continue
        for image_info in node_output.get("images", []) or []:
            if isinstance(image_info, dict):
                images.append({**image_info, "node_id": node_id})

    if not images:
        print("Generation completed, but no output images were listed in the history response.")
        print(json.dumps(outputs, indent=2, ensure_ascii=False))
        return 0

    print(f"Generation complete. {len(images)} image(s):")
    for item in images:
        filename = item.get("filename", "(unnamed)")
        subfolder = item.get("subfolder", "")
        kind = item.get("type", "output")
        print(f"- ComfyUI: type={kind}, subfolder={subfolder!r}, filename={filename!r}")
        if not args.no_download:
            try:
                saved = download_image(base_url, item, args.output_dir, timeout=30)
                print(f"  Downloaded: {saved.resolve()}")
            except (HTTPError, URLError, TimeoutError, OSError, RuntimeError) as exc:
                print(f"  WARNING: could not download image: {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        raise SystemExit(130)
