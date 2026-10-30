"""
Tkinter GUI launcher for iNexus.
Provides interactive database selection, auto-discovery from an extraction
directory, tunable correlation parameters, and a live execution console.
"""
import os
import sys
import threading
import webbrowser
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from .constants import (
    TOOL_NAME, TOOL_VERSION,
    DEFAULT_CLUSTER_RADIUS_M, DEFAULT_CLUSTER_TIME_GAP_HRS,
    DEFAULT_INTERP_WINDOW_SECS, DEFAULT_PLACE_GPS_REJECT_M,
    DEFAULT_MIN_STAY_MINUTES,
)


# Standard filenames (and flattened extraction-tool aliases) to look for during Auto-Scan
_SOURCE_SPECS = [
    ("cache_db",     "Cache.sqlite",          "Location Track & Visits",               ["cache.sqlite", "cache__com.apple.routined.sqlite"]),
    ("local",        "Local.sqlite",          "Routined Learned Visits / LOIs",        ["local.sqlite", "Local__com.apple.routined.sqlite"]),
    ("cloud",        "Cloud-V2.sqlite",       "iCloud Synced Places & Visits",         ["cloud-v2.sqlite", "cloud.sqlite"]),
    ("photos",       "Photos.sqlite",         "Photo/Video Assets",                    ["photos.sqlite", "photos__photodata.sqlite"]),
    ("knowledgec",   "knowledgeC.db",         "App Foreground/Background Usage",       ["knowledgec.db"]),
    ("sms",          "sms.db",                "iMessage & SMS Messages",               ["sms.db"]),
    ("calls",        "CallHistory.storedata", "Native & CallKit VoIP Call Logs",       ["callhistory.storedata"]),
    ("addressbook",  "AddressBook.sqlitedb",  "Contacts for Phone/Email Resolution",   ["addressbook.sqlitedb"]),
    ("interactions", "interactionC.db",       "CoreDuet Siri App Interactions",        ["interactionc.db"]),
]


class _StdoutRedirector:
    """Redirects print() statements to both the Tkinter Text widget and stdout."""
    def __init__(self, text_widget, orig_stdout):
        self.text_widget = text_widget
        self.orig_stdout = orig_stdout

    def write(self, msg):
        if self.orig_stdout:
            self.orig_stdout.write(msg)
        self.text_widget.after(0, self._append, msg)

    def _append(self, msg):
        self.text_widget.configure(state="normal")
        self.text_widget.insert("end", msg)
        self.text_widget.see("end")
        self.text_widget.configure(state="disabled")

    def flush(self):
        if self.orig_stdout:
            self.orig_stdout.flush()


