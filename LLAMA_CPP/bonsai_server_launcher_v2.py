import os
import queue
import subprocess
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from pathlib import Path
import webbrowser


class BonsaiServerLauncher:
    def __init__(self, root):
        self.root = root
        self.root.title("Local GGUF API Launcher")
        self.root.geometry("780x750")
        self.root.minsize(700, 680)

        self.process = None
        self.log_queue = queue.Queue()

        self.server_var = tk.StringVar()
        self.model_var = tk.StringVar()
        self.mmproj_var = tk.StringVar()
        self.context_var = tk.StringVar(value="32768")
        # "auto" lets llama-server choose how many layers fit in available VRAM.
        self.gpu_layers_var = tk.StringVar(value="auto")
        self.cache_type_k_var = tk.StringVar(value="q8_0")
        self.cache_type_v_var = tk.StringVar(value="q8_0")
        self.fit_var = tk.BooleanVar(value=True)
        self.host_var = tk.StringVar(value="127.0.0.1")
        self.port_var = tk.StringVar(value="8080")
        self.alias_var = tk.StringVar(value="bonsai2")
        self.temp_var = tk.StringVar(value="1.0")
        self.top_p_var = tk.StringVar(value="0.95")
        self.top_k_var = tk.StringVar(value="20")
        self.min_p_var = tk.StringVar(value="0.05")
        self.flash_var = tk.BooleanVar(value=True)
        self.jinja_var = tk.BooleanVar(value=True)

        self._build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.after(100, self._poll_logs)

    def _build_ui(self):
        outer = ttk.Frame(self.root, padding=12)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(1, weight=1)
        outer.rowconfigure(11, weight=1)

        def file_row(row, label, variable, command, button_text="Browse…"):
            ttk.Label(outer, text=label).grid(row=row, column=0, sticky="w", padx=(0, 8), pady=5)
            ttk.Entry(outer, textvariable=variable).grid(row=row, column=1, sticky="ew", pady=5)
            ttk.Button(outer, text=button_text, command=command).grid(row=row, column=2, padx=(8, 0), pady=5)

        file_row(0, "llama-server.exe", self.server_var, self._browse_server)
        file_row(1, "Model (.gguf)", self.model_var, self._browse_model)
        file_row(2, "Vision mmproj (.gguf, optional)", self.mmproj_var, self._browse_mmproj)

        settings = ttk.LabelFrame(outer, text="Server settings", padding=10)
        settings.grid(row=3, column=0, columnspan=3, sticky="ew", pady=(10, 6))
        for col in (1, 3):
            settings.columnconfigure(col, weight=1)

        self._setting(settings, 0, 0, "Context tokens", self.context_var)
        self._setting(settings, 0, 2, "GPU layers (-ngl)", self.gpu_layers_var)
        self._setting(settings, 1, 0, "Host", self.host_var)
        self._setting(settings, 1, 2, "Port", self.port_var)
        self._setting(settings, 2, 0, "API model name", self.alias_var)
        self._setting(settings, 2, 2, "Temperature", self.temp_var)
        self._setting(settings, 3, 0, "Top-p", self.top_p_var)
        self._setting(settings, 3, 2, "Top-k", self.top_k_var)
        cache_types = ("f16", "bf16", "q8_0", "q5_0", "q5_1", "q4_0", "q4_1", "iq4_nl", "f32")
        self._choice(settings, 4, 0, "KV cache K (-ctk)", self.cache_type_k_var, cache_types)
        self._choice(settings, 4, 2, "KV cache V (-ctv)", self.cache_type_v_var, cache_types)
        self._setting(settings, 5, 0, "Min-p", self.min_p_var)

        checks = ttk.Frame(settings)
        checks.grid(row=5, column=2, columnspan=2, sticky="w", padx=4, pady=5)
        ttk.Checkbutton(checks, text="Flash attention", variable=self.flash_var).pack(side="left", padx=(0, 10))
        ttk.Checkbutton(checks, text="Jinja / tool templates", variable=self.jinja_var).pack(side="left")
        ttk.Checkbutton(
            settings,
            text="Auto-fit settings to available device memory (--fit on)",
            variable=self.fit_var,
        ).grid(row=6, column=0, columnspan=4, sticky="w", padx=4, pady=(4, 2))

        btns = ttk.Frame(outer)
        btns.grid(row=4, column=0, columnspan=3, sticky="ew", pady=6)
        self.start_btn = ttk.Button(btns, text="Start API", command=self.start_server)
        self.start_btn.pack(side="left")
        self.stop_btn = ttk.Button(btns, text="Stop server", command=self.stop_server, state="disabled")
        self.stop_btn.pack(side="left", padx=8)
        ttk.Button(btns, text="Open API", command=self.open_api).pack(side="left")
        ttk.Button(btns, text="Copy API URL", command=self.copy_api).pack(side="left", padx=8)

        self.api_label = ttk.Label(outer, text="API: http://127.0.0.1:8080/v1  |  Chat: /v1/chat/completions")
        self.api_label.grid(row=5, column=0, columnspan=3, sticky="w", pady=(2, 8))

        ttk.Label(outer, text="Server log").grid(row=6, column=0, columnspan=3, sticky="w")
        self.log_text = tk.Text(outer, wrap="word", height=16, state="disabled", background="#111827", foreground="#e5e7eb")
        self.log_text.grid(row=7, column=0, columnspan=3, sticky="nsew", pady=(4, 0))
        outer.rowconfigure(7, weight=1)

        ttk.Label(
            outer,
            text="Auto GPU layers and --fit on let the server fit layers to available VRAM. q8_0 KV cache uses less memory than f16; q4_0 saves more but can affect quality. Keep Host as 127.0.0.1 for local-only access.",
            wraplength=730,
        ).grid(row=8, column=0, columnspan=3, sticky="w", pady=(8, 0))

    @staticmethod
    def _setting(parent, row, col, label, variable):
        ttk.Label(parent, text=label).grid(row=row, column=col, sticky="w", padx=(4, 6), pady=5)
        ttk.Entry(parent, textvariable=variable, width=14).grid(row=row, column=col + 1, sticky="ew", padx=(0, 12), pady=5)

    @staticmethod
    def _choice(parent, row, col, label, variable, choices):
        ttk.Label(parent, text=label).grid(row=row, column=col, sticky="w", padx=(4, 6), pady=5)
        ttk.Combobox(
            parent, textvariable=variable, values=choices, state="readonly", width=12
        ).grid(row=row, column=col + 1, sticky="ew", padx=(0, 12), pady=5)

    def _browse_server(self):
        path = filedialog.askopenfilename(
            title="Choose llama-server.exe",
            filetypes=[("llama-server.exe", "llama-server.exe"), ("Executable", "*.exe"), ("All files", "*.*")],
        )
        if path:
            self.server_var.set(path)

    def _browse_model(self):
        path = filedialog.askopenfilename(title="Choose model GGUF", filetypes=[("GGUF model", "*.gguf"), ("All files", "*.*")])
        if path:
            self.model_var.set(path)
            if not self.alias_var.get().strip():
                self.alias_var.set(Path(path).stem)

    def _browse_mmproj(self):
        path = filedialog.askopenfilename(title="Choose mmproj GGUF (optional)", filetypes=[("GGUF projector", "*.gguf"), ("All files", "*.*")])
        if path:
            self.mmproj_var.set(path)

    def _append_log(self, text):
        self.log_text.configure(state="normal")
        self.log_text.insert("end", text)
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _get_args(self):
        server = Path(self.server_var.get().strip())
        model = Path(self.model_var.get().strip())
        mmproj_text = self.mmproj_var.get().strip()
        mmproj = Path(mmproj_text) if mmproj_text else None

        if not server.is_file():
            raise ValueError("Select a valid llama-server.exe file.")
        if not model.is_file():
            raise ValueError("Select a valid model .gguf file.")
        if mmproj and not mmproj.is_file():
            raise ValueError("The selected mmproj file does not exist.")

        try:
            context = int(self.context_var.get())
            gpu_layers_text = self.gpu_layers_var.get().strip().lower()
            if gpu_layers_text not in ("auto", "all"):
                gpu_layers = int(gpu_layers_text)
                if gpu_layers < 0:
                    raise ValueError
            port = int(self.port_var.get())
            top_k = int(self.top_k_var.get())
            temperature = float(self.temp_var.get())
            top_p = float(self.top_p_var.get())
            min_p = float(self.min_p_var.get())
        except ValueError:
            raise ValueError("Context, GPU layers (auto/all/or a number), port and sampling fields must be valid.")

        if context < 1:
            raise ValueError("Context must be greater than zero. Avoid huge values unless your memory supports them.")
        cache_types = {"f32", "f16", "bf16", "q8_0", "q5_0", "q5_1", "q4_0", "q4_1", "iq4_nl"}
        cache_k = self.cache_type_k_var.get().strip().lower()
        cache_v = self.cache_type_v_var.get().strip().lower()
        if cache_k not in cache_types or cache_v not in cache_types:
            raise ValueError("Choose supported cache types for K and V.")
        if not (1 <= port <= 65535):
            raise ValueError("Port must be between 1 and 65535.")
        if top_k < 0 or temperature < 0 or not (0 <= top_p <= 1) or not (0 <= min_p <= 1):
            raise ValueError("Sampling values are out of range.")
        host = self.host_var.get().strip() or "127.0.0.1"
        alias = self.alias_var.get().strip() or model.stem

        args = [
            str(server), "-m", str(model),
            "--host", host, "--port", str(port),
            "-c", str(context), "-ngl", gpu_layers_text,
            "-ctk", cache_k, "-ctv", cache_v,
            "--alias", alias,
            "--temp", str(temperature), "--top-p", str(top_p),
            "--top-k", str(top_k), "--min-p", str(min_p),
        ]
        if mmproj:
            args.extend(["--mmproj", str(mmproj)])
        if self.flash_var.get():
            args.extend(["-fa", "on"])
        if self.jinja_var.get():
            args.append("--jinja")
        if self.fit_var.get():
            args.extend(["--fit", "on"])
        return args, host, port, alias

    def start_server(self):
        if self.process and self.process.poll() is None:
            messagebox.showinfo("Server already running", "The API server is already running.")
            return
        try:
            args, host, port, alias = self._get_args()
        except ValueError as exc:
            messagebox.showerror("Check settings", str(exc))
            return

        self._append_log("\n> " + subprocess.list2cmdline(args) + "\n\n")
        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            self.process = subprocess.Popen(
                args,
                cwd=str(Path(args[0]).parent),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                creationflags=creation_flags,
            )
        except Exception as exc:
            self.process = None
            messagebox.showerror("Could not start server", str(exc))
            return

        threading.Thread(target=self._read_output, args=(self.process,), daemon=True).start()
        self.start_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        api_host = "127.0.0.1" if host in ("0.0.0.0", "::") else host
        self.api_label.configure(text=f"API: http://{api_host}:{port}/v1  |  Chat: /v1/chat/completions  |  Model: {alias}")
        self._append_log("Launching… wait for the server's startup/ready message before sending requests.\n")

    def _read_output(self, process):
        try:
            if process.stdout:
                for line in process.stdout:
                    self.log_queue.put(line)
        finally:
            code = process.wait()
            self.log_queue.put(f"\n[Server process exited with code {code}]\n")
            self.log_queue.put(("__EXIT__", process))

    def _poll_logs(self):
        try:
            while True:
                item = self.log_queue.get_nowait()
                if isinstance(item, tuple) and item and item[0] == "__EXIT__":
                    if self.process is item[1]:
                        self.process = None
                        self.start_btn.configure(state="normal")
                        self.stop_btn.configure(state="disabled")
                else:
                    self._append_log(item)
        except queue.Empty:
            pass
        self.root.after(100, self._poll_logs)

    def stop_server(self):
        proc = self.process
        if proc and proc.poll() is None:
            try:
                proc.terminate()
            except Exception as exc:
                messagebox.showerror("Stop failed", str(exc))
                return
            self._append_log("\nStopping server…\n")
        else:
            self.process = None
            self.start_btn.configure(state="normal")
            self.stop_btn.configure(state="disabled")

    def _api_root(self):
        host = self.host_var.get().strip() or "127.0.0.1"
        if host in ("0.0.0.0", "::"):
            host = "127.0.0.1"
        return f"http://{host}:{self.port_var.get().strip()}/v1"

    def open_api(self):
        url = self._api_root() + "/models"
        webbrowser.open(url)

    def copy_api(self):
        url = self._api_root()
        self.root.clipboard_clear()
        self.root.clipboard_append(url)
        self.root.update()
        messagebox.showinfo("Copied", f"Base API URL copied:\n{url}\n\nChat endpoint: {url}/chat/completions")

    def _on_close(self):
        if self.process and self.process.poll() is None:
            if not messagebox.askyesno("Exit", "Stop the running server and exit?"):
                return
            try:
                self.process.terminate()
            except Exception:
                pass
        self.root.destroy()


def main():
    root = tk.Tk()
    try:
        ttk.Style().theme_use("vista")
    except tk.TclError:
        pass
    BonsaiServerLauncher(root)
    root.mainloop()


if __name__ == "__main__":
    main()
