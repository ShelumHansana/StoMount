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

# ---------------------------------------------------------------------------
# High-DPI / HD Display Awareness for Windows
# Eliminates blurry text/DWM scaling and renders razor-sharp HD typography
# ---------------------------------------------------------------------------
if sys.platform == "win32":
    try:
        import ctypes
        # Set Per-Monitor DPI Awareness (V2) for Windows 10/11
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            import ctypes
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass

import tkinter as tk
from tkinter import ttk, messagebox, filedialog

# Application Metadata
APP_NAME = "StoMount"
APP_VERSION = "1.2.0"
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

    def move_package_to_internal(self, package_name):
        """Run 'adb shell pm move-package <pkg> internal' to revert app to internal storage."""
        self.log(f"Reverting {package_name} to internal phone storage...", "INFO")
        success, stdout, stderr = self.run_adb(["shell", "pm", "move-package", package_name, "internal"], timeout=180)
        output = (stdout + "\n" + stderr).strip()
        if "Success" in output or (success and "failure" not in output.lower()):
            self.log(f"✓ {package_name}: Reverted to internal storage!", "SUCCESS")
            return True, output
        else:
            self.log(f"✕ {package_name}: Revert failed ({output})", "ERROR")
            return False, output

    def move_primary_storage_to_internal(self):
        """Run 'adb shell pm move-primary-storage internal' to restore primary storage to phone."""
        self.log("Restoring primary shared media & storage back to phone internal storage...", "INFO")
        success, stdout, stderr = self.run_adb(["shell", "pm", "move-primary-storage", "internal"], timeout=300)
        output = (stdout + "\n" + stderr).strip()
        if "Success" in output or (success and "failure" not in output.lower()):
            self.log(f"✓ Primary storage restored to internal storage! {output}", "SUCCESS")
            return True, output
        else:
            self.log(f"✕ Primary storage restore failed! {output}", "ERROR")
            return False, output

    def partition_disk_public(self, disk_id):
        """Run 'adb shell sm partition <diskid> public' to revert SD card to standard portable storage."""
        self.log(f"Formatting disk {disk_id} as standard portable storage ('sm partition public')...", "INFO")
        success, stdout, stderr = self.run_adb(["shell", "sm", "partition", disk_id, "public"], timeout=120)
        output = (stdout + "\n" + stderr).strip()
        if success and "error" not in output.lower():
            self.log(f"✓ Successfully restored {disk_id} to portable SD card storage.", "SUCCESS")
            return True, f"Successfully formatted {disk_id} back to portable storage."
        return False, output or "Failed to partition disk as public."

    def forget_volume(self, uuid_val):
        """Run 'adb shell sm forget <uuid>' to clean up volume records."""
        if not uuid_val:
            return True, ""
        self.log(f"Cleaning up adopted volume {uuid_val} records...", "INFO")
        success, stdout, stderr = self.run_adb(["shell", "sm", "forget", uuid_val], timeout=30)
        return success, (stdout + "\n" + stderr).strip()


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

        # Top banner with HD App Icon
        header = tk.Frame(self, bg="#0f172a", padx=18, pady=14)
        header.pack(fill=tk.X)

        self.guide_icon_img = None
        for candidate_dir in [getattr(sys, "_MEIPASS", None), os.path.dirname(os.path.abspath(__file__))]:
            if candidate_dir:
                p = os.path.join(candidate_dir, "app_icon_48.png")
                if os.path.exists(p):
                    try:
                        self.guide_icon_img = tk.PhotoImage(file=p)
                        break
                    except Exception:
                        pass

        if self.guide_icon_img:
            icon_box = tk.Label(header, image=self.guide_icon_img, bg="#0f172a")
            icon_box.pack(side=tk.LEFT, padx=(0, 12))

        title_box = tk.Frame(header, bg="#0f172a")
        title_box.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        tk.Label(title_box, text="📖 How to Use StoMount", font=("Segoe UI", 13, "bold"), bg="#0f172a", fg="#38bdf8").pack(anchor="w")
        tk.Label(title_box, text="Step-by-step instructions to turn your SD card into fast internal storage.", font=("Segoe UI", 9), bg="#0f172a", fg="#94a3b8").pack(anchor="w", pady=(2, 0))

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
        self.title("⚠️ Confirmation - Adopt SD Card as Internal Storage")
        self.disk_id = disk_id
        self.result = False

        self.geometry("580x490")
        self.minsize(540, 450)
        self.resizable(True, True)
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
        w = 580
        h = 490
        x = px + max(0, (pw - w) // 2)
        y = py + max(0, (ph - h) // 2)
        self.geometry(f"{w}x{h}+{x}+{y}")

    def setup_ui(self):
        self.configure(bg="#f8fafc")

        # 1. Header (pinned to top)
        header_frame = tk.Frame(self, bg="#fef2f2", padx=18, pady=12, relief=tk.SOLID, bd=1)
        header_frame.pack(fill=tk.X, side=tk.TOP)

        title_lbl = tk.Label(
            header_frame,
            text="⚠️ Confirm SD Card Formatting",
            font=("Segoe UI", 11, "bold"),
            bg="#fef2f2",
            fg="#991b1b"
        )
        title_lbl.pack(anchor="w")

        subtitle_lbl = tk.Label(
            header_frame,
            text="Adopting storage will format the card and erase all existing content.",
            font=("Segoe UI", 8),
            bg="#fef2f2",
            fg="#b91c1c"
        )
        subtitle_lbl.pack(anchor="w", pady=(2, 0))

        # 2. Bottom buttons (pinned to bottom)
        btn_frame = tk.Frame(self, bg="#f1f5f9", padx=16, pady=12)
        btn_frame.pack(fill=tk.X, side=tk.BOTTOM)

        self.cancel_btn = ttk.Button(btn_frame, text="Cancel", command=self.on_cancel)
        self.cancel_btn.pack(side=tk.RIGHT, padx=(8, 0))

        self.proceed_btn = tk.Button(
            btn_frame,
            text="Format & Adopt SD Card",
            font=("Segoe UI", 9, "bold"),
            bg="#e2e8f0",
            fg="#94a3b8",
            disabledforeground="#94a3b8",
            activebackground="#b91c1c",
            activeforeground="#ffffff",
            relief=tk.FLAT,
            padx=16,
            pady=6,
            state=tk.DISABLED,
            command=self.on_proceed
        )
        self.proceed_btn.pack(side=tk.RIGHT)

        # 3. Body content (fills center space)
        body_frame = tk.Frame(self, bg="#f8fafc", padx=20, pady=12)
        body_frame.pack(fill=tk.BOTH, expand=True)

        # Summary box
        info_box = tk.Frame(body_frame, bg="#ffffff", relief=tk.SOLID, bd=1, padx=12, pady=10)
        info_box.pack(fill=tk.X, pady=(0, 12))

        info_text = (
            f"Target Disk: {self.disk_id}\n"
            "• All existing files, photos, videos, and music will be permanently erased.\n"
            "• The card will become encrypted internal storage for apps and data.\n"
            "• Please ensure you have backed up any needed files to a computer first."
        )
        tk.Label(
            info_box,
            text=info_text,
            font=("Segoe UI", 8),
            bg="#ffffff",
            fg="#334155",
            justify=tk.LEFT,
            wraplength=510
        ).pack(anchor="w")

        tk.Label(
            body_frame,
            text="Choose an action to proceed:",
            font=("Segoe UI", 9, "bold"),
            bg="#f8fafc",
            fg="#0f172a"
        ).pack(anchor="w", pady=(0, 8))

        self.choice_var = tk.StringVar(value="cancel")

        # Option 1 Card: Safe / Cancel
        self.opt1_frame = tk.Frame(body_frame, bg="#ffffff", relief=tk.SOLID, bd=1, padx=12, pady=8, cursor="hand2")
        self.opt1_frame.pack(fill=tk.X, pady=(0, 8))

        rb1 = tk.Radiobutton(
            self.opt1_frame,
            text="No, keep my SD card safe (Do not format)",
            value="cancel",
            variable=self.choice_var,
            command=self.on_choice_change,
            font=("Segoe UI", 9, "bold"),
            bg="#ffffff",
            activebackground="#ffffff",
            fg="#1e293b",
            selectcolor="#ffffff",
            cursor="hand2"
        )
        rb1.pack(anchor="w")
        lbl1 = tk.Label(
            self.opt1_frame,
            text="Cancel the operation and return to StoMount without touching the card.",
            font=("Segoe UI", 8),
            bg="#ffffff",
            fg="#64748b",
            cursor="hand2"
        )
        lbl1.pack(anchor="w", padx=(24, 0))

        # Option 2 Card: Confirm / Format
        self.opt2_frame = tk.Frame(body_frame, bg="#ffffff", relief=tk.SOLID, bd=1, padx=12, pady=8, cursor="hand2")
        self.opt2_frame.pack(fill=tk.X, pady=(0, 6))

        rb2 = tk.Radiobutton(
            self.opt2_frame,
            text="Yes, format this SD card as adopted internal storage",
            value="format",
            variable=self.choice_var,
            command=self.on_choice_change,
            font=("Segoe UI", 9, "bold"),
            bg="#ffffff",
            activebackground="#ffffff",
            fg="#b91c1c",
            selectcolor="#ffffff",
            cursor="hand2"
        )
        rb2.pack(anchor="w")
        lbl2 = tk.Label(
            self.opt2_frame,
            text="I understand that all data on this SD card will be permanently erased.",
            font=("Segoe UI", 8),
            bg="#ffffff",
            fg="#64748b",
            cursor="hand2"
        )
        lbl2.pack(anchor="w", padx=(24, 0))

        # Bind card clicks
        for w_item in (self.opt1_frame, lbl1):
            w_item.bind("<Button-1>", lambda e: self.set_choice("cancel"))
        for w_item in (self.opt2_frame, lbl2):
            w_item.bind("<Button-1>", lambda e: self.set_choice("format"))

    def set_choice(self, val):
        self.choice_var.set(val)
        self.on_choice_change()

    def on_choice_change(self):
        if self.choice_var.get() == "format":
            self.proceed_btn.config(
                state=tk.NORMAL,
                bg="#dc2626",
                fg="#ffffff",
                cursor="hand2"
            )
            self.opt2_frame.config(bg="#fef2f2")
            self.opt1_frame.config(bg="#ffffff")
        else:
            self.proceed_btn.config(
                state=tk.DISABLED,
                bg="#e2e8f0",
                fg="#94a3b8",
                cursor=""
            )
            self.opt1_frame.config(bg="#f8fafc")
            self.opt2_frame.config(bg="#ffffff")

    def on_proceed(self):
        if self.choice_var.get() == "format":
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
        self.geometry("1000x800")
        self.minsize(880, 700)

        # Cache of loaded PhotoImages to prevent Python GC de-allocation
        self.icons = {}

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

        # Apply HD crisp background
        self.configure(bg="#f0f5fa")
        self.setup_styles()

        # Threading Queue for thread-safe UI updates
        self.ui_queue = queue.Queue()

        # Initialize Backend
        self.backend = ADBBackend(log_callback=self.enqueue_log)
        self.stored_uuid = self.backend.get_saved_uuid()

        # State Variables
        self.conn_state = tk.StringVar(value="Not Connected")
        self.device_info_str = tk.StringVar(value="No devices found via USB or Wi-Fi")
        self.uuid_var = tk.StringVar(value=self.stored_uuid)
        self.detected_disk_var = tk.StringVar(value="Waiting for USB connection...")
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

    def get_ui_icon(self, filename):
        """Retrieve and cache HD Tkinter PhotoImage from PyInstaller bundle or local path."""
        if filename in self.icons:
            return self.icons[filename]
        for candidate_dir in [getattr(sys, "_MEIPASS", None), os.path.dirname(os.path.abspath(__file__))]:
            if candidate_dir:
                p = os.path.join(candidate_dir, filename)
                if os.path.exists(p):
                    try:
                        img = tk.PhotoImage(file=p)
                        self.icons[filename] = img
                        return img
                    except Exception:
                        pass
        return None

    def setup_styles(self):
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except Exception:
            pass

        style.configure("Card.TFrame", background="#ffffff", relief="flat")
        style.configure("TProgressbar", thickness=6, troughcolor="#e2e8f0", background="#2563eb")
        style.configure("TCombobox", padding=4)

    def create_widgets(self):
        # ===================================================================
        # 1. Top Navigation & Status Bar with HD Icon
        # ===================================================================
        top_bar = tk.Frame(self, bg="#081a36", padx=20, pady=11)
        top_bar.pack(fill=tk.X, side=tk.TOP)

        # Brand box with embedded App Icon
        brand_box = tk.Frame(top_bar, bg="#081a36")
        brand_box.pack(side=tk.LEFT)

        app_logo_img = self.get_ui_icon("app_icon_40.png")
        if app_logo_img:
            icon_lbl = tk.Label(brand_box, image=app_logo_img, bg="#081a36")
            icon_lbl.pack(side=tk.LEFT, padx=(0, 10))

        app_title = tk.Label(
            brand_box, text=APP_NAME, font=("Segoe UI", 16, "bold"),
            bg="#081a36", fg="#38bdf8"
        )
        app_title.pack(side=tk.LEFT)

        sep_lbl = tk.Label(
            brand_box, text="|", font=("Segoe UI", 14),
            bg="#081a36", fg="#334155"
        )
        sep_lbl.pack(side=tk.LEFT, padx=10)

        tagline = tk.Label(
            brand_box, text="Android Adopted Storage Manager", font=("Segoe UI", 10),
            bg="#081a36", fg="#94a3b8"
        )
        tagline.pack(side=tk.LEFT)

        # Quick action buttons on top right
        guide_btn = tk.Button(
            top_bar, text="📖 User Guide", font=("Segoe UI", 8, "bold"),
            bg="#152744", fg="#f1f5f9", activebackground="#223b61", activeforeground="#ffffff",
            relief=tk.SOLID, bd=1, highlightbackground="#263f68", highlightcolor="#263f68",
            padx=10, pady=4, cursor="hand2", command=self.open_guide
        )
        guide_btn.pack(side=tk.RIGHT, padx=(6, 0))

        adb_cfg_btn = tk.Button(
            top_bar, text="⚙ ADB Path", font=("Segoe UI", 8, "bold"),
            bg="#152744", fg="#f1f5f9", activebackground="#223b61", activeforeground="#ffffff",
            relief=tk.SOLID, bd=1, highlightbackground="#263f68", highlightcolor="#263f68",
            padx=10, pady=4, cursor="hand2", command=self.open_adb_config_dialog
        )
        adb_cfg_btn.pack(side=tk.RIGHT, padx=(6, 0))

        refresh_conn_btn = tk.Button(
            top_bar, text="↻ Refresh", font=("Segoe UI", 8, "bold"),
            bg="#152744", fg="#f1f5f9", activebackground="#223b61", activeforeground="#ffffff",
            relief=tk.SOLID, bd=1, highlightbackground="#263f68", highlightcolor="#263f68",
            padx=10, pady=4, cursor="hand2", command=self.manual_refresh_connection
        )
        refresh_conn_btn.pack(side=tk.RIGHT)
        ToolTip(refresh_conn_btn, "Immediately re-checks USB connection & SD card status.")

        # ===================================================================
        # Main Workspace Container
        # ===================================================================
        main_content = tk.Frame(self, bg="#f0f5fa", padx=20, pady=12)
        main_content.pack(fill=tk.BOTH, expand=True)

        # ===================================================================
        # 2. Connection Status Card (Pristine White Card)
        # ===================================================================
        status_card = tk.Frame(
            main_content, bg="#ffffff",
            highlightbackground="#e2e8f0", highlightcolor="#e2e8f0", highlightthickness=1,
            bd=0, padx=16, pady=8
        )
        status_card.pack(fill=tk.X, pady=(0, 10))

        status_left = tk.Frame(status_card, bg="#ffffff")
        status_left.pack(side=tk.LEFT)

        usb_ico = self.get_ui_icon("icon_usb.png")
        if usb_ico:
            tk.Label(status_left, image=usb_ico, bg="#ffffff").pack(side=tk.LEFT, padx=(0, 8))

        self.status_dot_lbl = tk.Label(
            status_left, text="● Not Connected", font=("Segoe UI", 9, "bold"),
            bg="#ffffff", fg="#16a34a"
        )
        self.status_dot_lbl.pack(side=tk.LEFT, padx=(0, 8))

        tk.Label(status_left, text="|", font=("Segoe UI", 9), bg="#ffffff", fg="#cbd5e1").pack(side=tk.LEFT, padx=(0, 8))

        self.device_label = tk.Label(
            status_left, textvariable=self.device_info_str,
            font=("Segoe UI", 9), bg="#ffffff", fg="#64748b"
        )
        self.device_label.pack(side=tk.LEFT)

        # Right Pill Badge: e.g. Waiting for USB connection...
        self.status_pill_frame = tk.Frame(
            status_card, bg="#e0f2fe",
            highlightbackground="#bae6fd", highlightcolor="#bae6fd", highlightthickness=1,
            bd=0, padx=10, pady=3
        )
        self.status_pill_frame.pack(side=tk.RIGHT)

        spin_ico = self.get_ui_icon("icon_spinner.png")
        if spin_ico:
            self.spin_lbl = tk.Label(self.status_pill_frame, image=spin_ico, bg="#e0f2fe")
            self.spin_lbl.pack(side=tk.LEFT, padx=(0, 5))
        else:
            self.spin_lbl = None

        self.disk_badge = tk.Label(
            self.status_pill_frame, textvariable=self.detected_disk_var,
            font=("Segoe UI", 8, "bold"), bg="#e0f2fe", fg="#0369a1"
        )
        self.disk_badge.pack(side=tk.LEFT)

        # ===================================================================
        # 3. Adopted SD Card UUID Card
        # ===================================================================
        uuid_card = tk.Frame(
            main_content, bg="#ffffff",
            highlightbackground="#e2e8f0", highlightcolor="#e2e8f0", highlightthickness=1,
            bd=0, padx=16, pady=8
        )
        uuid_card.pack(fill=tk.X, pady=(0, 10))

        tk.Label(
            uuid_card, text="Adopted SD Card UUID:", font=("Segoe UI", 9, "bold"),
            bg="#ffffff", fg="#0f172a"
        ).pack(side=tk.LEFT, padx=(0, 8))

        self.uuid_entry = tk.Entry(
            uuid_card, textvariable=self.uuid_var, width=38,
            font=("Segoe UI", 9), bg="#ffffff", relief=tk.SOLID, bd=1,
            highlightthickness=0
        )
        self.uuid_entry.pack(side=tk.LEFT, padx=(0, 8), ipady=3)
        self.uuid_var.trace_add("write", lambda *args: self.on_uuid_changed())

        detect_btn = tk.Button(
            uuid_card, text="🔍 Detect UUID", font=("Segoe UI", 8, "bold"),
            bg="#e0f2fe", fg="#0284c7", activebackground="#bae6fd", activeforeground="#0369a1",
            relief=tk.SOLID, bd=1, highlightbackground="#bae6fd", highlightcolor="#bae6fd",
            padx=10, pady=3, cursor="hand2", command=self.detect_sd_uuid_thread
        )
        detect_btn.pack(side=tk.LEFT, padx=(0, 6))
        ToolTip(detect_btn, "Inspects 'sm list-volumes' to detect any currently adopted SD card UUID.")

        save_uuid_btn = tk.Button(
            uuid_card, text="💾 Save UUID", font=("Segoe UI", 8, "bold"),
            bg="#e0f2fe", fg="#0284c7", activebackground="#bae6fd", activeforeground="#0369a1",
            relief=tk.SOLID, bd=1, highlightbackground="#bae6fd", highlightcolor="#bae6fd",
            padx=10, pady=3, cursor="hand2", command=self.save_current_uuid
        )
        save_uuid_btn.pack(side=tk.LEFT, padx=(0, 8))
        ToolTip(save_uuid_btn, "Save this UUID permanently so you don't have to detect it again.")

        self.uuid_status_pill = tk.Label(
            uuid_card, text="⚠️ No UUID Detected", font=("Segoe UI", 8, "bold"),
            bg="#fef3c7", fg="#b45309", relief=tk.SOLID, bd=1,
            highlightbackground="#fde68a", highlightcolor="#fde68a",
            padx=10, pady=3
        )
        self.uuid_status_pill.pack(side=tk.RIGHT)

        # ===================================================================
        # 4. Primary Guided Workflow (Side-by-Side Steps 1 & 2)
        # ===================================================================
        actions_header = tk.Frame(main_content, bg="#f0f5fa")
        actions_header.pack(fill=tk.X, pady=(2, 6))

        wf_ico = self.get_ui_icon("icon_workflow.png")
        if wf_ico:
            tk.Label(actions_header, image=wf_ico, bg="#f0f5fa").pack(side=tk.LEFT, padx=(0, 6))

        tk.Label(
            actions_header, text="Primary Workflow (Follow Steps 1 & 2)",
            font=("Segoe UI", 10, "bold"), bg="#f0f5fa", fg="#1e293b"
        ).pack(side=tk.LEFT)

        actions_grid = tk.Frame(main_content, bg="#f0f5fa")
        actions_grid.pack(fill=tk.X, pady=(0, 10))
        actions_grid.columnconfigure(0, weight=1, uniform="col")
        actions_grid.columnconfigure(1, weight=1, uniform="col")

        # -----------------------------
        # STEP 1 CARD
        # -----------------------------
        card1 = tk.Frame(
            actions_grid, bg="#ffffff",
            highlightbackground="#e2e8f0", highlightcolor="#e2e8f0", highlightthickness=1,
            bd=0, padx=16, pady=12
        )
        card1.grid(row=0, column=0, sticky="nsew", padx=(0, 6))

        c1_top = tk.Frame(card1, bg="#ffffff")
        c1_top.pack(fill=tk.X, pady=(0, 8))

        tk.Label(
            c1_top, text="STEP 1", font=("Segoe UI", 8, "bold"),
            bg="#2563eb", fg="#ffffff", padx=8, pady=2
        ).pack(side=tk.LEFT)

        self.c1_status_pill = tk.Label(
            c1_top, text="▶ Start Here", font=("Segoe UI", 8, "bold"),
            bg="#eff6ff", fg="#2563eb", padx=8, pady=2,
            relief=tk.SOLID, bd=1, highlightbackground="#dbeafe", highlightcolor="#dbeafe"
        )
        self.c1_status_pill.pack(side=tk.RIGHT)

        c1_body = tk.Frame(card1, bg="#ffffff")
        c1_body.pack(fill=tk.X, pady=(0, 10))

        sd_ico = self.get_ui_icon("card_icon_sd.png")
        if sd_ico:
            tk.Label(c1_body, image=sd_ico, bg="#ffffff").pack(side=tk.LEFT, padx=(0, 12))

        c1_txt = tk.Frame(c1_body, bg="#ffffff")
        c1_txt.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        tk.Label(
            c1_txt, text="Mount SD as Internal Storage",
            font=("Segoe UI", 11, "bold"), bg="#ffffff", fg="#0f172a"
        ).pack(anchor="w", pady=(0, 2))

        tk.Label(
            c1_txt,
            text='Formats the removable microSD card into\nencrypted adopted storage ("sdm partition private").',
            font=("Segoe UI", 8), bg="#ffffff", fg="#64748b", justify=tk.LEFT
        ).pack(anchor="w")

        tk.Label(
            c1_txt,
            text="⚠️ Erases all data on the card!",
            font=("Segoe UI", 8, "bold"), bg="#ffffff", fg="#d97706"
        ).pack(anchor="w", pady=(2, 0))

        self.mount_btn = tk.Button(
            card1,
            text="⚡ Mount SD Card as Internal Storage",
            font=("Segoe UI", 9, "bold"),
            bg="#2563eb", fg="#ffffff",
            activebackground="#1d4ed8", activeforeground="#ffffff",
            disabledforeground="#94a3b8",
            relief=tk.FLAT, pady=8, cursor="hand2",
            command=self.on_mount_sd_clicked
        )
        self.mount_btn.pack(fill=tk.X)

        # -----------------------------
        # STEP 2 CARD
        # -----------------------------
        card2 = tk.Frame(
            actions_grid, bg="#ffffff",
            highlightbackground="#e2e8f0", highlightcolor="#e2e8f0", highlightthickness=1,
            bd=0, padx=16, pady=12
        )
        card2.grid(row=0, column=1, sticky="nsew", padx=(6, 0))

        c2_top = tk.Frame(card2, bg="#ffffff")
        c2_top.pack(fill=tk.X, pady=(0, 8))

        tk.Label(
            c2_top, text="STEP 2", font=("Segoe UI", 8, "bold"),
            bg="#16a34a", fg="#ffffff", padx=8, pady=2
        ).pack(side=tk.LEFT)

        self.c2_status_pill = tk.Label(
            c2_top, text="❗️ Requires Step 1", font=("Segoe UI", 8, "bold"),
            bg="#fee2e2", fg="#dc2626", padx=8, pady=2,
            relief=tk.SOLID, bd=1, highlightbackground="#fecaca", highlightcolor="#fecaca"
        )
        self.c2_status_pill.pack(side=tk.RIGHT)

        c2_body = tk.Frame(card2, bg="#ffffff")
        c2_body.pack(fill=tk.X, pady=(0, 10))

        apps_ico = self.get_ui_icon("card_icon_apps.png")
        if apps_ico:
            tk.Label(c2_body, image=apps_ico, bg="#ffffff").pack(side=tk.LEFT, padx=(0, 12))

        c2_txt = tk.Frame(c2_body, bg="#ffffff")
        c2_txt.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        tk.Label(
            c2_txt, text="Move All Apps & Content to SD",
            font=("Segoe UI", 11, "bold"), bg="#ffffff", fg="#0f172a"
        ).pack(anchor="w", pady=(0, 2))

        tk.Label(
            c2_txt,
            text="Batch moves all installed 3rd-party apps to the\nadopted SD card, then migrates primary storage\nfor photos, downloads, and media.",
            font=("Segoe UI", 8), bg="#ffffff", fg="#64748b", justify=tk.LEFT
        ).pack(anchor="w")

        self.move_all_btn = tk.Button(
            card2,
            text="🚀 Move All Apps & Content to SD Card",
            font=("Segoe UI", 9, "bold"),
            bg="#e2e8f0", fg="#94a3b8",
            activebackground="#047857", activeforeground="#ffffff",
            disabledforeground="#94a3b8",
            relief=tk.FLAT, pady=8, cursor="hand2",
            state=tk.DISABLED,
            command=self.on_move_all_clicked
        )
        self.move_all_btn.pack(fill=tk.X)
        self.move_all_tooltip = ToolTip(self.move_all_btn, "Requires an adopted SD Card UUID to be detected first.")

        # ===================================================================
        # 5. Additional Storage Controls Card
        # ===================================================================
        sec_card = tk.Frame(
            main_content, bg="#ffffff",
            highlightbackground="#e2e8f0", highlightcolor="#e2e8f0", highlightthickness=1,
            bd=0, padx=16, pady=10
        )
        sec_card.pack(fill=tk.X, pady=(0, 10))

        sec_header = tk.Frame(sec_card, bg="#ffffff")
        sec_header.pack(fill=tk.X, pady=(0, 6))

        gear_ico = self.get_ui_icon("icon_settings.png")
        if gear_ico:
            tk.Label(sec_header, image=gear_ico, bg="#ffffff").pack(side=tk.LEFT, padx=(0, 6))

        tk.Label(
            sec_header, text="Additional Storage Controls",
            font=("Segoe UI", 9, "bold"), bg="#ffffff", fg="#1e293b"
        ).pack(side=tk.LEFT)

        # Row 1: Move Single App with Combobox & Action Buttons
        row1 = tk.Frame(sec_card, bg="#ffffff")
        row1.pack(fill=tk.X, pady=(0, 6))

        tk.Label(
            row1, text="Move Single App:", font=("Segoe UI", 9, "bold"),
            bg="#ffffff", fg="#1e293b"
        ).pack(side=tk.LEFT, padx=(0, 8))

        # Search filter entry
        self.app_filter_var = tk.StringVar()
        self.app_filter_var.trace_add("write", self.filter_app_list)

        self.single_app_combo = ttk.Combobox(row1, width=34, state="readonly")
        self.single_app_combo.pack(side=tk.LEFT, padx=(0, 8))

        self.refresh_apps_btn = tk.Button(
            row1, text="↻ Refresh List", font=("Segoe UI", 8, "bold"),
            bg="#eff6ff", fg="#0284c7", activebackground="#dbeafe", activeforeground="#0369a1",
            relief=tk.SOLID, bd=1, highlightbackground="#bae6fd", highlightcolor="#bae6fd",
            padx=10, pady=3, cursor="hand2", command=self.refresh_app_list_thread
        )
        self.refresh_apps_btn.pack(side=tk.LEFT, padx=(0, 6))

        self.move_single_btn = tk.Button(
            row1, text="➔ Move to SD", font=("Segoe UI", 8, "bold"),
            bg="#eff6ff", fg="#0284c7", activebackground="#dbeafe", activeforeground="#0369a1",
            relief=tk.SOLID, bd=1, highlightbackground="#bae6fd", highlightcolor="#bae6fd",
            padx=10, pady=3, cursor="hand2", command=self.on_move_single_app_clicked
        )
        self.move_single_btn.pack(side=tk.LEFT, padx=(0, 6))
        ToolTip(self.move_single_btn, "Moves the selected app to the adopted SD card.")

        self.move_single_internal_btn = tk.Button(
            row1, text="⬅ Move to Internal", font=("Segoe UI", 8, "bold"),
            bg="#eff6ff", fg="#0284c7", activebackground="#dbeafe", activeforeground="#0369a1",
            relief=tk.SOLID, bd=1, highlightbackground="#bae6fd", highlightcolor="#bae6fd",
            padx=10, pady=3, cursor="hand2", command=self.on_move_single_internal_clicked
        )
        self.move_single_internal_btn.pack(side=tk.LEFT)
        ToolTip(self.move_single_internal_btn, "Reverts the selected app back to phone internal storage.")

        self.apps_count_lbl = tk.Label(row1, text="", font=("Segoe UI", 8), bg="#ffffff", fg="#64748b")
        self.apps_count_lbl.pack(side=tk.RIGHT)

        # Row 2: Auto-move newly installed apps
        row2 = tk.Frame(sec_card, bg="#ffffff")
        row2.pack(fill=tk.X, pady=(4, 0))

        self.auto_move_chk = ttk.Checkbutton(
            row2,
            text="Auto-move newly installed apps to SD Card (scans every 20 seconds in background)",
            variable=self.auto_move_active,
            command=self.on_toggle_auto_move
        )
        self.auto_move_chk.pack(side=tk.LEFT)

        self.auto_move_indicator = tk.Label(
            row2, text="ⓘ OFF", font=("Segoe UI", 8, "bold"),
            bg="#f1f5f9", fg="#64748b", padx=8, pady=2,
            relief=tk.SOLID, bd=1, highlightbackground="#e2e8f0", highlightcolor="#e2e8f0"
        )
        self.auto_move_indicator.pack(side=tk.LEFT, padx=(10, 0))

        # ===================================================================
        # 6. Revert & Reset to Original Storage Card (Red Accented Card)
        # ===================================================================
        revert_card = tk.Frame(
            main_content, bg="#ffffff",
            highlightbackground="#fca5a5", highlightcolor="#fca5a5", highlightthickness=1,
            bd=0, padx=16, pady=10
        )
        revert_card.pack(fill=tk.X, pady=(0, 10))

        tk.Label(
            revert_card,
            text="🔄 Revert & Reset Storage (Restore to Original Situation)",
            font=("Segoe UI", 9, "bold"), bg="#ffffff", fg="#dc2626"
        ).pack(anchor="w", pady=(0, 2))

        tk.Label(
            revert_card,
            text="Need to revert back to default? Move apps and media back to internal storage, and restore the SD card as standard portable storage (FAT32/exFAT).",
            font=("Segoe UI", 8), bg="#ffffff", fg="#64748b", justify=tk.LEFT
        ).pack(anchor="w", pady=(0, 8))

        revert_btn_row = tk.Frame(revert_card, bg="#ffffff")
        revert_btn_row.pack(fill=tk.X)

        self.revert_apps_btn = tk.Button(
            revert_btn_row, text="📥 Move All Apps Back to Internal",
            font=("Segoe UI", 8, "bold"), bg="#ffffff", fg="#1e293b",
            activebackground="#f1f5f9", activeforeground="#0f172a",
            relief=tk.SOLID, bd=1, highlightbackground="#cbd5e1", highlightcolor="#cbd5e1",
            padx=10, pady=4, cursor="hand2",
            command=self.on_revert_all_apps_clicked
        )
        self.revert_apps_btn.pack(side=tk.LEFT, padx=(0, 8))
        ToolTip(self.revert_apps_btn, "Moves all 3rd-party apps and primary media back to phone internal storage.")

        self.revert_sd_btn = tk.Button(
            revert_btn_row, text="💾 Format SD as Standard Portable",
            font=("Segoe UI", 8, "bold"), bg="#ffffff", fg="#dc2626",
            activebackground="#fee2e2", activeforeground="#991b1b",
            relief=tk.SOLID, bd=1, highlightbackground="#fca5a5", highlightcolor="#fca5a5",
            padx=10, pady=4, cursor="hand2",
            command=self.on_format_sd_public_clicked
        )
        self.revert_sd_btn.pack(side=tk.LEFT, padx=(0, 8))
        ToolTip(self.revert_sd_btn, "Formats the SD card back to portable public storage ('sm partition public') so it can be read on PCs again.")

        self.full_reset_btn = tk.Button(
            revert_btn_row, text="⚡ Complete Storage Reset Wizard",
            font=("Segoe UI", 8, "bold"), bg="#ef4444", fg="#ffffff",
            activebackground="#dc2626", activeforeground="#ffffff",
            relief=tk.FLAT, padx=14, pady=5, cursor="hand2",
            command=self.on_full_reset_wizard_clicked
        )
        self.full_reset_btn.pack(side=tk.RIGHT)
        ToolTip(self.full_reset_btn, "Automated 1-click restore: moves apps and media back, formats SD as portable, and clears StoMount session.")

        # ===================================================================
        # 7. Progress & Status Row
        # ===================================================================
        self.progress_frame = tk.Frame(main_content, bg="#f0f5fa")
        self.progress_frame.pack(fill=tk.X, pady=(0, 4))

        prog_top = tk.Frame(self.progress_frame, bg="#f0f5fa")
        prog_top.pack(fill=tk.X)

        self.progress_lbl = tk.Label(
            prog_top,
            text="✓ Ready",
            font=("Segoe UI", 9, "bold"),
            bg="#f0f5fa",
            fg="#16a34a"
        )
        self.progress_lbl.pack(side=tk.LEFT)

        self.progress_pct_lbl = tk.Label(
            prog_top,
            text="",
            font=("Segoe UI", 8, "bold"),
            bg="#f0f5fa",
            fg="#475569"
        )
        self.progress_pct_lbl.pack(side=tk.RIGHT)

        self.progress_bar = ttk.Progressbar(self.progress_frame, orient=tk.HORIZONTAL, mode="determinate")
        self.progress_bar.pack(fill=tk.X, pady=(2, 0))

        # ===================================================================
        # 8. Real-Time ADB Console / Log Panel
        # ===================================================================
        log_header = tk.Frame(main_content, bg="#f0f5fa")
        log_header.pack(fill=tk.X, pady=(4, 4))

        con_ico = self.get_ui_icon("icon_console.png")
        if con_ico:
            tk.Label(log_header, image=con_ico, bg="#f0f5fa").pack(side=tk.LEFT, padx=(0, 6))

        tk.Label(
            log_header, text="ADB Command Log & Real-Time Console",
            font=("Segoe UI", 9, "bold"), bg="#f0f5fa", fg="#334155"
        ).pack(side=tk.LEFT)

        copy_btn = tk.Button(
            log_header, text="📋 Copy All", font=("Segoe UI", 8),
            bg="#f1f5f9", fg="#334155", activebackground="#e2e8f0",
            relief=tk.SOLID, bd=1, highlightbackground="#cbd5e1", highlightcolor="#cbd5e1",
            padx=8, pady=2, cursor="hand2", command=self.copy_log_to_clipboard
        )
        copy_btn.pack(side=tk.RIGHT, padx=(6, 0))

        clear_btn = tk.Button(
            log_header, text="🗑 Clear Log", font=("Segoe UI", 8),
            bg="#f1f5f9", fg="#334155", activebackground="#e2e8f0",
            relief=tk.SOLID, bd=1, highlightbackground="#cbd5e1", highlightcolor="#cbd5e1",
            padx=8, pady=2, cursor="hand2", command=self.clear_log
        )
        clear_btn.pack(side=tk.RIGHT)

        log_container = tk.Frame(
            main_content, bg="#0b162c",
            highlightbackground="#1e293b", highlightcolor="#1e293b", highlightthickness=1,
            bd=0
        )
        log_container.pack(fill=tk.BOTH, expand=True)

        self.log_text = tk.Text(
            log_container,
            bg="#0b162c",
            fg="#e2e8f0",
            insertbackground="#ffffff",
            font=("Consolas", 9),
            wrap=tk.WORD,
            padx=10,
            pady=8,
            height=7
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
                    self.progress_lbl.config(text=text, fg="#0f172a")
                elif event_type == "PROGRESS_INDETERMINATE":
                    text = data
                    self.progress_bar.config(mode="indeterminate")
                    self.progress_bar.start(15)
                    self.progress_pct_lbl.config(text="Working...")
                    self.progress_lbl.config(text=text, fg="#0284c7")
                elif event_type == "PROGRESS_STOP":
                    text = data
                    self.progress_bar.stop()
                    self.progress_bar.config(mode="determinate", value=0)
                    self.progress_pct_lbl.config(text="")
                    self.progress_lbl.config(text=text or "✓ Ready", fg="#16a34a")
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
        self.move_single_internal_btn.config(state=state)
        self.revert_apps_btn.config(state=state)
        self.revert_sd_btn.config(state=state)
        self.full_reset_btn.config(state=state)
        self.uuid_entry.config(state="disabled" if busy else "normal")
        self.on_uuid_changed()

    def on_uuid_changed(self):
        uuid_val = self.uuid_var.get().strip()
        if not self.operation_in_progress:
            if uuid_val:
                self.move_all_btn.config(state=tk.NORMAL, bg="#059669", fg="#ffffff")
                self.move_all_tooltip.set_text("Move all 3rd-party apps and primary storage to SD card: " + uuid_val)
                self.uuid_status_pill.config(
                    text="✓ Adopted UUID Set", bg="#dcfce7", fg="#15803d",
                    highlightbackground="#bbf7d0", highlightcolor="#bbf7d0"
                )
                self.c1_status_pill.config(
                    text="✓ SD Card Adopted", bg="#dcfce7", fg="#15803d",
                    highlightbackground="#bbf7d0", highlightcolor="#bbf7d0"
                )
                self.c2_status_pill.config(
                    text="Ready to Migrate", bg="#dbeafe", fg="#1d4ed8",
                    highlightbackground="#bfdbfe", highlightcolor="#bfdbfe"
                )
            else:
                self.move_all_btn.config(state=tk.DISABLED, bg="#e2e8f0", fg="#94a3b8")
                self.move_all_tooltip.set_text("Requires an adopted SD card UUID. Complete Step 1 or enter a valid UUID.")
                self.uuid_status_pill.config(
                    text="⚠️ No UUID Detected", bg="#fef3c7", fg="#b45309",
                    highlightbackground="#fde68a", highlightcolor="#fde68a"
                )
                self.c1_status_pill.config(
                    text="▶ Start Here", bg="#eff6ff", fg="#2563eb",
                    highlightbackground="#dbeafe", highlightcolor="#dbeafe"
                )
                self.c2_status_pill.config(
                    text="❗️ Requires Step 1", bg="#fee2e2", fg="#dc2626",
                    highlightbackground="#fecaca", highlightcolor="#fecaca"
                )
        else:
            self.move_all_btn.config(state=tk.DISABLED, bg="#e2e8f0", fg="#94a3b8")

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
        self.status_dot_lbl.config(text="● Checking...", fg="#0284c7")
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
            self.status_dot_lbl.config(text="● Connected", fg="#16a34a")
            if disks:
                self.detected_disk_var.set(f"SD Card: {', '.join(disks)}")
                self.status_pill_frame.config(bg="#dcfce7", highlightbackground="#bbf7d0", highlightcolor="#bbf7d0")
                self.disk_badge.config(bg="#dcfce7", fg="#15803d")
            else:
                self.detected_disk_var.set("No SD card disk detected")
                self.status_pill_frame.config(bg="#f1f5f9", highlightbackground="#e2e8f0", highlightcolor="#e2e8f0")
                self.disk_badge.config(bg="#f1f5f9", fg="#64748b")
            if self.spin_lbl:
                self.spin_lbl.pack_forget()
        elif state == "Unauthorized":
            self.status_dot_lbl.config(text="● Unauthorized", fg="#d97706")
            self.detected_disk_var.set("Unlock phone to detect SD")
            self.status_pill_frame.config(bg="#fef3c7", highlightbackground="#fde68a", highlightcolor="#fde68a")
            self.disk_badge.config(bg="#fef3c7", fg="#b45309")
            if self.spin_lbl:
                self.spin_lbl.pack_forget()
        elif state == "Offline":
            self.status_dot_lbl.config(text="● Offline", fg="#dc2626")
            self.detected_disk_var.set("Device offline")
            self.status_pill_frame.config(bg="#fee2e2", highlightbackground="#fecaca", highlightcolor="#fecaca")
            self.disk_badge.config(bg="#fee2e2", fg="#dc2626")
            if self.spin_lbl:
                self.spin_lbl.pack_forget()
        else:
            self.status_dot_lbl.config(text="● Not Connected", fg="#16a34a")
            self.detected_disk_var.set("Waiting for USB connection...")
            self.status_pill_frame.config(bg="#e0f2fe", highlightbackground="#bae6fd", highlightcolor="#bae6fd")
            self.disk_badge.config(bg="#e0f2fe", fg="#0369a1")
            if self.spin_lbl:
                self.spin_lbl.pack(side=tk.LEFT, padx=(0, 5))

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

            self.auto_move_indicator.config(
                text="ⓘ ACTIVE", bg="#dcfce7", fg="#15803d",
                highlightbackground="#bbf7d0", highlightcolor="#bbf7d0"
            )
            self.enqueue_log("Auto-move background monitor ENABLED (polling every 20 seconds).", "SUCCESS")
            self.stop_auto_move_event.clear()
            self.auto_move_thread = threading.Thread(target=self.auto_move_daemon_worker, daemon=True)
            self.auto_move_thread.start()
        else:
            self.auto_move_indicator.config(
                text="ⓘ OFF", bg="#f1f5f9", fg="#64748b",
                highlightbackground="#e2e8f0", highlightcolor="#e2e8f0"
            )
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

    # -----------------------------------------------------------------------
    # Revert & Reset Storage Handlers
    # -----------------------------------------------------------------------
    def on_move_single_internal_clicked(self):
        pkg = self.single_app_combo.get().strip()
        if not pkg:
            messagebox.showwarning("No App Selected", "Please select an app from the dropdown list.", parent=self)
            return

        state, info, _ = self.backend.check_connection()
        if state != "Connected":
            messagebox.showerror("Device Not Connected", f"Device is {state}. Please check USB connection.", parent=self)
            return

        def worker():
            self.ui_queue.put(("SET_BUSY", True))
            self.ui_queue.put(("PROGRESS_INDETERMINATE", f"Reverting {pkg} to phone internal storage..."))
            ok, msg = self.backend.move_package_to_internal(pkg)
            self.ui_queue.put(("PROGRESS_STOP", "Ready"))
            self.ui_queue.put(("SET_BUSY", False))
            if ok:
                self.ui_queue.put(("ALERT", ("info", "App Reverted", f"'{pkg}' was successfully moved back to phone internal storage!")))
            else:
                self.ui_queue.put(("ALERT", ("error", "Revert Failed", f"Failed to revert '{pkg}':\n{msg}")))

        threading.Thread(target=worker, daemon=True).start()

    def on_revert_all_apps_clicked(self):
        state, info, _ = self.backend.check_connection()
        if state != "Connected":
            messagebox.showerror("Device Not Connected", f"Device is {state}. Please check USB connection.", parent=self)
            return

        confirm = messagebox.askyesno(
            "Revert Apps to Internal Storage",
            "This will move all 3rd-party apps and primary media storage back to your phone's internal memory.\n\n"
            "Please ensure your phone has sufficient free internal storage.\n\n"
            "Do you want to proceed?",
            parent=self
        )
        if not confirm:
            return

        def worker():
            self.ui_queue.put(("SET_BUSY", True))
            self.ui_queue.put(("LOG", ("Starting migration of apps back to internal phone storage...", "INFO")))

            packages = self.backend.list_third_party_packages()
            total_pkgs = len(packages)

            if total_pkgs > 0:
                self.ui_queue.put(("PROGRESS_START", total_pkgs))
                success_count = 0
                fail_count = 0

                for idx, pkg in enumerate(packages, start=1):
                    prog_msg = f"Moving app {idx} of {total_pkgs} back to internal: {pkg}"
                    self.ui_queue.put(("PROGRESS_UPDATE", (idx, total_pkgs, prog_msg)))

                    ok, _ = self.backend.move_package_to_internal(pkg)
                    if ok:
                        success_count += 1
                    else:
                        fail_count += 1
                    time.sleep(0.4)

                self.ui_queue.put(("LOG", (f"Apps revert finished: {success_count} succeeded, {fail_count} skipped/failed.", "INFO")))

            # Revert primary shared storage
            self.ui_queue.put(("PROGRESS_INDETERMINATE", "Restoring primary media storage back to internal phone storage..."))
            storage_ok, storage_msg = self.backend.move_primary_storage_to_internal()

            self.ui_queue.put(("PROGRESS_STOP", "Revert Complete"))
            self.ui_queue.put(("SET_BUSY", False))

            summary = (
                f"Revert Operation Finished!\n\n"
                f"• Apps Processed: {total_pkgs}\n"
                f"• Primary Media Restored: {'Success' if storage_ok else 'Failed'}\n\n"
                f"All eligible apps and media have been moved back to phone internal storage."
            )
            self.ui_queue.put(("ALERT", ("info", "Storage Reverted", summary)))

        threading.Thread(target=worker, daemon=True).start()

    def on_format_sd_public_clicked(self):
        state, info, _ = self.backend.check_connection()
        if state != "Connected":
            messagebox.showerror("Device Not Connected", f"Device is {state}. Please check USB connection.", parent=self)
            return

        disks = self.backend.list_disks()
        if not disks:
            messagebox.showerror("No SD Card", "No SD card disk was found via ADB.", parent=self)
            return

        chosen_disk = disks[0]

        confirm = messagebox.askyesno(
            "Format SD Card to Portable",
            f"This will reformat disk '{chosen_disk}' as standard portable storage (FAT32/exFAT).\n\n"
            "⚠️ Important: Any remaining files on the SD card will be erased!\n"
            "Make sure you have already moved your apps back to internal storage.\n\n"
            "Do you want to reformat this card as portable storage?",
            parent=self
        )
        if not confirm:
            return

        def worker():
            self.ui_queue.put(("SET_BUSY", True))
            self.ui_queue.put(("PROGRESS_INDETERMINATE", f"Formatting {chosen_disk} as standard portable storage..."))

            # Forget old volume records if any
            old_uuid = self.uuid_var.get().strip()
            if old_uuid:
                self.backend.forget_volume(old_uuid)

            ok, msg = self.backend.partition_disk_public(chosen_disk)

            self.ui_queue.put(("PROGRESS_STOP", "Ready"))
            self.ui_queue.put(("SET_BUSY", False))

            if ok:
                self.ui_queue.put(("SET_UUID", ""))
                self.ui_queue.put(("ALERT", ("info", "SD Card Restored", f"MicroSD Card '{chosen_disk}' is now formatted as standard portable storage!\n\nYou can now use it normally or plug it into other PCs/devices.")))
            else:
                self.ui_queue.put(("ALERT", ("error", "Format Failed", f"Failed to format as portable:\n{msg}")))

        threading.Thread(target=worker, daemon=True).start()

    def on_full_reset_wizard_clicked(self):
        state, info, _ = self.backend.check_connection()
        if state != "Connected":
            messagebox.showerror("Device Not Connected", f"Device is {state}. Please check USB connection.", parent=self)
            return

        disks = self.backend.list_disks()
        if not disks:
            messagebox.showerror("No SD Card", "No SD card disk was found via ADB.", parent=self)
            return

        chosen_disk = disks[0]

        confirm = messagebox.askyesno(
            "Complete Storage Reset Wizard",
            "This will completely reset your phone & SD card back to the original situation:\n\n"
            "1. Move all 3rd-party apps back to phone internal storage\n"
            "2. Restore primary media and downloads to internal storage\n"
            "3. Format the MicroSD card back to standard portable storage (FAT32/exFAT)\n"
            "4. Reset StoMount session\n\n"
            "⚠️ Please ensure phone internal storage has enough free space!\n\n"
            "Do you want to run the Complete Storage Reset Wizard?",
            parent=self
        )
        if not confirm:
            return

        def worker():
            self.ui_queue.put(("SET_BUSY", True))
            self.ui_queue.put(("LOG", ("==================================================", "INFO")))
            self.ui_queue.put(("LOG", ("Starting Complete Storage Reset Wizard...", "INFO")))

            # Step 1: Revert all apps
            packages = self.backend.list_third_party_packages()
            total_pkgs = len(packages)

            if total_pkgs > 0:
                self.ui_queue.put(("PROGRESS_START", total_pkgs))
                for idx, pkg in enumerate(packages, start=1):
                    prog_msg = f"[Reset 1/3] Moving app {idx} of {total_pkgs} back to internal: {pkg}"
                    self.ui_queue.put(("PROGRESS_UPDATE", (idx, total_pkgs, prog_msg)))
                    self.backend.move_package_to_internal(pkg)
                    time.sleep(0.4)

            # Step 2: Restore primary storage
            self.ui_queue.put(("PROGRESS_INDETERMINATE", "[Reset 2/3] Restoring primary shared storage to internal..."))
            self.backend.move_primary_storage_to_internal()

            # Step 3: Format SD card back to public
            self.ui_queue.put(("PROGRESS_INDETERMINATE", f"[Reset 3/3] Formatting {chosen_disk} as standard portable storage..."))
            old_uuid = self.uuid_var.get().strip()
            if old_uuid:
                self.backend.forget_volume(old_uuid)

            format_ok, format_msg = self.backend.partition_disk_public(chosen_disk)

            # Step 4: Reset StoMount session
            self.ui_queue.put(("SET_UUID", ""))
            self.ui_queue.put(("PROGRESS_STOP", "Reset Finished"))
            self.ui_queue.put(("SET_BUSY", False))

            self.ui_queue.put(("LOG", ("==================================================", "SUCCESS")))
            self.ui_queue.put(("LOG", ("Complete Storage Reset Wizard finished successfully!", "SUCCESS")))

            summary = (
                f"Storage Reset Complete!\n\n"
                f"• All apps reverted to phone internal storage\n"
                f"• Primary media restored to internal storage\n"
                f"• SD Card '{chosen_disk}' formatted as standard portable storage\n\n"
                f"Your storage is back to its original state."
            )
            self.ui_queue.put(("ALERT", ("info", "Storage Reset Complete", summary)))

        threading.Thread(target=worker, daemon=True).start()


# ---------------------------------------------------------------------------
# Application Entry Point
# ---------------------------------------------------------------------------
def main():
    app = StoMountApp()
    app.mainloop()


if __name__ == "__main__":
    main()
