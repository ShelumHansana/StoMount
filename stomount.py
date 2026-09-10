#!/usr/bin/env python3
"""
StoMount
A standalone Windows desktop GUI application for managing Android adopted SD card storage via ADB.

Built using Python standard library only (Tkinter, subprocess, threading, json, os, sys, etc.).
"""

import os
import sys
import json
import time
import queue
import shutil
import pathlib
import threading
import subprocess
import zipfile
import urllib.request
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

# Application Metadata
APP_NAME = "StoMount"
APP_VERSION = "1.1.0"
CONFIG_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "StoMount")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")


# ---------------------------------------------------------------------------
# Tooltip Helper
# ---------------------------------------------------------------------------
class ToolTip:
    """Create a modern tooltip for a given widget."""
    def __init__(self, widget, text=""):
        self.widget = widget
        self.text = text
        self.tipwindow = None
        self.widget.bind("<Enter>", self.show_tip)
        self.widget.bind("<Leave>", self.hide_tip)

    def set_text(self, text):
        self.text = text

    def show_tip(self, event=None):
        if not self.text:
            return
        x, y, cx, cy = self.widget.bbox("insert") if hasattr(self.widget, "bbox") and self.widget.bbox("insert") else (0, 0, 0, 0)
        x = x + self.widget.winfo_rootx() + 20
        y = y + self.widget.winfo_rooty() + 28
        self.tipwindow = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        tw.configure(bg="#0f172a")
        label = tk.Label(
            tw, text=self.text, justify=tk.LEFT,
            background="#1e293b", foreground="#f8fafc",
            relief=tk.SOLID, borderwidth=1,
            font=("Segoe UI", 9), padx=10, pady=5
        )
        label.pack(ipadx=1)

    def hide_tip(self, event=None):
        if self.tipwindow:
            self.tipwindow.destroy()
            self.tipwindow = None


# ---------------------------------------------------------------------------
# ADB Subprocess Backend
# ---------------------------------------------------------------------------
class ADBBackend:
    def __init__(self, log_callback=None):
        self.adb_path = "adb"
        self.log_callback = log_callback
        self.device_serial = None
        self.load_config()

    def load_config(self):
        os.makedirs(CONFIG_DIR, exist_ok=True)
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                    saved_adb = cfg.get("adb_path", "")
                    if saved_adb and os.path.exists(saved_adb):
                        self.adb_path = saved_adb
            except Exception as e:
                self.log(f"Error reading config: {e}", "ERROR")

    def save_config(self, extra_data=None):
        try:
            os.makedirs(CONFIG_DIR, exist_ok=True)
            cfg = {}
            if os.path.exists(CONFIG_FILE):
                try:
                    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                        cfg = json.load(f)
                except Exception:
                    pass
            cfg["adb_path"] = self.adb_path
            if extra_data:
                cfg.update(extra_data)
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=2)
        except Exception as e:
            self.log(f"Error saving config: {e}", "ERROR")

    def get_saved_uuid(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                    return cfg.get("last_sd_uuid", "")
            except Exception:
                return ""
        return ""

    def save_sd_uuid(self, uuid_val):
        self.save_config({"last_sd_uuid": uuid_val})

    def is_adb_valid(self):
        """Test if the current adb path is valid and executable."""
        try:
            res = self.run_raw([self.adb_path, "version"], timeout=5)
            return res[0] and "Android Debug Bridge" in res[1]
        except Exception:
            return False

    def locate_adb(self):
        """Try to locate adb in bundled PyInstaller resources, application folder, PATH, or standard SDK paths."""
        if self.is_adb_valid():
            return self.adb_path

        # 1. Check PyInstaller _MEIPASS bundled folder
        if hasattr(sys, "_MEIPASS"):
            meipass_adb = os.path.join(sys._MEIPASS, "platform-tools", "adb.exe")
            if os.path.exists(meipass_adb):
                self.adb_path = meipass_adb
                return self.adb_path
            meipass_adb_root = os.path.join(sys._MEIPASS, "adb.exe")
            if os.path.exists(meipass_adb_root):
                self.adb_path = meipass_adb_root
                return self.adb_path

        # 2. Check directory next to application executable / script
        app_dir = os.path.dirname(os.path.abspath(sys.executable if getattr(sys, "frozen", False) else __file__))
        app_cand = [
            os.path.join(app_dir, "platform-tools", "adb.exe"),
            os.path.join(app_dir, "bin", "adb.exe"),
            os.path.join(app_dir, "adb.exe"),
        ]
        for c in app_cand:
            if os.path.exists(c):
                self.adb_path = c
                if self.is_adb_valid():
                    self.save_config()
                    return self.adb_path

        # 3. Check StoMount managed directory in LOCALAPPDATA
        local_app_data = os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))
        stomount_adb = os.path.join(local_app_data, "StoMount", "platform-tools", "adb.exe")
        if os.path.exists(stomount_adb):
            self.adb_path = stomount_adb
            if self.is_adb_valid():
                self.save_config()
                return self.adb_path

        # 4. Check PATH
        which_adb = shutil.which("adb")
        if which_adb:
            self.adb_path = which_adb
            self.save_config()
            return self.adb_path

        # 5. Check common Android SDK locations on Windows
        sdk_candidates = [
            os.path.join(local_app_data, "Android", "Sdk", "platform-tools", "adb.exe"),
            os.path.join(os.environ.get("ProgramFiles", "C:\\Program Files"), "Android", "platform-tools", "adb.exe"),
            os.path.join(os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)"), "Android", "platform-tools", "adb.exe"),
        ]
        for c in sdk_candidates:
            if os.path.exists(c):
                self.adb_path = c
                if self.is_adb_valid():
                    self.save_config()
                    return self.adb_path

        return None

    def download_platform_tools(self, progress_callback=None):
        """Download official Google Android platform-tools zip and unpack into LOCALAPPDATA."""
        url = "https://dl.google.com/android/repository/platform-tools-latest-windows.zip"
        target_base = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "StoMount")
        os.makedirs(target_base, exist_ok=True)
        zip_path = os.path.join(target_base, "platform-tools.zip")

        try:
            self.log("Connecting to dl.google.com to download Android platform-tools...", "INFO")
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
            with urllib.request.urlopen(req, timeout=60) as resp:
                total_size = int(resp.headers.get("Content-Length", 0))
                downloaded = 0
                block_size = 65536
                with open(zip_path, "wb") as f:
                    while True:
                        chunk = resp.read(block_size)
                        if not chunk:
                            break
                        f.write(chunk)
                        downloaded += len(chunk)
                        if progress_callback and total_size > 0:
                            pct = int((downloaded / total_size) * 100)
                            progress_callback(pct, f"Downloading ADB... ({pct}%)")

            self.log("Unzipping official Google platform-tools...", "INFO")
            with zipfile.ZipFile(zip_path, "r") as zip_ref:
                zip_ref.extractall(target_base)

            # Clean up zip
            try:
                os.remove(zip_path)
            except Exception:
                pass

            extracted_adb = os.path.join(target_base, "platform-tools", "adb.exe")
            if os.path.exists(extracted_adb):
                self.adb_path = extracted_adb
                self.save_config()
                self.log(f"Successfully installed ADB to: {extracted_adb}", "SUCCESS")
                return True, extracted_adb
            else:
                return False, "Extraction completed but adb.exe was not found."

        except Exception as e:
            self.log(f"Failed to download ADB: {e}", "ERROR")
            return False, str(e)

    def log(self, message, level="INFO"):
        if self.log_callback:
            self.log_callback(message, level)

    def run_raw(self, cmd_list, timeout=30):
        """Execute subprocess with hidden window flags on Windows."""
        creationflags = 0
        startupinfo = None
        if sys.platform == "win32":
            creationflags = subprocess.CREATE_NO_WINDOW
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = 0  # SW_HIDE

        try:
            proc = subprocess.Popen(
                cmd_list,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                startupinfo=startupinfo,
                creationflags=creationflags,
                text=True,
                encoding="utf-8",
                errors="replace"
            )
            stdout, stderr = proc.communicate(timeout=timeout)
            return proc.returncode == 0, stdout, stderr
        except subprocess.TimeoutExpired:
            proc.kill()
            return False, "", "Command timed out"
        except Exception as e:
            return False, "", str(e)

    def run_adb(self, args, timeout=60, log_cmd=True):
        """Run an adb command optionally targeting the active device serial."""
        cmd = [self.adb_path]
        if self.device_serial:
            cmd.extend(["-s", self.device_serial])
        cmd.extend(args)

        cmd_display = "adb " + " ".join(args)
        if log_cmd:
            self.log(f"$ {cmd_display}", "CMD")

        success, stdout, stderr = self.run_raw(cmd, timeout=timeout)
        stdout_clean = stdout.strip()
        stderr_clean = stderr.strip()

        if not success and stderr_clean:
            self.log(f"Error: {stderr_clean}", "ERROR")

        return success, stdout_clean, stderr_clean

    def check_connection(self):
        """Check ADB connection state: Connected, Unauthorized, Offline, Not Connected."""
        success, stdout, _ = self.run_raw([self.adb_path, "devices", "-l"], timeout=5)
        if not success:
            return "Not Connected", "ADB executable error or daemon stopped", None

        lines = [line.strip() for line in stdout.splitlines() if line.strip()]
        device_lines = [l for l in lines if not l.startswith("List of devices") and not l.startswith("* daemon")]

        if not device_lines:
            return "Not Connected", "No devices found via USB or Wi-Fi", None

        first_line = device_lines[0]
        parts = first_line.split()
        serial = parts[0]
        status = parts[1] if len(parts) > 1 else "unknown"

        model = "Android Device"
        for p in parts[2:]:
            if p.startswith("model:"):
                model = p.split(":", 1)[1]

        if status == "device":
            self.device_serial = serial
            return "Connected", f"{model} ({serial})", serial
        elif status == "unauthorized":
            return "Unauthorized", f"{serial} - Unlock phone and tap 'Allow USB debugging'", serial
        elif status == "offline":
            return "Offline", f"{serial} - Device offline. Unplug and reconnect USB cable", serial
        else:
            return "Not Connected", f"State: {status} ({serial})", serial

    def list_disks(self):
        """Find adoptable/removable storage disk IDs."""
        success, stdout, _ = self.run_adb(["shell", "sm", "list-disks", "adoptable"])
        disks = [line.strip() for line in stdout.splitlines() if line.strip().startswith("disk:")]
        if not disks:
            success, stdout, _ = self.run_adb(["shell", "sm", "list-disks"])
            disks = [line.strip() for line in stdout.splitlines() if line.strip().startswith("disk:")]
        return disks

    def partition_disk_private(self, disk_id):
        """Run 'adb shell sm partition <diskid> private'."""
        self.log(f"Partitioning disk {disk_id} as private adopted storage...", "INFO")
        success, stdout, stderr = self.run_adb(["shell", "sm", "partition", disk_id, "private"], timeout=120)
        output = (stdout + "\n" + stderr).strip()
        if success and "error" not in output.lower():
            return True, f"Successfully partitioned {disk_id} as private storage."
        return False, output or "Partition command failed without error output."

    def list_volumes(self):
        """Run 'adb shell sm list-volumes all'."""
        success, stdout, _ = self.run_adb(["shell", "sm", "list-volumes", "all"], log_cmd=False)
        return [line.strip() for line in stdout.splitlines() if line.strip()]

    def parse_adopted_uuid(self, volume_lines):
        """Parse adopted private volume UUID from sm list-volumes."""
        for line in volume_lines:
            line_clean = line.strip()
            if line_clean.startswith("private"):
                parts = line_clean.split()
                if "mounted" in parts:
                    idx = parts.index("mounted")
                    if idx + 1 < len(parts):
                        uuid_cand = parts[idx + 1].strip()
                        if uuid_cand and uuid_cand != "null":
                            return uuid_cand
                prefix = parts[0]
                if ":" in prefix:
                    ident = prefix.split(":", 1)[1]
                    if "-" in ident or len(ident) > 8:
                        return ident
        return None

    def list_third_party_packages(self):
        """Run 'adb shell pm list packages -3'."""
        success, stdout, _ = self.run_adb(["shell", "pm", "list", "packages", "-3"], log_cmd=False)
        packages = []
        for line in stdout.splitlines():
            line = line.strip()
            if line.startswith("package:"):
                pkg = line.replace("package:", "").strip()
                if pkg:
                    packages.append(pkg)
        return sorted(packages)

    def move_package(self, package_name, uuid_val):
        """Run 'adb shell pm move-package <pkg> <uuid>'."""
        self.log(f"Moving {package_name} to SD Card ({uuid_val})...", "INFO")
        success, stdout, stderr = self.run_adb(["shell", "pm", "move-package", package_name, uuid_val], timeout=180)
        output = (stdout + "\n" + stderr).strip()

        if "Success" in output or (success and "failure" not in output.lower()):
            self.log(f"✓ {package_name}: Move succeeded!", "SUCCESS")
            return True, output
        else:
            self.log(f"✕ {package_name}: Move failed ({output})", "ERROR")
            return False, output

    def move_primary_storage(self, uuid_val):
        """Run 'adb shell pm move-primary-storage <uuid>'."""
        self.log(f"Migrating primary shared media & storage to SD card ({uuid_val})...", "INFO")
        success, stdout, stderr = self.run_adb(["shell", "pm", "move-primary-storage", uuid_val], timeout=300)
        output = (stdout + "\n" + stderr).strip()
        if "Success" in output or (success and "failure" not in output.lower()):
            self.log(f"✓ Primary storage migration succeeded! {output}", "SUCCESS")
            return True, output
        else:
            self.log(f"✕ Primary storage migration failed! {output}", "ERROR")
            return False, output