class iNexusGUI:
    def __init__(self, root, run_callback):
        self.root = root
        self.run_callback = run_callback
        self.root.title(f"{TOOL_NAME} v{TOOL_VERSION} — Forensic Artifact Correlator")
        self.root.geometry("980x820")
        self.root.minsize(880, 720)

        # Cyberpunk / Forensic Dark Palette
        self.bg_dark = "#0f172a"
        self.bg_card = "#1e293b"
        self.bg_input = "#0b1120"
        self.fg_main = "#f8fafc"
        self.fg_muted = "#94a3b8"
        self.accent_cyan = "#06b6d4"
        self.accent_green = "#10b981"

        self.root.configure(bg=self.bg_dark)
        self._configure_styles()

        self.source_enabled = {}
        self.source_paths = {}
        self.last_report_path = None

        self._build_ui()

    def _configure_styles(self):
        style = ttk.Style()
        style.theme_use("clam")
        style.configure(".", background=self.bg_dark, foreground=self.fg_main, font=("Segoe UI", 9))
        style.configure("TFrame", background=self.bg_dark)
        style.configure("Card.TFrame", background=self.bg_card, relief="flat")
        style.configure("TLabel", background=self.bg_dark, foreground=self.fg_main)
        style.configure("Card.TLabel", background=self.bg_card, foreground=self.fg_main)
        style.configure("Muted.TLabel", background=self.bg_card, foreground=self.fg_muted, font=("Segoe UI", 8))
        style.configure("Header.TLabel", background=self.bg_dark, foreground=self.accent_cyan, font=("Segoe UI", 14, "bold"))
        style.configure("Section.TLabel", background=self.bg_card, foreground=self.accent_cyan, font=("Segoe UI", 10, "bold"))
        style.configure("TCheckbutton", background=self.bg_card, foreground=self.fg_main, font=("Consolas", 9, "bold"))
        style.map("TCheckbutton", background=[("active", self.bg_card)])
        style.configure("TEntry", fieldbackground=self.bg_input, foreground=self.fg_main, insertcolor=self.fg_main)
        style.configure("TButton", background="#334155", foreground=self.fg_main, borderwidth=0, padding=(8, 4))
        style.map("TButton", background=[("active", "#475569")])
        style.configure("Accent.TButton", background=self.accent_cyan, foreground="#0f172a", font=("Segoe UI", 10, "bold"), padding=(14, 6))
        style.map("Accent.TButton", background=[("active", "#22d3ee")])
        style.configure("Scan.TButton", background="#3b82f6", foreground="#ffffff", font=("Segoe UI", 9, "bold"), padding=(10, 4))
        style.map("Scan.TButton", background=[("active", "#60a5fa")])

    def _build_ui(self):
        # ── Top Header Bar ────────────────────────────────────────────────────
        header = ttk.Frame(self.root, padding=(16, 10))
        header.pack(fill="x")

        ttk.Label(header, text=f"⚡ {TOOL_NAME} v{TOOL_VERSION}", style="Header.TLabel").pack(side="left")
        ttk.Label(
            header,
            text="Multi-Source iOS Location & Artifact Correlation Engine",
            foreground=self.fg_muted,
        ).pack(side="left", padx=(12, 0), pady=(4, 0))

        ttk.Button(
            header,
            text="📂 Auto-Scan Extraction Folder…",
            style="Scan.TButton",
            command=self._auto_scan_folder,
        ).pack(side="right")

        # ── Main Content Container ────────────────────────────────────────────
        main_frame = ttk.Frame(self.root, padding=(16, 4))
        main_frame.pack(fill="both", expand=True)

        # 1. Database Sources Card
        db_card = ttk.Frame(main_frame, style="Card.TFrame", padding=12)
        db_card.pack(fill="x", pady=(0, 8))

        top_db_row = ttk.Frame(db_card, style="Card.TFrame")
        top_db_row.pack(fill="x", pady=(0, 6))
        ttk.Label(top_db_row, text="1. Database Sources (Select any combination)", style="Section.TLabel").pack(side="left")
        ttk.Button(top_db_row, text="Clear All", command=self._clear_all_sources).pack(side="right")

        grid_frame = ttk.Frame(db_card, style="Card.TFrame")
        grid_frame.pack(fill="x")
        grid_frame.columnconfigure(2, weight=1)

        for idx, (dest, label, desc, _) in enumerate(_SOURCE_SPECS):
            enabled_var = tk.BooleanVar(value=False)
            path_var = tk.StringVar(value="")
            self.source_enabled[dest] = enabled_var
            self.source_paths[dest] = path_var

            cb = ttk.Checkbutton(grid_frame, text=label, variable=enabled_var)
            cb.grid(row=idx, column=0, sticky="w", padx=(0, 8), pady=2)

            desc_lbl = ttk.Label(grid_frame, text=desc, style="Muted.TLabel")
            desc_lbl.grid(row=idx, column=1, sticky="w", padx=(0, 10), pady=2)

            entry = ttk.Entry(grid_frame, textvariable=path_var)
            entry.grid(row=idx, column=2, sticky="ew", padx=(0, 6), pady=2)

            # Auto-check when user types or pastes a path
            path_var.trace_add("write", lambda *_, d=dest: self._on_path_changed(d))

            btn = ttk.Button(
                grid_frame,
                text="Browse…",
                command=lambda d=dest, l=label: self._browse_db(d, l),
            )
            btn.grid(row=idx, column=3, sticky="e", pady=2)

        # 2. Middle Split: Case Metadata & Options (Left) + Parameters (Right)
        mid_frame = ttk.Frame(main_frame)
        mid_frame.pack(fill="x", pady=(0, 8))
        mid_frame.columnconfigure(0, weight=3)
        mid_frame.columnconfigure(1, weight=2)

        # Left Card: Output, Case Info, Recovery & HEIC
        meta_card = ttk.Frame(mid_frame, style="Card.TFrame", padding=12)
        meta_card.grid(row=0, column=0, sticky="nsew", padx=(0, 4))
        meta_card.columnconfigure(1, weight=1)

        ttk.Label(meta_card, text="2. Output & Case Metadata", style="Section.TLabel").grid(
            row=0, column=0, columnspan=3, sticky="w", pady=(0, 6)
        )

        self.output_var = tk.StringVar(value=os.path.abspath("location_report.html"))
        self.case_var = tk.StringVar(value="")
        self.examiner_var = tk.StringVar(value="")
        self.notes_var = tk.StringVar(value="")
        self.dcim_var = tk.StringVar(value="")
        self.recover_var = tk.BooleanVar(value=False)
        self.heic_var = tk.BooleanVar(value=False)
        self.jpeg_q_var = tk.IntVar(value=85)
        self.thumbnails_var = tk.StringVar(value="")
        self.carto_key_var = tk.StringVar(value="")
        if os.path.exists("carto_key.txt"):
            try:
                with open("carto_key.txt", "r", encoding="utf-8") as f:
                    self.carto_key_var.set(f.read().strip())
            except Exception:
                pass

        self._add_labeled_entry(meta_card, 7, "CARTO API Key:", self.carto_key_var)
        self._add_labeled_entry(meta_card, 1, "Output HTML:", self.output_var, browse_save=True)
        self._add_labeled_entry(meta_card, 2, "Case Number:", self.case_var)
        self._add_labeled_entry(meta_card, 3, "Examiner:", self.examiner_var)
        self._add_labeled_entry(meta_card, 4, "Case Notes:", self.notes_var)
        self._add_labeled_entry(meta_card, 5, "DCIM Folder:", self.dcim_var, browse_dir=True)
        self._add_labeled_entry(meta_card, 6, "V2 Thumbnails:", self.thumbnails_var, browse_thumbs=True)

        flags_row = ttk.Frame(meta_card, style="Card.TFrame")
        flags_row.grid(row=8, column=0, columnspan=3, sticky="w", pady=(8, 0))
        ttk.Checkbutton(
            flags_row,
            text="Recover Deleted SQLite Freelist Rows (-recover-deleted)",
            variable=self.recover_var,
        ).pack(anchor="w")
        ttk.Checkbutton(
            flags_row,
            text="Batch Convert DCIM HEIC to JPEG (-convert-heic)",
            variable=self.heic_var,
        ).pack(anchor="w", pady=(2, 0))

        # Right Card: Correlation & Clustering Parameters
        param_card = ttk.Frame(mid_frame, style="Card.TFrame", padding=12)
        param_card.grid(row=0, column=1, sticky="nsew", padx=(4, 0))
        param_card.columnconfigure(1, weight=1)

        top_param = ttk.Frame(param_card, style="Card.TFrame")
        top_param.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        ttk.Label(top_param, text="3. Correlation Parameters", style="Section.TLabel").pack(side="left")
        ttk.Button(top_param, text="Reset Defaults", command=self._reset_defaults).pack(side="right")

        self.radius_var = tk.DoubleVar(value=DEFAULT_CLUSTER_RADIUS_M)
        self.visit_var = tk.DoubleVar(value=DEFAULT_CLUSTER_TIME_GAP_HRS)
        self.window_var = tk.DoubleVar(value=DEFAULT_INTERP_WINDOW_SECS)
        self.reject_var = tk.DoubleVar(value=DEFAULT_PLACE_GPS_REJECT_M)
        self.minstay_var = tk.DoubleVar(value=DEFAULT_MIN_STAY_MINUTES)
        self.start_date_var = tk.StringVar(value="")
        self.end_date_var = tk.StringVar(value="")

        self._add_param_row(param_card, 1, "Cluster Radius (m):", self.radius_var)
        self._add_param_row(param_card, 2, "Visit Merge Gap (hrs):", self.visit_var)
        self._add_param_row(param_card, 3, "Interp Window (±sec):", self.window_var)
        self._add_param_row(param_card, 4, "GPS Reject Dist (m):", self.reject_var)
        self._add_param_row(param_card, 5, "Min Stay Duration (min):", self.minstay_var)
        self._add_param_row(param_card, 6, "HEIC JPEG Quality (1-100):", self.jpeg_q_var)
        self._add_param_row(param_card, 7, "Start Date (YYYY-MM-DD):", self.start_date_var)
        self._add_param_row(param_card, 8, "End Date (YYYY-MM-DD):", self.end_date_var)

        # 3. Action Bar & Console Log
        action_bar = ttk.Frame(main_frame, padding=(0, 4))
        action_bar.pack(fill="x")

        self.run_btn = ttk.Button(
            action_bar,
            text="▶ Run Correlation & Build Report",
            style="Accent.TButton",
            command=self._start_run,
        )
        self.run_btn.pack(side="left")

        self.open_btn = ttk.Button(
            action_bar,
            text="🌐 Open Report in Browser",
            command=self._open_report,
            state="disabled",
        )
        self.open_btn.pack(side="left", padx=(10, 0))

        self.status_lbl = ttk.Label(action_bar, text="Ready.", foreground=self.fg_muted)
        self.status_lbl.pack(side="right")

        log_card = ttk.Frame(main_frame, style="Card.TFrame", padding=8)
        log_card.pack(fill="both", expand=True, pady=(4, 8))

        self.console = tk.Text(
            log_card,
            bg=self.bg_input,
            fg="#38bdf8",
            insertbackground=self.fg_main,
            font=("Consolas", 9),
            relief="flat",
            state="disabled",
            height=10,
        )
        scroll = ttk.Scrollbar(log_card, orient="vertical", command=self.console.yview)
        self.console.configure(yscrollcommand=scroll.set)
        self.console.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

    def _add_labeled_entry(self, parent, row, label, var, browse_save=False, browse_dir=False, browse_thumbs=False):
        ttk.Label(parent, text=label, style="Card.TLabel").grid(row=row, column=0, sticky="w", padx=(0, 8), pady=2)
        ttk.Entry(parent, textvariable=var).grid(row=row, column=1, sticky="ew", padx=(0, 6), pady=2)
        if browse_save:
            ttk.Button(parent, text="Browse…", command=self._browse_output).grid(row=row, column=2, pady=2)
        elif browse_dir:
            ttk.Button(parent, text="Browse…", command=self._browse_dcim).grid(row=row, column=2, pady=2)
        elif browse_thumbs:
            ttk.Button(parent, text="Browse…", command=self._browse_thumbnails).grid(row=row, column=2, pady=2)

    def _add_param_row(self, parent, row, label, var):
        ttk.Label(parent, text=label, style="Card.TLabel").grid(row=row, column=0, sticky="w", padx=(0, 8), pady=3)
        ttk.Entry(parent, textvariable=var, width=10).grid(row=row, column=1, sticky="e", pady=3)

    def _browse_thumbnails(self):
        path = filedialog.askdirectory(title="Select PhotoData/Thumbnails/V2 Folder")
        if path:
            self.thumbnails_var.set(path)

    def _on_path_changed(self, dest):
        val = self.source_paths[dest].get().strip()
        self.source_enabled[dest].set(bool(val))

    def _browse_db(self, dest, label):
        path = filedialog.askopenfilename(
            title=f"Select {label}",
            filetypes=[("SQLite Databases", "*.sqlite *.db *.sqlitedb *.storedata *.*"), ("All Files", "*.*")],
        )
        if path:
            self.source_paths[dest].set(path)
            self.source_enabled[dest].set(True)

    def _browse_output(self):
        path = filedialog.asksaveasfilename(
            title="Save HTML Report As",
            defaultextension=".html",
            initialfile="location_report.html",
            filetypes=[("HTML Report", "*.html"), ("All Files", "*.*")],
        )
        if path:
            self.output_var.set(path)

    def _browse_dcim(self):
        path = filedialog.askdirectory(title="Select DCIM Folder")
        if path:
            self.dcim_var.set(path)
            self.heic_var.set(True)

    def _clear_all_sources(self):
        for dest in self.source_paths:
            self.source_paths[dest].set("")
            self.source_enabled[dest].set(False)

    def _reset_defaults(self):
        self.radius_var.set(DEFAULT_CLUSTER_RADIUS_M)
        self.visit_var.set(DEFAULT_CLUSTER_TIME_GAP_HRS)
        self.window_var.set(DEFAULT_INTERP_WINDOW_SECS)
        self.reject_var.set(DEFAULT_PLACE_GPS_REJECT_M)
        self.minstay_var.set(DEFAULT_MIN_STAY_MINUTES)
        self.jpeg_q_var.set(85)

    def _auto_scan_folder(self):
        folder = filedialog.askdirectory(title="Select Root Extraction Folder to Scan for Databases")
        if not folder:
            return

        # ── Proactively set report output and DCIM paths into the extraction folder ──
        default_report_path = os.path.join(folder, "location_report.html")
        self.output_var.set(os.path.abspath(default_report_path))

        # Look for a DCIM folder inside the extraction directory automatically
        potential_dcim = os.path.join(folder, "DCIM")
        if os.path.isdir(potential_dcim):
            self.dcim_var.set(potential_dcim)
            self.heic_var.set(True)

        found_count = 0
        lookup = {}
        for dest, _, _, aliases in _SOURCE_SPECS:
            for alias in aliases:
                lookup[alias.lower()] = dest

        for root_dir, dirs, files in os.walk(folder):
            for d in dirs:
                if d.upper() == "DCIM" and not self.dcim_var.get():
                    dcim_path = os.path.join(root_dir, d)
                    self.dcim_var.set(dcim_path)
                    self.heic_var.set(True)
            for fname in files:
                lower = fname.lower()
                if lower in lookup:
                    dest = lookup[lower]
                    full_path = os.path.join(root_dir, fname)
                    existing = self.source_paths[dest].get()
                    if not existing or (
                        os.path.exists(full_path)
                        and os.path.exists(existing)
                        and os.path.getsize(full_path) > os.path.getsize(existing)
                    ):
                        self.source_paths[dest].set(full_path)
                        self.source_enabled[dest].set(True)
                        found_count += 1

        active_sources = len([k for k, v in self.source_enabled.items() if v.get()])
        self.status_lbl.configure(text=f"Auto-scan complete: populated {active_sources} database(s). Report set to target extraction folder.")
        if found_count == 0:
            messagebox.showinfo("Auto-Scan Complete", "No matching standard iOS databases were found in that folder.")

    def _build_namespace(self):
        ns = argparse.Namespace()
        for dest, _, _, _ in _SOURCE_SPECS:
            if self.source_enabled[dest].get() and self.source_paths[dest].get().strip():
                setattr(ns, dest, self.source_paths[dest].get().strip())
            else:
                setattr(ns, dest, None)

        ns.output_flag = self.output_var.get().strip() or "location_report.html"
        ns.case = self.case_var.get().strip() or None
        ns.examiner = self.examiner_var.get().strip() or None
        ns.notes = self.notes_var.get().strip() or None
        ns.dcim = self.dcim_var.get().strip() or None
        ns.thumbnails_dir = self.thumbnails_var.get().strip() or None  # <--- Dedicated V2 thumbnails path
        ns.convert_heic = bool(self.heic_var.get())
        ns.recover_deleted = bool(self.recover_var.get())
        ns.jpeg_quality = int(self.jpeg_q_var.get())
        ns.radius = float(self.radius_var.get())
        ns.visit = float(self.visit_var.get())
        ns.window = float(self.window_var.get())
        ns.reject = float(self.reject_var.get())
        ns.minstay = float(self.minstay_var.get())
        ns.gui = True
        ns.start_date = self.start_date_var.get().strip() or None
        ns.end_date = self.end_date_var.get().strip() or None
        return ns

    def _start_run(self):
        try:
            args = self._build_namespace()
        except ValueError as e:
            messagebox.showerror("Invalid Parameter", f"Please check your numeric parameters:\n{e}")
            return

        # Clear console
        self.console.configure(state="normal")
        self.console.delete("1.0", "end")
        self.console.configure(state="disabled")

        self.run_btn.configure(state="disabled")
        self.open_btn.configure(state="disabled")
        self.status_lbl.configure(text="Running analysis pipeline…", foreground=self.accent_cyan)

        def _worker():
            orig_stdout = sys.stdout
            sys.stdout = _StdoutRedirector(self.console, orig_stdout)
            try:
                self.run_callback(args)
                self.last_report_path = os.path.abspath(args.output_flag)
                self.root.after(0, self._on_run_success)
            except SystemExit:
                self.root.after(0, self._on_run_failed, "Run aborted (see console log for details).")
            except Exception as exc:
                print(f"\n✗ UNEXPECTED ERROR: {exc}")
                self.root.after(0, self._on_run_failed, str(exc))
            finally:
                sys.stdout = orig_stdout

        threading.Thread(target=_worker, daemon=True).start()

    def _on_run_success(self):
        self.run_btn.configure(state="normal")
        self.open_btn.configure(state="normal")
        self.status_lbl.configure(text="✓ Report generated successfully!", foreground=self.accent_green)

    def _on_run_failed(self, err_msg):
        self.run_btn.configure(state="normal")
        self.status_lbl.configure(text="✗ Run failed.", foreground="#ef4444")
        messagebox.showerror("Execution Error", err_msg)

    def _open_report(self):
        if self.last_report_path and os.path.exists(self.last_report_path):
            webbrowser.open(f"file://{self.last_report_path}")


import argparse  # needed for _build_namespace


def launch_gui(run_callback):
    root = tk.Tk()
    app = iNexusGUI(root, run_callback)
    root.mainloop()