# ---------------------------------------------------------------------------
# Help & Guide Dialog
# ---------------------------------------------------------------------------
class GuideDialog(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title("StoMount - Quick Setup & User Guide")
        self.geometry("640x520")
        self.minsize(580, 480)
        self.transient(parent)
        self.grab_set()
        self.configure(bg="#f8fafc")

        # Top banner
        header = tk.Frame(self, bg="#0f172a", padx=18, pady=14)
        header.pack(fill=tk.X)
        tk.Label(header, text="📖 How to Use StoMount", font=("Segoe UI", 13, "bold"), bg="#0f172a", fg="#38bdf8").pack(anchor="w")
        tk.Label(header, text="Step-by-step instructions to turn your SD card into fast internal storage.", font=("Segoe UI", 9), bg="#0f172a", fg="#94a3b8").pack(anchor="w", pady=(2, 0))

        content = tk.Frame(self, bg="#f8fafc", padx=20, pady=16)
        content.pack(fill=tk.BOTH, expand=True)

        steps = [
            ("1. Enable USB Debugging on Phone",
             "Open Android Settings → About Phone → Tap 'Build Number' 7 times.\n"
             "Then go to Settings → Developer Options → Enable 'USB Debugging'."),
            ("2. Connect Phone to PC via USB Cable",
             "Connect your phone with a good data cable. Look at your phone screen\n"
             "and tap 'Always allow from this computer' on the debugging prompt."),
            ("3. Step 1: Mount SD Card as Internal Storage",
             "Click the blue 'Mount SD Card as Internal Storage' button.\n"
             "⚠️ Warning: This formats the SD card. Make sure you back up any files on the card first!\n"
             "StoMount will format the card and detect its unique internal storage UUID."),
            ("4. Step 2: Move All Apps & Content",
             "Once the UUID is detected, click 'Move All Apps and Content to SD Card'.\n"
             "StoMount will move installed third-party apps and set your SD card as primary storage."),
            ("5. Optional: Auto-Move New Installs",
             "Toggle 'Auto-Move New Installs' ON to automatically transfer future app installations to SD card in the background.")
        ]

        for title, desc in steps:
            card = tk.Frame(content, bg="#ffffff", relief=tk.SOLID, bd=1, padx=12, pady=8)
            card.pack(fill=tk.X, pady=(0, 8))
            tk.Label(card, text=title, font=("Segoe UI", 9, "bold"), bg="#ffffff", fg="#0f172a").pack(anchor="w")
            tk.Label(card, text=desc, font=("Segoe UI", 8), bg="#ffffff", fg="#475569", justify=tk.LEFT).pack(anchor="w", pady=(2, 0))

        btn_row = tk.Frame(self, bg="#f1f5f9", padx=16, pady=10)
        btn_row.pack(fill=tk.X, side=tk.BOTTOM)
        ttk.Button(btn_row, text="Got it, Close", command=self.destroy).pack(side=tk.RIGHT)


# ---------------------------------------------------------------------------
# Confirmation Dialog for SD Formatting
# ---------------------------------------------------------------------------
class PartitionConfirmDialog(tk.Toplevel):
    def __init__(self, parent, disk_id):
        super().__init__(parent)
        self.title("⚠️ Mandatory Confirmation - Erase SD Card")
        self.disk_id = disk_id
        self.result = False

        self.geometry("540x410")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        self.setup_ui()
        self.center_window(parent)

    def center_window(self, parent):
        self.update_idletasks()
        px = parent.winfo_rootx()
        py = parent.winfo_rooty()
        pw = parent.winfo_width()
        ph = parent.winfo_height()
        w = self.winfo_width()
        h = self.winfo_height()
        x = px + max(0, (pw - w) // 2)
        y = py + max(0, (ph - h) // 2)
        self.geometry(f"+{x}+{y}")

    def setup_ui(self):
        self.configure(bg="#f8fafc")

        header_frame = tk.Frame(self, bg="#fef2f2", padx=18, pady=14, relief=tk.SOLID, bd=1)
        header_frame.pack(fill=tk.X)

        title_lbl = tk.Label(
            header_frame,
            text="⚠️ DATA LOSS WARNING: SD Card Will Be Formatted",
            font=("Segoe UI", 11, "bold"),
            bg="#fef2f2",
            fg="#991b1b"
        )
        title_lbl.pack(anchor="w")

        body_frame = tk.Frame(self, bg="#f8fafc", padx=20, pady=14)
        body_frame.pack(fill=tk.BOTH, expand=True)

        desc_text = (
            f"You are preparing to adopt disk '{self.disk_id}' as internal storage.\n\n"
            "• ALL existing files, photos, videos, and music on this SD card will be PERMANENTLY ERASED.\n"
            "• The card will be formatted with an encrypted filesystem and cannot be read on a PC without reformatting.\n"
            "• Please ensure you have copied any needed files off the card before continuing."
        )
        desc_lbl = tk.Label(
            body_frame,
            text=desc_text,
            font=("Segoe UI", 9),
            bg="#f8fafc",
            fg="#334155",
            justify=tk.LEFT,
            wraplength=490
        )
        desc_lbl.pack(anchor="w", pady=(0, 14))

        # Checkbox
        self.check_var = tk.BooleanVar(value=False)
        chk = tk.Checkbutton(
            body_frame,
            text="✓  I understand that all data on this SD card will be completely wiped.",
            variable=self.check_var,
            command=self.validate_input,
            bg="#f8fafc",
            activebackground="#f8fafc",
            fg="#b91c1c",
            font=("Segoe UI", 9, "bold")
        )
        chk.pack(anchor="w", pady=(0, 12))

        # Text prompt
        type_frame = tk.Frame(body_frame, bg="#ffffff", relief=tk.SOLID, bd=1, padx=12, pady=10)
        type_frame.pack(fill=tk.X, pady=(0, 10))

        type_lbl = tk.Label(
            type_frame,
            text='Confirmation step: Type "YES" in capital letters to unlock:',
            font=("Segoe UI", 9, "bold"),
            bg="#ffffff",
            fg="#1e293b"
        )
        type_lbl.pack(anchor="w", pady=(0, 4))

        self.confirm_entry_var = tk.StringVar()
        self.confirm_entry_var.trace_add("write", lambda *args: self.validate_input())
        self.entry = tk.Entry(
            type_frame,
            textvariable=self.confirm_entry_var,
            font=("Segoe UI", 11, "bold"),
            width=18,
            bg="#f8fafc"
        )
        self.entry.pack(anchor="w")

        # Bottom buttons
        btn_frame = tk.Frame(self, bg="#f1f5f9", padx=16, pady=12)
        btn_frame.pack(fill=tk.X, side=tk.BOTTOM)

        self.cancel_btn = ttk.Button(btn_row := btn_frame, text="Cancel (Keep Data Safe)", command=self.on_cancel)
        self.cancel_btn.pack(side=tk.RIGHT, padx=(8, 0))

        self.proceed_btn = tk.Button(
            btn_frame,
            text="Permanently Erase & Adopt SD Card",
            font=("Segoe UI", 9, "bold"),
            bg="#dc2626",
            fg="#ffffff",
            disabledforeground="#9ca3af",
            activebackground="#b91c1c",
            activeforeground="#ffffff",
            relief=tk.FLAT,
            padx=14,
            pady=5,
            state=tk.DISABLED,
            command=self.on_proceed
        )
        self.proceed_btn.pack(side=tk.RIGHT)

    def validate_input(self):
        typed = self.confirm_entry_var.get().strip()
        checked = self.check_var.get()
        if checked and typed == "YES":
            self.proceed_btn.config(state=tk.NORMAL, bg="#dc2626", cursor="hand2")
        else:
            self.proceed_btn.config(state=tk.DISABLED, bg="#e2e8f0", cursor="")

    def on_proceed(self):
        self.result = True
        self.destroy()

    def on_cancel(self):
        self.result = False
        self.destroy()


# ---------------------------------------------------------------------------
# Main GUI Application
# ---------------------------------------------------------------------------
class StoMountApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"{APP_NAME} - Android Adopted Storage Manager (v{APP_VERSION})")
        self.geometry("860x760")
        self.minsize(780, 680)

        # Set Window Icon
        for candidate_dir in [getattr(sys, "_MEIPASS", None), os.path.dirname(os.path.abspath(__file__))]:
            if candidate_dir:
                ico = os.path.join(candidate_dir, "app_icon.ico")
                if os.path.exists(ico):
                    try:
                        self.iconbitmap(ico)
                        break
                    except Exception:
                        pass

        # Apply clean theme
        self.configure(bg="#f8fafc")
        self.setup_styles()

        # Threading Queue for thread-safe UI updates
        self.ui_queue = queue.Queue()

        # Initialize Backend
        self.backend = ADBBackend(log_callback=self.enqueue_log)
        self.stored_uuid = self.backend.get_saved_uuid()

        # State Variables
        self.conn_state = tk.StringVar(value="Checking...")
        self.device_info_str = tk.StringVar(value="Searching for connected Android devices...")
        self.uuid_var = tk.StringVar(value=self.stored_uuid)
        self.detected_disk_var = tk.StringVar(value="Detecting SD Card disk...")
        self.operation_in_progress = False
        self.auto_move_active = tk.BooleanVar(value=False)
        self.auto_move_thread = None
        self.stop_auto_move_event = threading.Event()
        self.all_installed_packages = []
        self.filtered_packages = []

        # Build UI layout
        self.create_widgets()

        # Start periodic UI queue processor
        self.after(100, self.process_ui_queue)

        # Check ADB Path on launch
        self.after(200, self.verify_adb_on_start)

        # Start auto-refresh timer for device status (every 5 seconds)
        self.after(500, self.schedule_connection_poll)

    def setup_styles(self):
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except Exception:
            pass

        style.configure("Card.TFrame", background="#ffffff", relief="solid", borderwidth=1)
        style.configure("Primary.TButton", font=("Segoe UI", 10, "bold"), padding=8)
        style.configure("Secondary.TButton", font=("Segoe UI", 9), padding=5)

    def create_widgets(self):
        # ===================================================================
        # 1. Top Navigation & Status Bar
        # ===================================================================
        top_bar = tk.Frame(self, bg="#0f172a", padx=16, pady=10)
        top_bar.pack(fill=tk.X, side=tk.TOP)

        # Brand
        brand_box = tk.Frame(top_bar, bg="#0f172a")
        brand_box.pack(side=tk.LEFT)

        app_title = tk.Label(
            brand_box, text=f"⚡ {APP_NAME}", font=("Segoe UI", 13, "bold"),
            bg="#0f172a", fg="#38bdf8"
        )
        app_title.pack(side=tk.LEFT)

        tagline = tk.Label(
            brand_box, text=" | Android Adopted Storage", font=("Segoe UI", 9),
            bg="#0f172a", fg="#64748b"
        )
        tagline.pack(side=tk.LEFT)

        # Quick action buttons on top right
        guide_btn = tk.Button(
            top_bar, text="📖 User Guide", font=("Segoe UI", 8, "bold"),
            bg="#1e293b", fg="#e2e8f0", activebackground="#334155", activeforeground="#ffffff",
            relief=tk.FLAT, padx=8, pady=3, cursor="hand2", command=self.open_guide
        )
        guide_btn.pack(side=tk.RIGHT, padx=(6, 0))

        adb_cfg_btn = tk.Button(
            top_bar, text="⚙ ADB Path", font=("Segoe UI", 8),
            bg="#1e293b", fg="#cbd5e1", activebackground="#334155", activeforeground="#ffffff",
            relief=tk.FLAT, padx=8, pady=3, cursor="hand2", command=self.open_adb_config_dialog
        )
        adb_cfg_btn.pack(side=tk.RIGHT, padx=(6, 0))

        refresh_conn_btn = tk.Button(
            top_bar, text="↻ Refresh", font=("Segoe UI", 8),
            bg="#1e293b", fg="#cbd5e1", activebackground="#334155", activeforeground="#ffffff",
            relief=tk.FLAT, padx=8, pady=3, cursor="hand2", command=self.manual_refresh_connection
        )
        refresh_conn_btn.pack(side=tk.RIGHT)
        ToolTip(refresh_conn_btn, "Immediately re-checks USB connection & SD card status.")

        # ===================================================================
        # 2. Device & SD Card Overview Dashboard Card
        # ===================================================================
        dash_frame = tk.Frame(self, bg="#1e293b", padx=16, pady=10)
        dash_frame.pack(fill=tk.X)

        # Connection status badge
        self.status_badge = tk.Label(
            dash_frame, text="Checking Device...", font=("Segoe UI", 9, "bold"),
            bg="#334155", fg="#f8fafc", padx=10, pady=4, relief=tk.FLAT
        )
        self.status_badge.pack(side=tk.LEFT, padx=(0, 10))

        # Device info & phone model
        self.device_label = tk.Label(
            dash_frame, textvariable=self.device_info_str,
            font=("Segoe UI", 9), bg="#1e293b", fg="#cbd5e1"
        )
        self.device_label.pack(side=tk.LEFT)

        # Detected SD Card info indicator
        self.disk_badge = tk.Label(
            dash_frame, textvariable=self.detected_disk_var,
            font=("Segoe UI", 8, "bold"), bg="#0f172a", fg="#38bdf8", padx=8, pady=3, relief=tk.FLAT
        )
        self.disk_badge.pack(side=tk.RIGHT)

        # ===================================================================
        # 3. Main Workspace Container
        # ===================================================================
        main_content = tk.Frame(self, bg="#f8fafc", padx=16, pady=12)
        main_content.pack(fill=tk.BOTH, expand=True)

        # SD Card UUID bar
        uuid_card = tk.Frame(main_content, bg="#ffffff", relief=tk.SOLID, bd=1, padx=14, pady=8)
        uuid_card.pack(fill=tk.X, pady=(0, 10))

        tk.Label(uuid_card, text="Adopted SD Card UUID:", font=("Segoe UI", 9, "bold"), bg="#ffffff", fg="#334155").pack(side=tk.LEFT, padx=(0, 6))

        self.uuid_entry = ttk.Entry(uuid_card, textvariable=self.uuid_var, width=34, font=("Consolas", 10))
        self.uuid_entry.pack(side=tk.LEFT, padx=(0, 8))
        self.uuid_var.trace_add("write", lambda *args: self.on_uuid_changed())

        detect_btn = ttk.Button(uuid_card, text="🔍 Detect UUID", command=self.detect_sd_uuid_thread)
        detect_btn.pack(side=tk.LEFT, padx=(0, 4))
        ToolTip(detect_btn, "Inspects 'sm list-volumes' to detect any currently adopted SD card UUID.")

        save_uuid_btn = ttk.Button(uuid_card, text="💾 Save UUID", command=self.save_current_uuid)
        save_uuid_btn.pack(side=tk.LEFT, padx=(0, 8))
        ToolTip(save_uuid_btn, "Save this UUID permanently so you don't have to detect it again.")

        self.uuid_status_pill = tk.Label(
            uuid_card, text="Not detected yet", font=("Segoe UI", 8, "bold"),
            bg="#fef3c7", fg="#b45309", padx=8, pady=2
        )
        self.uuid_status_pill.pack(side=tk.RIGHT)

        # ===================================================================
        # 4. Primary Guided Actions (Front and Center)
        # ===================================================================
        actions_header = tk.Frame(main_content, bg="#f8fafc")
        actions_header.pack(fill=tk.X, pady=(0, 6))

        tk.Label(
            actions_header, text="PRIMARY WORKFLOW (FOLLOW STEPS 1 & 2)",
            font=("Segoe UI", 10, "bold"), bg="#f8fafc", fg="#475569"
        ).pack(side=tk.LEFT)

        actions_grid = tk.Frame(main_content, bg="#f8fafc")
        actions_grid.pack(fill=tk.X, pady=(0, 10))
        actions_grid.columnconfigure(0, weight=1, uniform="col")
        actions_grid.columnconfigure(1, weight=1, uniform="col")

        # -----------------------------
        # STEP 1 CARD
        # -----------------------------
        card1 = tk.Frame(actions_grid, bg="#ffffff", relief=tk.SOLID, bd=1, padx=14, pady=12)
        card1.grid(row=0, column=0, sticky="nsew", padx=(0, 6))

        c1_top = tk.Frame(card1, bg="#ffffff")
        c1_top.pack(fill=tk.X)

        tk.Label(c1_top, text="STEP 1", font=("Segoe UI", 8, "bold"), bg="#dbeafe", fg="#1d4ed8", padx=6, pady=1).pack(side=tk.LEFT)
        self.c1_status_pill = tk.Label(c1_top, text="Start Here", font=("Segoe UI", 8, "bold"), bg="#f1f5f9", fg="#475569", padx=6, pady=1)
        self.c1_status_pill.pack(side=tk.RIGHT)

        tk.Label(
            card1, text="Mount SD as Internal Storage",
            font=("Segoe UI", 11, "bold"), bg="#ffffff", fg="#0f172a"
        ).pack(anchor="w", pady=(6, 2))

        c1_desc = tk.Label(
            card1,
            text="Formats the removable microSD card into encrypted adopted storage ('sm partition private').\n⚠️ Erases all data on the card!",
            font=("Segoe UI", 8), bg="#ffffff", fg="#64748b", justify=tk.LEFT, wraplength=350
        )
        c1_desc.pack(anchor="w", pady=(0, 10))

        self.mount_btn = tk.Button(
            card1,
            text="⚡ Mount SD Card as Internal Storage",
            font=("Segoe UI", 10, "bold"),
            bg="#2563eb", fg="#ffffff",
            activebackground="#1d4ed8", activeforeground="#ffffff",
            disabledforeground="#94a3b8",
            relief=tk.FLAT, padx=12, pady=8,
            cursor="hand2",
            command=self.on_mount_sd_clicked
        )
        self.mount_btn.pack(fill=tk.X)

        # -----------------------------
        # STEP 2 CARD
        # -----------------------------
        card2 = tk.Frame(actions_grid, bg="#ffffff", relief=tk.SOLID, bd=1, padx=14, pady=12)
        card2.grid(row=0, column=1, sticky="nsew", padx=(6, 0))

        c2_top = tk.Frame(card2, bg="#ffffff")
        c2_top.pack(fill=tk.X)

        tk.Label(c2_top, text="STEP 2", font=("Segoe UI", 8, "bold"), bg="#dcfce7", fg="#15803d", padx=6, pady=1).pack(side=tk.LEFT)
        self.c2_status_pill = tk.Label(c2_top, text="Requires Step 1", font=("Segoe UI", 8, "bold"), bg="#fee2e2", fg="#991b1b", padx=6, pady=1)
        self.c2_status_pill.pack(side=tk.RIGHT)

        tk.Label(
            card2, text="Move All Apps & Content to SD",
            font=("Segoe UI", 11, "bold"), bg="#ffffff", fg="#0f172a"
        ).pack(anchor="w", pady=(6, 2))

        c2_desc = tk.Label(
            card2,
            text="Batch moves all installed 3rd-party apps to the adopted SD card, then migrates primary storage for photos, downloads, and media.",
            font=("Segoe UI", 8), bg="#ffffff", fg="#64748b", justify=tk.LEFT, wraplength=350
        )
        c2_desc.pack(anchor="w", pady=(0, 10))

        self.move_all_btn = tk.Button(
            card2,
            text="🚀 Move All Apps & Content to SD Card",
            font=("Segoe UI", 10, "bold"),
            bg="#059669", fg="#ffffff",
            activebackground="#047857", activeforeground="#ffffff",
            disabledforeground="#94a3b8",
            relief=tk.FLAT, padx=12, pady=8,
            cursor="hand2",
            command=self.on_move_all_clicked
        )
        self.move_all_btn.pack(fill=tk.X)
        self.move_all_tooltip = ToolTip(self.move_all_btn, "Requires an adopted SD Card UUID to be detected first.")

        # ===================================================================
        # 5. Additional Storage Controls (Single App & Auto-Move)
        # ===================================================================
        sec_card = tk.LabelFrame(
            main_content, text="  Additional Storage Controls  ",
            font=("Segoe UI", 9, "bold"), bg="#ffffff", fg="#334155", padx=14, pady=10
        )
        sec_card.pack(fill=tk.X, pady=(0, 10))

        # Row 1: Move Single App with Search Filter
        row1 = tk.Frame(sec_card, bg="#ffffff")
        row1.pack(fill=tk.X, pady=(0, 6))

        tk.Label(row1, text="Move Single App:", font=("Segoe UI", 9, "bold"), bg="#ffffff", fg="#334155").pack(side=tk.LEFT, padx=(0, 6))

        # Search filter
        self.app_filter_var = tk.StringVar()
        self.app_filter_var.trace_add("write", self.filter_app_list)
        self.filter_entry = ttk.Entry(row1, textvariable=self.app_filter_var, width=16)
        self.filter_entry.pack(side=tk.LEFT, padx=(0, 6))
        ToolTip(self.filter_entry, "Filter app list by name (e.g., whatsapp, music)")

        self.single_app_combo = ttk.Combobox(row1, width=32, state="readonly")
        self.single_app_combo.pack(side=tk.LEFT, padx=(0, 6))

        self.refresh_apps_btn = ttk.Button(row1, text="↻ Refresh List", command=self.refresh_app_list_thread)
        self.refresh_apps_btn.pack(side=tk.LEFT, padx=(0, 6))

        self.move_single_btn = ttk.Button(row1, text="Move App", command=self.on_move_single_app_clicked)
        self.move_single_btn.pack(side=tk.LEFT)

        self.apps_count_lbl = tk.Label(row1, text="", font=("Segoe UI", 8), bg="#ffffff", fg="#64748b")
        self.apps_count_lbl.pack(side=tk.RIGHT)

        # Separator line
        ttk.Separator(sec_card, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=6)

        # Row 2: Auto-move new installs
        row2 = tk.Frame(sec_card, bg="#ffffff")
        row2.pack(fill=tk.X)

        self.auto_move_chk = ttk.Checkbutton(
            row2,
            text="Auto-move newly installed apps to SD Card (scans every 20 seconds in background)",
            variable=self.auto_move_active,
            command=self.on_toggle_auto_move
        )
        self.auto_move_chk.pack(side=tk.LEFT)

        self.auto_move_indicator = tk.Label(
            row2, text="OFF", font=("Segoe UI", 8, "bold"),
            bg="#f1f5f9", fg="#64748b", padx=8, pady=2
        )
        self.auto_move_indicator.pack(side=tk.LEFT, padx=(10, 0))

        # ===================================================================
        # 6. Progress & Status Banner
        # ===================================================================
        self.progress_frame = tk.Frame(main_content, bg="#f8fafc")
        self.progress_frame.pack(fill=tk.X, pady=(0, 6))

        prog_top = tk.Frame(self.progress_frame, bg="#f8fafc")
        prog_top.pack(fill=tk.X)

        self.progress_lbl = tk.Label(
            prog_top,
            text="Ready",
            font=("Segoe UI", 9, "bold"),
            bg="#f8fafc",
            fg="#0f172a"
        )
        self.progress_lbl.pack(side=tk.LEFT)

        self.progress_pct_lbl = tk.Label(
            prog_top,
            text="",
            font=("Segoe UI", 8, "bold"),
            bg="#f8fafc",
            fg="#475569"
        )
        self.progress_pct_lbl.pack(side=tk.RIGHT)

        self.progress_bar = ttk.Progressbar(self.progress_frame, orient=tk.HORIZONTAL, mode="determinate")
        self.progress_bar.pack(fill=tk.X, pady=(2, 0))

        # ===================================================================
        # 7. Real-Time ADB Console / Log Panel
        # ===================================================================
        log_header = tk.Frame(main_content, bg="#f8fafc")
        log_header.pack(fill=tk.X, pady=(4, 2))

        tk.Label(log_header, text="ADB Command Log & Real-Time Console", font=("Segoe UI", 9, "bold"), bg="#f8fafc", fg="#475569").pack(side=tk.LEFT)

        copy_btn = tk.Button(
            log_header, text="📋 Copy All", font=("Segoe UI", 8),
            bg="#e2e8f0", fg="#334155", relief=tk.FLAT, padx=6, pady=1,
            cursor="hand2", command=self.copy_log_to_clipboard
        )
        copy_btn.pack(side=tk.RIGHT, padx=(4, 0))

        clear_btn = tk.Button(
            log_header, text="Clear Log", font=("Segoe UI", 8),
            bg="#e2e8f0", fg="#334155", relief=tk.FLAT, padx=6, pady=1,
            cursor="hand2", command=self.clear_log
        )
        clear_btn.pack(side=tk.RIGHT)

        log_container = tk.Frame(main_content, bg="#0f172a", relief=tk.SOLID, bd=1)
        log_container.pack(fill=tk.BOTH, expand=True)

        self.log_text = tk.Text(
            log_container,
            bg="#0f172a",
            fg="#e2e8f0",
            insertbackground="#ffffff",
            font=("Consolas", 9),
            wrap=tk.WORD,
            padx=8,
            pady=8,
            height=9
        )
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        log_scroll = ttk.Scrollbar(log_container, orient=tk.VERTICAL, command=self.log_text.yview)
        log_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.log_text.configure(yscrollcommand=log_scroll.set)

        self.log_text.tag_config("TIME", foreground="#64748b")
        self.log_text.tag_config("INFO", foreground="#38bdf8")
        self.log_text.tag_config("SUCCESS", foreground="#4ade80", font=("Consolas", 9, "bold"))
        self.log_text.tag_config("WARNING", foreground="#fbbf24")
        self.log_text.tag_config("ERROR", foreground="#f87171", font=("Consolas", 9, "bold"))
        self.log_text.tag_config("CMD", foreground="#c084fc")

        self.on_uuid_changed()

    # -----------------------------------------------------------------------
    # Logging & Thread-safe Queue
    # -----------------------------------------------------------------------
    def enqueue_log(self, message, level="INFO"):
        self.ui_queue.put(("LOG", (message, level)))

    def clear_log(self):
        self.log_text.delete("1.0", tk.END)

    def copy_log_to_clipboard(self):
        txt = self.log_text.get("1.0", tk.END).strip()
        if txt:
            self.clipboard_clear()
            self.clipboard_append(txt)
            messagebox.showinfo("Copied", "Console log copied to clipboard!", parent=self)

    def open_guide(self):
        GuideDialog(self)

    def process_ui_queue(self):
        while not self.ui_queue.empty():
            try:
                event_type, data = self.ui_queue.get_nowait()
                if event_type == "LOG":
                    msg, level = data
                    timestamp = time.strftime("%H:%M:%S")
                    self.log_text.insert(tk.END, f"[{timestamp}] ", "TIME")
                    self.log_text.insert(tk.END, f"[{level}] ", level)
                    self.log_text.insert(tk.END, f"{msg}\n")
                    self.log_text.see(tk.END)
                elif event_type == "STATUS":
                    state, info, disks = data
                    self.update_status_display(state, info, disks)
                elif event_type == "SET_UUID":
                    uuid_val = data
                    self.uuid_var.set(uuid_val)
                    self.backend.save_sd_uuid(uuid_val)
                    self.on_uuid_changed()
                elif event_type == "SET_APPS":
                    apps = data
                    self.all_installed_packages = apps
                    self.filter_app_list()
                elif event_type == "PROGRESS_START":
                    total = data
                    self.progress_bar.config(mode="determinate", maximum=total, value=0)
                    self.progress_pct_lbl.config(text="0%")
                elif event_type == "PROGRESS_UPDATE":
                    curr, total, text = data
                    self.progress_bar.config(value=curr)
                    pct = int((curr / total) * 100) if total else 0
                    self.progress_pct_lbl.config(text=f"{pct}%")
                    self.progress_lbl.config(text=text)
                elif event_type == "PROGRESS_INDETERMINATE":
                    text = data
                    self.progress_bar.config(mode="indeterminate")
                    self.progress_bar.start(15)
                    self.progress_pct_lbl.config(text="Working...")
                    self.progress_lbl.config(text=text)
                elif event_type == "PROGRESS_STOP":
                    text = data
                    self.progress_bar.stop()
                    self.progress_bar.config(mode="determinate", value=0)
                    self.progress_pct_lbl.config(text="")
                    self.progress_lbl.config(text=text or "Ready")
                elif event_type == "SET_BUSY":
                    busy = data
                    self.set_busy_state(busy)
                elif event_type == "ALERT":
                    kind, title, text = data
                    if kind == "error":
                        messagebox.showerror(title, text, parent=self)
                    elif kind == "info":
                        messagebox.showinfo(title, text, parent=self)
                    elif kind == "warning":
                        messagebox.showwarning(title, text, parent=self)
            except queue.Empty:
                break
        self.after(100, self.process_ui_queue)

    def set_busy_state(self, busy):
        self.operation_in_progress = busy
        state = tk.DISABLED if busy else tk.NORMAL

        self.mount_btn.config(state=state)
        self.refresh_apps_btn.config(state=state)
        self.move_single_btn.config(state=state)
        self.uuid_entry.config(state="disabled" if busy else "normal")
        self.on_uuid_changed()

    def on_uuid_changed(self):
        uuid_val = self.uuid_var.get().strip()
        if not self.operation_in_progress:
            if uuid_val:
                self.move_all_btn.config(state=tk.NORMAL, bg="#059669")
                self.move_all_tooltip.set_text("Move all 3rd-party apps and primary storage to SD card: " + uuid_val)
                self.uuid_status_pill.config(text="✓ Adopted UUID Set", bg="#dcfce7", fg="#15803d")
                self.c1_status_pill.config(text="✓ SD Card Adopted", bg="#dcfce7", fg="#15803d")
                self.c2_status_pill.config(text="Ready to Migrate", bg="#dbeafe", fg="#1d4ed8")
            else:
                self.move_all_btn.config(state=tk.DISABLED, bg="#e2e8f0")
                self.move_all_tooltip.set_text("Requires an adopted SD card UUID. Complete Step 1 or enter a valid UUID.")
                self.uuid_status_pill.config(text="No UUID Detected", bg="#fef3c7", fg="#b45309")
                self.c1_status_pill.config(text="Start Here", bg="#f1f5f9", fg="#475569")
                self.c2_status_pill.config(text="Requires Step 1", bg="#fee2e2", fg="#991b1b")
        else:
            self.move_all_btn.config(state=tk.DISABLED, bg="#e2e8f0")

    def filter_app_list(self, *args):
        query = self.app_filter_var.get().strip().lower()
        if not query:
            self.filtered_packages = list(self.all_installed_packages)
        else:
            self.filtered_packages = [p for p in self.all_installed_packages if query in p.lower()]

        self.single_app_combo["values"] = self.filtered_packages
        if self.filtered_packages:
            self.single_app_combo.current(0)
        else:
            self.single_app_combo.set("")

        count_text = f"{len(self.filtered_packages)} / {len(self.all_installed_packages)} apps" if query else f"{len(self.all_installed_packages)} apps installed"
        self.apps_count_lbl.config(text=count_text)

    def save_current_uuid(self):
        val = self.uuid_var.get().strip()
        self.backend.save_sd_uuid(val)
        self.enqueue_log(f"Saved SD UUID '{val}' to config.", "SUCCESS")
        messagebox.showinfo("Saved", f"Adopted SD Card UUID saved as:\n{val or '(empty)'}", parent=self)

    # -----------------------------------------------------------------------
    # Connection Polling & Status
    # -----------------------------------------------------------------------
    def schedule_connection_poll(self):
        if not self.operation_in_progress:
            threading.Thread(target=self.poll_connection_worker, daemon=True).start()
        self.after(5000, self.schedule_connection_poll)

    def manual_refresh_connection(self):
        self.status_badge.config(text="Checking...", bg="#334155", fg="#ffffff")
        threading.Thread(target=self.poll_connection_worker, daemon=True).start()

    def poll_connection_worker(self):
        state, info, _ = self.backend.check_connection()
        disks = []
        if state == "Connected":
            disks = self.backend.list_disks()
        self.ui_queue.put(("STATUS", (state, info, disks)))

    def update_status_display(self, state, info, disks):
        self.conn_state.set(state)
        self.device_info_str.set(info)

        if state == "Connected":
            self.status_badge.config(text="● Connected", bg="#059669", fg="#ffffff")
            if disks:
                self.detected_disk_var.set(f"SD Card: {', '.join(disks)}")
                self.disk_badge.config(bg="#0284c7", fg="#ffffff")
            else:
                self.detected_disk_var.set("No SD card disk detected")
                self.disk_badge.config(bg="#475569", fg="#cbd5e1")
        elif state == "Unauthorized":
            self.status_badge.config(text="▲ Unauthorized", bg="#d97706", fg="#ffffff")
            self.detected_disk_var.set("Unlock phone to detect SD")
            self.disk_badge.config(bg="#d97706", fg="#ffffff")
        elif state == "Offline":
            self.status_badge.config(text="■ Offline", bg="#dc2626", fg="#ffffff")
            self.detected_disk_var.set("Device offline")
            self.disk_badge.config(bg="#dc2626", fg="#ffffff")
        else:
            self.status_badge.config(text="✕ Not Connected", bg="#475569", fg="#ffffff")
            self.detected_disk_var.set("Waiting for USB connection...")
            self.disk_badge.config(bg="#334155", fg="#94a3b8")

    # -----------------------------------------------------------------------
    # ADB Configuration Dialog
    # -----------------------------------------------------------------------
    def verify_adb_on_start(self):
        found = self.backend.locate_adb()
        if not found:
            self.enqueue_log("ADB executable not found in PATH or standard SDK locations.", "WARNING")
            self.prompt_locate_adb()
        else:
            self.enqueue_log(f"Ready. Using ADB at: {self.backend.adb_path}", "INFO")
            self.refresh_app_list_thread()

    def prompt_locate_adb(self):
        """Prompt user with choices to either auto-download official Google ADB or browse manually."""
        win = tk.Toplevel(self)
        win.title("ADB Setup Required")
        win.geometry("540x260")
        win.resizable(False, False)
        win.transient(self)
        win.grab_set()
        win.configure(bg="#f8fafc")

        header = tk.Frame(win, bg="#0f172a", padx=16, pady=12)
        header.pack(fill=tk.X)
        tk.Label(header, text="⚡ Android ADB Setup", font=("Segoe UI", 11, "bold"), bg="#0f172a", fg="#38bdf8").pack(anchor="w")
        tk.Label(header, text="StoMount requires the Android Debug Bridge (adb.exe) to communicate with your phone.", font=("Segoe UI", 8), bg="#0f172a", fg="#94a3b8").pack(anchor="w")

        body = tk.Frame(win, bg="#f8fafc", padx=20, pady=16)
        body.pack(fill=tk.BOTH, expand=True)

        desc = tk.Label(
            body,
            text="No working ADB was detected on this PC.\nStoMount can automatically download the official Google Android platform-tools for you with zero setup required.",
            font=("Segoe UI", 9), bg="#f8fafc", fg="#334155", justify=tk.LEFT
        )
        desc.pack(anchor="w", pady=(0, 14))

        status_lbl = tk.Label(body, text="", font=("Segoe UI", 9, "bold"), bg="#f8fafc", fg="#0284c7")
        status_lbl.pack(anchor="w", pady=(0, 8))

        btn_box = tk.Frame(body, bg="#f8fafc")
        btn_box.pack(fill=tk.X)

        def do_download():
            status_lbl.config(text="Connecting to Google & downloading official platform-tools...", fg="#0284c7")
            dl_btn.config(state=tk.DISABLED)
            browse_btn.config(state=tk.DISABLED)

            def worker():
                def prog_cb(pct, txt):
                    self.ui_queue.put(("LOG", (f"ADB Download: {pct}%", "INFO")))
                    self.after(0, lambda: status_lbl.config(text=f"Downloading: {pct}%"))

                ok, res = self.backend.download_platform_tools(progress_callback=prog_cb)
                if ok:
                    self.after(0, lambda: [
                        messagebox.showinfo("Success", "Official Google ADB downloaded and configured successfully!", parent=win),
                        win.destroy(),
                        self.refresh_app_list_thread()
                    ])
                else:
                    self.after(0, lambda: [
                        status_lbl.config(text=f"Download failed: {res}", fg="#dc2626"),
                        dl_btn.config(state=tk.NORMAL),
                        browse_btn.config(state=tk.NORMAL)
                    ])

            threading.Thread(target=worker, daemon=True).start()

        dl_btn = tk.Button(
            btn_box, text="⚡ Download & Install ADB Automatically (Recommended)",
            font=("Segoe UI", 9, "bold"), bg="#059669", fg="#ffffff",
            activebackground="#047857", activeforeground="#ffffff", relief=tk.FLAT, padx=12, pady=6,
            cursor="hand2", command=do_download
        )
        dl_btn.pack(side=tk.LEFT, padx=(0, 8))

        browse_btn = ttk.Button(btn_box, text="📁 Browse Manually...", command=lambda: [win.destroy(), self.browse_for_adb()])
        browse_btn.pack(side=tk.LEFT)

    def browse_for_adb(self):
        path = filedialog.askopenfilename(
            title="Locate adb.exe",
            filetypes=[("Executable Files", "*.exe"), ("All Files", "*.*")],
            parent=self
        )
        if path:
            self.backend.adb_path = path
            if self.backend.is_adb_valid():
                self.backend.save_config()
                self.enqueue_log(f"Configured ADB path: {path}", "SUCCESS")
                messagebox.showinfo("ADB Configured", f"ADB found and saved!\n{path}", parent=self)
                self.refresh_app_list_thread()
            else:
                self.enqueue_log(f"The selected file at '{path}' is not a working ADB binary.", "ERROR")
                messagebox.showerror("Invalid ADB", "The selected file did not respond to 'adb version'.", parent=self)

    def open_adb_config_dialog(self):
        win = tk.Toplevel(self)
        win.title("ADB Settings")
        win.geometry("560x220")
        win.resizable(False, False)
        win.transient(self)
        win.grab_set()

        tk.Label(win, text="Active ADB Executable Path:", font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=16, pady=(16, 4))

        path_var = tk.StringVar(value=self.backend.adb_path)
        entry = ttk.Entry(win, textvariable=path_var, width=62)
        entry.pack(padx=16, fill=tk.X, pady=(0, 10))

        status_lbl = tk.Label(win, text="", font=("Segoe UI", 8), fg="#0284c7")
        status_lbl.pack(anchor="w", padx=16, pady=(0, 8))

        btn_row = tk.Frame(win)
        btn_row.pack(fill=tk.X, padx=16)

        def browse():
            p = filedialog.askopenfilename(parent=win, filetypes=[("Executable", "*.exe"), ("All", "*.*")])
            if p:
                path_var.set(p)

        def auto_download():
            status_lbl.config(text="Downloading Google platform-tools...")
            def worker():
                ok, res = self.backend.download_platform_tools()
                if ok:
                    self.after(0, lambda: [
                        path_var.set(res),
                        status_lbl.config(text="Downloaded and installed successfully!"),
                        messagebox.showinfo("Success", "Official Google ADB downloaded and installed!", parent=win)
                    ])
                else:
                    self.after(0, lambda: status_lbl.config(text=f"Download error: {res}"))
            threading.Thread(target=worker, daemon=True).start()

        def save():
            new_p = path_var.get().strip()
            self.backend.adb_path = new_p
            if self.backend.is_adb_valid():
                self.backend.save_config()
                self.enqueue_log(f"ADB updated to: {new_p}", "SUCCESS")
                messagebox.showinfo("Success", "ADB path updated and saved.", parent=win)
                win.destroy()
            else:
                messagebox.showerror("Error", "Invalid ADB binary at specified path.", parent=win)

        ttk.Button(btn_row, text="📁 Browse...", command=browse).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(btn_row, text="⚡ Auto-Download from Google", command=auto_download).pack(side=tk.LEFT)
        ttk.Button(btn_row, text="Save & Close", command=save).pack(side=tk.RIGHT)
        ttk.Button(btn_row, text="Cancel", command=win.destroy).pack(side=tk.RIGHT, padx=6)

    # -----------------------------------------------------------------------
    # Primary Action 1: Mount SD Card as Internal Storage
    # -----------------------------------------------------------------------
    def on_mount_sd_clicked(self):
        state, info, _ = self.backend.check_connection()
        if state != "Connected":
            messagebox.showerror(
                "Device Not Ready",
                f"Cannot format SD Card: Device is {state}.\n\nEnsure USB debugging is enabled and authorized on your phone screen.",
                parent=self
            )
            return

        self.enqueue_log("Scanning for adoptable storage disks...", "INFO")
        disks = self.backend.list_disks()
        if not disks:
            self.enqueue_log("No removable disks found from 'sm list-disks'.", "ERROR")
            messagebox.showerror(
                "No SD Card Found",
                "No adoptable or removable storage disks were detected by Android.\n\n"
                "Please verify that an SD card is physically inserted into your phone.",
                parent=self
            )
            return

        chosen_disk = disks[0]
        if len(disks) > 1:
            self.enqueue_log(f"Multiple disks detected: {disks}. Using primary disk {chosen_disk}.", "WARNING")

        dlg = PartitionConfirmDialog(self, chosen_disk)
        self.wait_window(dlg)

        if not dlg.result:
            self.enqueue_log("SD card partition cancelled by user.", "WARNING")
            return

        threading.Thread(target=self.mount_sd_worker, args=(chosen_disk,), daemon=True).start()

    def mount_sd_worker(self, disk_id):
        self.ui_queue.put(("SET_BUSY", True))
        self.ui_queue.put(("PROGRESS_INDETERMINATE", f"Formatting & partitioning {disk_id} as adopted storage... (do not unplug USB)"))

        success, msg = self.backend.partition_disk_private(disk_id)
        if not success:
            self.ui_queue.put(("PROGRESS_STOP", "Partition failed"))
            self.ui_queue.put(("SET_BUSY", False))
            self.ui_queue.put(("ALERT", ("error", "Partition Failed", f"Failed to format SD card:\n{msg}")))
            return

        self.ui_queue.put(("LOG", ("Partition command finished. Waiting for Android to mount new volume...", "INFO")))

        max_attempts = 18
        found_uuid = None

        for attempt in range(1, max_attempts + 1):
            status_text = f"Waiting for adopted volume to appear... (Checking {attempt}/{max_attempts})"
            self.ui_queue.put(("PROGRESS_INDETERMINATE", status_text))
            self.ui_queue.put(("LOG", (f"Checking sm list-volumes (attempt {attempt}/{max_attempts})...", "INFO")))

            time.sleep(10)

            volumes = self.backend.list_volumes()
            uuid_cand = self.backend.parse_adopted_uuid(volumes)
            if uuid_cand:
                found_uuid = uuid_cand
                self.ui_queue.put(("LOG", (f"Adopted volume detected! UUID: {found_uuid}", "SUCCESS")))
                break

        self.ui_queue.put(("PROGRESS_STOP", "Ready"))
        self.ui_queue.put(("SET_BUSY", False))

        if found_uuid:
            self.ui_queue.put(("SET_UUID", found_uuid))
            self.ui_queue.put(("ALERT", ("info", "Mount Successful!", f"SD Card successfully mounted as Adopted Internal Storage!\n\nDetected UUID: {found_uuid}\n\nYou can now proceed to Step 2 to move apps and content!")))
        else:
            self.ui_queue.put(("ALERT", ("warning", "Volume Mount Timed Out", "Partition command succeeded, but the new volume UUID did not mount within 3 minutes.\n\nTry clicking 'Detect UUID' manually in a few moments.")))

    # -----------------------------------------------------------------------
    # Primary Action 2: Move All Apps and Content to SD Card
    # -----------------------------------------------------------------------
    def on_move_all_clicked(self):
        uuid_val = self.uuid_var.get().strip()
        if not uuid_val:
            messagebox.showwarning("Missing UUID", "Please complete Step 1 or specify an adopted SD card UUID first.", parent=self)
            return

        state, info, _ = self.backend.check_connection()
        if state != "Connected":
            messagebox.showerror("Device Not Ready", f"Device is {state}. Please check USB connection.", parent=self)
            return

        confirm = messagebox.askyesno(
            "Confirm Batch Migration",
            f"Ready to migrate apps and storage to SD Card ({uuid_val}):\n\n"
            "1. All 3rd-party apps will be moved to the adopted SD card.\n"
            "2. Primary shared storage (photos, media, downloads) will be migrated.\n\n"
            "This may take a few minutes depending on app size. Continue?",
            parent=self
        )
        if not confirm:
            return

        threading.Thread(target=self.move_all_worker, args=(uuid_val,), daemon=True).start()

    def move_all_worker(self, uuid_val):
        self.ui_queue.put(("SET_BUSY", True))
        self.ui_queue.put(("LOG", ("Starting batch migration of apps and primary storage...", "INFO")))

        packages = self.backend.list_third_party_packages()
        total_pkgs = len(packages)

        if total_pkgs == 0:
            self.ui_queue.put(("LOG", ("No 3rd-party packages found on device.", "WARNING")))
        else:
            self.ui_queue.put(("PROGRESS_START", total_pkgs))
            success_count = 0
            fail_count = 0

            for idx, pkg in enumerate(packages, start=1):
                prog_msg = f"Moving app {idx} of {total_pkgs}: {pkg}"
                self.ui_queue.put(("PROGRESS_UPDATE", (idx, total_pkgs, prog_msg)))

                ok, msg = self.backend.move_package(pkg, uuid_val)
                if ok:
                    success_count += 1
                else:
                    fail_count += 1

                time.sleep(0.5)

            self.ui_queue.put(("LOG", (f"Apps migration finished: {success_count} succeeded, {fail_count} skipped/failed.", "INFO")))

        # Step 2: Migrate primary shared storage
        self.ui_queue.put(("PROGRESS_INDETERMINATE", "Migrating primary shared storage to SD card (pm move-primary-storage)..."))
        self.ui_queue.put(("LOG", ("Initiating primary shared media migration...", "INFO")))

        storage_ok, storage_msg = self.backend.move_primary_storage(uuid_val)

        self.ui_queue.put(("PROGRESS_STOP", "Migration complete"))
        self.ui_queue.put(("SET_BUSY", False))

        summary = (
            f"Batch Migration Finished!\n\n"
            f"• Apps Processed: {total_pkgs}\n"
            f"• Apps Moved: {success_count}\n"
            f"• Primary Storage Migration: {'Success' if storage_ok else 'Failed'}\n\n"
            f"See the console log below for detailed per-app records."
        )
        self.ui_queue.put(("ALERT", ("info", "Migration Complete", summary)))

    # -----------------------------------------------------------------------
    # Secondary Controls: Single App Move & Auto-Move Daemon
    # -----------------------------------------------------------------------
    def detect_sd_uuid_thread(self):
        state, _, _ = self.backend.check_connection()
        if state != "Connected":
            messagebox.showwarning("Device Not Connected", "Please connect and authorize device first.", parent=self)
            return

        def worker():
            self.ui_queue.put(("LOG", ("Scanning sm list-volumes for adopted SD card UUID...", "INFO")))
            volumes = self.backend.list_volumes()
            uuid_found = self.backend.parse_adopted_uuid(volumes)
            if uuid_found:
                self.ui_queue.put(("SET_UUID", uuid_found))
                self.ui_queue.put(("LOG", (f"Found adopted volume UUID: {uuid_found}", "SUCCESS")))
                self.ui_queue.put(("ALERT", ("info", "UUID Detected", f"Adopted SD Card UUID found:\n{uuid_found}")))
            else:
                self.ui_queue.put(("LOG", ("No adopted private volume found in sm list-volumes.", "WARNING")))
                self.ui_queue.put(("ALERT", ("warning", "UUID Not Found", "No adopted private volume was found.\n\nMake sure the SD card has been mounted as internal storage first (Step 1).")))

        threading.Thread(target=worker, daemon=True).start()

    def refresh_app_list_thread(self):
        state, _, _ = self.backend.check_connection()
        if state != "Connected":
            return

        def worker():
            pkgs = self.backend.list_third_party_packages()
            self.ui_queue.put(("SET_APPS", pkgs))
            self.ui_queue.put(("LOG", (f"Loaded {len(pkgs)} installed 3rd-party packages.", "INFO")))

        threading.Thread(target=worker, daemon=True).start()

    def on_move_single_app_clicked(self):
        pkg = self.single_app_combo.get().strip()
        if not pkg:
            messagebox.showwarning("No App Selected", "Please select an app from the dropdown list.", parent=self)
            return

        uuid_val = self.uuid_var.get().strip()
        if not uuid_val:
            messagebox.showwarning("Missing UUID", "Please specify or detect an adopted SD card UUID first.", parent=self)
            return

        def worker():
            self.ui_queue.put(("SET_BUSY", True))
            self.ui_queue.put(("PROGRESS_INDETERMINATE", f"Moving {pkg} to SD Card..."))
            ok, msg = self.backend.move_package(pkg, uuid_val)
            self.ui_queue.put(("PROGRESS_STOP", "Ready"))
            self.ui_queue.put(("SET_BUSY", False))
            if ok:
                self.ui_queue.put(("ALERT", ("info", "Success", f"App '{pkg}' moved to SD card successfully!")))
            else:
                self.ui_queue.put(("ALERT", ("error", "Move Failed", f"Failed to move '{pkg}':\n{msg}")))

        threading.Thread(target=worker, daemon=True).start()

    def on_toggle_auto_move(self):
        is_on = self.auto_move_active.get()
        if is_on:
            uuid_val = self.uuid_var.get().strip()
            if not uuid_val:
                messagebox.showwarning("Missing UUID", "Cannot start auto-move without an adopted SD card UUID.", parent=self)
                self.auto_move_active.set(False)
                return

            self.auto_move_indicator.config(text="ON (Active)", bg="#dcfce7", fg="#15803d")
            self.enqueue_log("Auto-move background monitor ENABLED (polling every 20 seconds).", "SUCCESS")
            self.stop_auto_move_event.clear()
            self.auto_move_thread = threading.Thread(target=self.auto_move_daemon_worker, daemon=True)
            self.auto_move_thread.start()
        else:
            self.auto_move_indicator.config(text="OFF", bg="#f1f5f9", fg="#64748b")
            self.enqueue_log("Auto-move background monitor DISABLED.", "WARNING")
            self.stop_auto_move_event.set()

    def auto_move_daemon_worker(self):
        """Background thread polling for new app installs every 20 seconds."""
        known_packages = set(self.backend.list_third_party_packages())

        while not self.stop_auto_move_event.is_set():
            if self.stop_auto_move_event.wait(timeout=20):
                break

            uuid_val = self.uuid_var.get().strip()
            if not uuid_val or self.operation_in_progress:
                continue

            state, _, _ = self.backend.check_connection()
            if state != "Connected":
                continue

            current_packages = set(self.backend.list_third_party_packages())
            new_packages = current_packages - known_packages

            if new_packages:
                for pkg in new_packages:
                    self.enqueue_log(f"[Auto-Move] Detected new install: {pkg}", "INFO")
                    ok, _ = self.backend.move_package(pkg, uuid_val)
                    if ok:
                        self.enqueue_log(f"[Auto-Move] ✓ Successfully moved new app {pkg} to SD Card!", "SUCCESS")
                    else:
                        self.enqueue_log(f"[Auto-Move] ✕ Failed to auto-move new app {pkg}.", "ERROR")

                known_packages = current_packages
                self.ui_queue.put(("SET_APPS", sorted(list(current_packages))))


# ---------------------------------------------------------------------------
# Application Entry Point
# ---------------------------------------------------------------------------
def main():
    app = StoMountApp()
    app.mainloop()


if __name__ == "__main__":
    main()
