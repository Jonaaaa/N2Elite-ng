"""N2Elite-ng GUI — a cross-platform Tkinter app styled after the original
N2 Elite Manager. Built on the same offline device/amiibo layers as the CLI.

Design goals: no extra dependencies (Tkinter ships with Python), fully offline,
non-blocking (device work runs in a worker thread), safe (writes confirm + are
gated behind the same logic as the CLI).
"""
from __future__ import annotations

import os
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk
from pathlib import Path

from . import __version__
from .amiibo import describe, identify, is_blank, is_empty_id, info_for_id
from .device import N2Elite
from .mfrc522 import NfcError, NfcTimeout
from .transport import TransportError, describe_ports

# Colours loosely echoing the original manager's dark slot grid.
BG = "#2b2f36"
PANEL = "#3a3f47"
ACCENT = "#4a90d9"
TEXT = "#e6e6e6"
SUBTLE = "#9aa0a6"
SLOT_EMPTY = "#333840"
SLOT_FILLED = "#2f4a6d"
SLOT_SELECTED = "#3f6da0"

# Plain-language explanations (from the N2 Elite manual) shown as button tooltips.
FUNCTION_HELP = {
    "Connect": "Open (or close) the connection to the N2 Elite USB reader. Pick the "
               "'Silicon Labs CP210x' port first, then Connect.",
    "Scan / Read": "Read the amiibo currently on the reader (the active bank) and show it "
                   "in the detail panel. Also tells you if the disc is locked or unlocked.",
    "Scan All Banks": "List every bank on the disc and show each bank's amiibo in the grid. "
                      "Click a tile to view a bank; double-click to make it active. The active "
                      "bank is marked with a green ★. (Needs the N2 unlocked.)",
    "Set Active Bank": "Make the selected bank the ACTIVE one — what a game/console sees when "
                       "you tap the disc. Select a bank tile first, or just double-click it. "
                       "(Needs the N2 unlocked.)",
    "Dump (backup)": "Save a bank to a .bin file. With a bank selected it saves that bank's "
                     "FULL 572-byte contents (including game-written data like Smash Bros. AI "
                     "or Wolf Link's level); otherwise it saves the active amiibo.",
    "Write Amiibo…": "Write ANY amiibo .bin to the selected bank — use this to ADD a new amiibo "
                     "to an empty bank or OVERWRITE an existing one. It replaces the bank's "
                     "contents, so back it up first. (Needs the N2 unlocked.)",
    "Empty Bank": "Erase all data in the selected bank, freeing the slot. This cannot be undone "
                  "unless you have a backup — it asks to confirm. (Needs the N2 unlocked.)",
    "Set Bank Count": "Set how many amiibo slots are active (1-200; 200 is the disc's limit). "
                      "The disc's Cycle button steps through this many, then wraps to slot #1. "
                      "Lowering it below a used slot does NOT erase data, but hides those slots "
                      "from games until you raise it again. (Needs the N2 unlocked.)",
    "Unlock": "Enter manager mode so the bank/write/settings functions work. A LOCKED disc just "
              "reads as a plain amiibo and hides these functions. (Standalone, without this app: "
              "hold the disc's Cycle button BEFORE tapping it to change slots.)",
    "Lock": "Protect the disc: it becomes a read-only amiibo of the active bank and hides the "
            "management functions. This is the safe 'in use' state for games and consoles.",
    "Show image": "Show the amiibo's figure picture. Fetches it once from the public amiibo "
                  "image database (the only time the app goes online), then caches it locally. "
                  "Use Settings to auto-show images or change the cache folder.",
}


class ToolTip:
    """Minimal hover tooltip for a widget (no external dependency)."""

    def __init__(self, widget, text: str):
        self.widget = widget
        self.text = text
        self.tip = None
        widget.bind("<Enter>", self._show)
        widget.bind("<Leave>", self._hide)

    def _show(self, _event=None):
        if self.tip or not self.text:
            return
        x = self.widget.winfo_rootx() + 12
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 4
        self.tip = tk.Toplevel(self.widget)
        self.tip.wm_overrideredirect(True)
        self.tip.wm_geometry(f"+{x}+{y}")
        tk.Label(self.tip, text=self.text, justify="left", bg="#ffffe0", fg="#000000",
                 relief="solid", borderwidth=1, wraplength=340,
                 font=("TkDefaultFont", 9)).pack(ipadx=4, ipady=3)

    def _hide(self, _event=None):
        if self.tip:
            self.tip.destroy()
            self.tip = None


class DeviceWorker(threading.Thread):
    """Runs device operations off the UI thread; posts results to a queue."""

    def __init__(self, out: queue.Queue):
        super().__init__(daemon=True)
        self.out = out
        self.jobs: queue.Queue = queue.Queue()
        self._stop = False

    def submit(self, name, fn):
        self.jobs.put((name, fn))

    def run(self):
        while not self._stop:
            try:
                name, fn = self.jobs.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                result = fn()
                self.out.put(("done", name, result))
            except (TransportError, NfcError, NfcTimeout, OSError, ValueError) as e:
                self.out.put(("error", name, str(e)))
            except Exception as e:  # pragma: no cover - defensive
                self.out.put(("error", name, f"unexpected: {e}"))

    def stop(self):
        self._stop = True


class N2App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"n2elite-ng {__version__} — by Jona")
        self.configure(bg=BG)
        self.geometry("1080x700")
        self.minsize(900, 600)

        self.dev: N2Elite | None = None
        self.events: queue.Queue = queue.Queue()
        self.worker = DeviceWorker(self.events)
        self.worker.start()
        self.slots: list[dict] = []
        self.selected_slot: int | None = None
        self.active_bank: int | None = None
        self.current_amiibo_id: str | None = None
        self.current_data: bytes | None = None
        self.unlocked: bool | None = None  # N2 manager mode state (None=unknown)
        self._photo = None        # popup image reference (avoid Tk GC)
        self._detail_photo = None  # inline detail-panel image reference

        from .config import Config
        from .amiibo import images
        self.cfg = Config()
        images.set_cache_dir(self.cfg.cache_dir)

        self._build_ui()
        self.after(80, self._poll_events)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.refresh_ports()

    # -- UI construction ---------------------------------------------------
    def _build_ui(self):
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("TButton", padding=(4, 2), font=("TkDefaultFont", 9))
        style.configure("Vertical.TScrollbar", troughcolor="#1e2127", background=PANEL,
                        bordercolor=BG, arrowcolor=TEXT, darkcolor=PANEL, lightcolor=PANEL,
                        relief="flat")
        style.map("Vertical.TScrollbar", background=[("active", ACCENT)])

        # Window icon (replaces Tk's default feather)
        icon_path = os.path.join(os.path.dirname(__file__), "assets", "icon.png")
        if os.path.exists(icon_path):
            try:
                self._icon_img = tk.PhotoImage(file=icon_path)
                self.iconphoto(True, self._icon_img)
            except tk.TclError:
                pass

        # Header — app name + credit (the n2-elite logo is the window/taskbar icon)
        head = tk.Frame(self, bg="#23262c")
        head.pack(fill="x")
        title = tk.Frame(head, bg="#23262c")
        title.pack(side="left", padx=(14, 0), pady=8)
        tk.Label(title, text="n2elite", bg="#23262c", fg=ACCENT,
                 font=("TkDefaultFont", 17, "bold")).pack(side="left")
        tk.Label(title, text="ng", bg="#23262c", fg="#23d174",
                 font=("TkDefaultFont", 17, "bold")).pack(side="left")
        tk.Label(head, text="amiibo / N2 manager", bg="#23262c", fg=SUBTLE,
                 font=("TkDefaultFont", 11)).pack(side="left", padx=10)
        tk.Label(head, text="by Jona", bg="#23262c", fg=SUBTLE,
                 font=("TkDefaultFont", 10, "italic")).pack(side="right", padx=18)

        top = tk.Frame(self, bg=PANEL, pady=8, padx=10)
        top.pack(fill="x")
        tk.Label(top, text="Port:", bg=PANEL, fg=TEXT).pack(side="left")
        self.port_var = tk.StringVar()
        self.port_menu = ttk.Combobox(top, textvariable=self.port_var, width=22, state="readonly")
        self.port_menu.pack(side="left", padx=(4, 6))
        ttk.Button(top, text="Refresh", command=self.refresh_ports).pack(side="left")
        self.connect_btn = ttk.Button(top, text="Connect", command=self.toggle_connect)
        self.connect_btn.pack(side="left", padx=8)
        ToolTip(self.connect_btn, FUNCTION_HELP["Connect"])
        self.status_var = tk.StringVar(value="Disconnected")
        tk.Label(top, textvariable=self.status_var, bg=PANEL, fg=SUBTLE).pack(side="right")

        # Action toolbar
        bar = tk.Frame(self, bg=BG, pady=6, padx=10)
        bar.pack(fill="x")
        self.btns: dict[str, ttk.Button] = {}
        for label, cmd in [
            ("Scan / Read", self.scan),
            ("Scan All Banks", self.scan_all_banks),
            ("Set Active Bank", self.set_active_bank),
            ("Dump (backup)", self.dump_active),
            ("Write Amiibo…", self.restore_active),
            ("Empty Bank", self.empty_bank),
            ("Set Bank Count", self.set_bank_count),
            ("Unlock", self.unlock),
            ("Lock", self.lock),
        ]:
            b = ttk.Button(bar, text=label, command=cmd, state="disabled")
            b.pack(side="left", padx=2)
            ToolTip(b, FUNCTION_HELP.get(label, ""))
            self.btns[label] = b
        self.action_btns = list(self.btns.values())
        # Image button is not a device action — enabled once an amiibo is known.
        self.image_btn = ttk.Button(bar, text="Show image", command=self.show_image,
                                    state="disabled")
        self.image_btn.pack(side="left", padx=(10, 2))
        ToolTip(self.image_btn, FUNCTION_HELP["Show image"])

        # Middle: bank slot grid (left) + amiibo detail panel (right)
        mid = tk.Frame(self, bg=BG, padx=10, pady=6)
        mid.pack(fill="both", expand=True)

        left = tk.Frame(mid, bg=BG)
        left.pack(side="left", fill="both", expand=True)
        tk.Label(left, text="Banks", bg=BG, fg=SUBTLE, anchor="w").pack(fill="x")
        # Scrollable canvas so many banks scroll within the panel, not the window.
        gwrap = tk.Frame(left, bg=BG)
        gwrap.pack(fill="both", expand=True, pady=4)
        self.grid_canvas = tk.Canvas(gwrap, bg=BG, highlightthickness=0)
        gscroll = ttk.Scrollbar(gwrap, orient="vertical", command=self.grid_canvas.yview)
        self.grid_canvas.configure(yscrollcommand=gscroll.set)
        gscroll.pack(side="right", fill="y")
        self.grid_canvas.pack(side="left", fill="both", expand=True)
        self.grid_frame = tk.Frame(self.grid_canvas, bg=BG)
        self._grid_win = self.grid_canvas.create_window((0, 0), window=self.grid_frame, anchor="nw")
        self.grid_frame.bind(
            "<Configure>",
            lambda e: self.grid_canvas.configure(scrollregion=self.grid_canvas.bbox("all")))
        self.grid_canvas.bind(
            "<Configure>",
            lambda e: self.grid_canvas.itemconfig(self._grid_win, width=e.width))

        def _over_grid(e):
            w = self.winfo_containing(e.x_root, e.y_root)
            while w is not None:
                if w is self.grid_canvas:
                    return True
                w = getattr(w, "master", None)
            return False

        def _wheel(e):
            if not _over_grid(e):
                return  # let other widgets (e.g. the log) scroll normally
            delta = 1 if getattr(e, "num", None) == 5 else -1 if getattr(e, "num", None) == 4 \
                else int(-e.delta / 120)
            self.grid_canvas.yview_scroll(delta, "units")
        for seq in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            self.bind_all(seq, _wheel, add="+")
        self._render_slots(0)

        detail = tk.Frame(mid, bg=PANEL, padx=12, pady=10, width=260)
        detail.pack(side="right", fill="y")
        detail.pack_propagate(False)
        tk.Label(detail, text="Amiibo", bg=PANEL, fg=SUBTLE, anchor="w").pack(fill="x")
        self.detail_img = tk.Label(detail, bg=PANEL, text="(read a tag)", fg=SUBTLE)
        self.detail_img.pack(pady=8)
        self.detail_info = tk.Label(detail, bg=PANEL, fg=TEXT, justify="left",
                                    anchor="nw", wraplength=232, font=("TkDefaultFont", 9))
        self.detail_info.pack(fill="both", expand=True)

        # File menu
        menubar = tk.Menu(self)
        filem = tk.Menu(menubar, tearoff=0)
        filem.add_command(label="Identify a .bin…", command=self.identify_file)
        filem.add_command(label="Decrypt a .bin…", command=lambda: self.crypto_file(False))
        filem.add_command(label="Encrypt a .bin…", command=lambda: self.crypto_file(True))
        filem.add_separator()
        filem.add_command(label="Quit", command=self._on_close)
        menubar.add_cascade(label="File", menu=filem)
        editm = tk.Menu(menubar, tearoff=0)
        editm.add_command(label="Settings…", command=self.show_settings)
        menubar.add_cascade(label="Settings", menu=editm)
        helpm = tk.Menu(menubar, tearoff=0)
        helpm.add_command(label="About", command=self.show_about)
        menubar.add_cascade(label="Help", menu=helpm)
        self.config(menu=menubar)

        # Log (with scrollbar)
        logf = tk.Frame(self, bg=BG, padx=10, pady=6)
        logf.pack(fill="x")
        tk.Label(logf, text="Log", bg=BG, fg=SUBTLE, anchor="w").pack(fill="x")
        logbox = tk.Frame(logf, bg=BG)
        logbox.pack(fill="x")
        log_scroll = ttk.Scrollbar(logbox, orient="vertical")
        log_scroll.pack(side="right", fill="y")
        self.log = tk.Text(logbox, height=7, bg="#1e2127", fg=TEXT, insertbackground=TEXT,
                           relief="flat", wrap="word", yscrollcommand=log_scroll.set)
        self.log.pack(side="left", fill="both", expand=True)
        log_scroll.config(command=self.log.yview)
        self.log.configure(state="disabled")
        self._log(f"n2elite-ng {__version__} — offline N2 Elite / amiibo manager. Ready.")

    def _render_slots(self, count: int):
        for w in self.grid_frame.winfo_children():
            w.destroy()
        self.slots = []
        self.selected_slot = None
        cols = 5
        count = max(count, 1)
        for i in range(count):
            f = tk.Frame(self.grid_frame, bg=SLOT_EMPTY, width=130, height=64,
                         highlightbackground=PANEL, highlightthickness=1, cursor="hand2")
            f.grid(row=i // cols, column=i % cols, padx=4, pady=4, sticky="nsew")
            f.grid_propagate(False)
            num = tk.Label(f, text=f"#{i + 1}", bg=SLOT_EMPTY, fg=SUBTLE, font=("TkDefaultFont", 8))
            num.pack(anchor="nw", padx=4, pady=(2, 0))
            name = tk.Label(f, text="(empty)", bg=SLOT_EMPTY, fg=TEXT, wraplength=118,
                            font=("TkDefaultFont", 9, "bold"), cursor="hand2")
            name.pack(anchor="center", expand=True)
            slot = {"frame": f, "num": num, "name": name, "amiibo_id": None, "filled": False}
            self.slots.append(slot)
            for w in (f, num, name):
                w.bind("<Button-1>", lambda _e, idx=i: self._on_slot_click(idx))
                w.bind("<Double-Button-1>", lambda _e, idx=i: self._on_slot_double_click(idx))
        for c in range(cols):
            self.grid_frame.columnconfigure(c, weight=1)

    def _set_slot(self, i: int, name: str, filled: bool, amiibo_id: str | None = None):
        if i >= len(self.slots):
            self._render_slots(i + 1)
        s = self.slots[i]
        s["amiibo_id"] = amiibo_id
        s["filled"] = filled
        bg = SLOT_FILLED if filled else SLOT_EMPTY
        s["frame"].configure(bg=bg)
        s["num"].configure(bg=bg)
        s["name"].configure(bg=bg, text=name)

    def _mark_active_bank(self):
        """Show a star on the active bank's tile."""
        for idx, s in enumerate(self.slots):
            star = " ★" if idx == self.active_bank else ""
            s["num"].configure(text=f"#{idx + 1}{star}",
                               fg="#8fd14f" if star else SUBTLE)

    def _on_slot_double_click(self, i: int):
        """Double-click a bank tile to make it the active bank."""
        if i >= len(self.slots):
            return
        self._on_slot_click(i)  # ensure it's selected/shown
        if self.dev is None:
            return
        if not self.unlocked:
            self._log("Double-click to set active needs the N2 unlocked (manager mode).")
            return
        self.set_active_bank()

    def _on_slot_click(self, i: int):
        if i >= len(self.slots):
            return
        # restore previously selected slot's colour
        if self.selected_slot is not None and self.selected_slot < len(self.slots):
            p = self.slots[self.selected_slot]
            pbg = SLOT_FILLED if p["filled"] else SLOT_EMPTY
            for k in ("frame", "num", "name"):
                p[k].configure(bg=pbg)
        self.selected_slot = i
        s = self.slots[i]
        for k in ("frame", "num", "name"):
            s[k].configure(bg=SLOT_SELECTED)
        self._show_amiibo_detail(s["amiibo_id"], bank=i)

    # -- helpers -----------------------------------------------------------
    def _log(self, msg: str):
        self.log.configure(state="normal")
        self.log.insert("end", msg + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _set_actions(self, enabled: bool):
        for b in self.action_btns:
            b.configure(state="normal" if enabled else "disabled")
        if enabled:
            self._apply_lock_state()

    def _apply_lock_state(self):
        """Grey out the button for the state we're already in, and gate the
        manager-only functions on being unlocked."""
        def setb(label, on):
            self.btns[label].configure(state="normal" if on else "disabled")

        manager_only = ("Scan All Banks", "Set Active Bank", "Write Amiibo…", "Empty Bank",
                        "Set Bank Count")
        if self.unlocked is True:          # already in manager mode
            setb("Unlock", False)          # grey out — already unlocked
            setb("Lock", True)
            for lbl in manager_only:
                setb(lbl, True)
        elif self.unlocked is False:       # locked
            setb("Lock", False)            # grey out — already locked
            setb("Unlock", True)
            for lbl in manager_only:
                setb(lbl, False)
        # unlocked is None (unknown until first scan): leave both enabled

    def _busy(self, msg: str):
        self.status_var.set(msg)
        self._set_actions(False)

    def refresh_ports(self):
        described = describe_ports()
        self._port_map = {label: dev for dev, label in described}
        labels = [label for _, label in described]
        self.port_menu["values"] = labels
        if labels and not self.port_var.get():
            self.port_var.set(labels[0])  # CP210x is first
        self._log(f"Found {len(labels)} serial port(s)."
                  + (" Pick the 'CP210x' one." if len(labels) > 1 else ""))

    # -- device operations (dispatched to worker) --------------------------
    def toggle_connect(self):
        if self.dev is not None:
            try:
                self.dev.close()
            except Exception:
                pass
            self.dev = None
            self.status_var.set("Disconnected")
            self.connect_btn.configure(text="Connect")
            self._set_actions(False)
            self._log("Disconnected.")
            return
        label = self.port_var.get()
        port = getattr(self, "_port_map", {}).get(label, label)
        if not port:
            messagebox.showwarning("No port", "Select a serial port first.")
            return
        self._busy("Connecting…")
        self._log(f"Connecting on {port}…")

        def job():
            dev = N2Elite(port=port)
            ver = dev.open()
            return dev, ver

        self.worker.submit("connect", job)

    def scan(self):
        if not self._require_dev():
            return
        self._busy("Scanning…")
        self._log("Scanning for a tag (place the disc on the reader)…")

        def job():
            uid = self.dev.activate(timeout=20)
            data = self.dev.dump_ntag()
            n2 = self.dev.is_n2_elite()
            return uid, data, n2

        self.worker.submit("scan", job)

    def scan_all_banks(self):
        if not self._require_dev():
            return
        self._busy("Listing all banks…")
        self._log("Reading every bank (needs the N2 unlocked)…")

        def job():
            self.dev.activate(timeout=20)
            info = self.dev.get_info()
            return info, self.dev.list_banks()

        self.worker.submit("list_banks", job)

    def set_active_bank(self):
        if not self._require_dev():
            return
        if self.selected_slot is None:
            messagebox.showinfo("Select a bank", "Click a bank tile first, then Set Active Bank.")
            return
        bank = self.selected_slot
        self._busy(f"Setting active bank to #{bank + 1}…")

        def job(b=bank):
            self.dev.activate(timeout=20)
            self.dev.select_bank(b)
            return self.dev.get_info().active_bank

        self.worker.submit("set_active", job)

    def _target_bank(self) -> int | None:
        """The bank a per-slot op should act on (the selected tile when unlocked)."""
        if self.unlocked and self.selected_slot is not None:
            return self.selected_slot
        return None

    def dump_active(self):
        if not self._require_dev():
            return
        bank = self._target_bank()
        default = f"bank_{bank + 1:02d}.bin" if bank is not None else "amiibo.bin"
        path = filedialog.asksaveasfilename(defaultextension=".bin", initialfile=default,
                                            filetypes=[("Amiibo dump", "*.bin")])
        if not path:
            return
        self._busy("Dumping…")
        self._log(f"Backing up {'bank #%d' % (bank + 1) if bank is not None else 'the active amiibo'}…")

        def job(b=bank, p=path):
            self.dev.activate(timeout=20)
            data = self.dev.dump_bank(b) if b is not None else self.dev.dump_ntag()
            Path(p).write_bytes(data)
            return self.dev.uid, data, p

        self.worker.submit("dump", job)

    def restore_active(self):
        if not self._require_dev():
            return
        bank = self._target_bank()
        if bank is None:
            messagebox.showinfo("Select a bank",
                                "Unlock the N2 and click the bank tile you want to write to.")
            return
        path = filedialog.askopenfilename(filetypes=[("Amiibo dump", "*.bin")])
        if not path:
            return
        data = Path(path).read_bytes()
        if len(data) not in (540, 572):
            messagebox.showerror("Bad file", f"Expected 540 or 572 bytes, got {len(data)}.")
            return
        if not messagebox.askyesno(
            "Confirm write",
            f"Write this .bin to bank #{bank + 1}? This overwrites the bank — back it up "
            f"first.\n\nProceed?",
        ):
            return
        self._busy(f"Writing to bank #{bank + 1}…")

        def job(b=bank, d=data):
            self.dev.activate(timeout=20)
            self.dev.write_bank(b, d)
            return b, self._read_bank_id(b)

        self.worker.submit("restore", job)

    def empty_bank(self):
        if not self._require_dev():
            return
        bank = self._target_bank()
        if bank is None:
            messagebox.showinfo("Select a bank",
                                "Unlock the N2 and click the bank tile you want to empty.")
            return
        if not messagebox.askyesno(
            "Confirm empty",
            f"Erase all data in bank #{bank + 1}? This CANNOT be undone unless you have a "
            f"backup.\n\nProceed?",
        ):
            return
        self._busy(f"Emptying bank #{bank + 1}…")

        def job(b=bank):
            self.dev.activate(timeout=20)
            self.dev.empty_bank(b)
            return b, self._read_bank_id(b)

        self.worker.submit("empty", job)

    def _read_bank_id(self, bank: int) -> str | None:
        try:
            raw = self.dev.read_bank_amiibo_id(bank)
            aid = "0x%016x" % int.from_bytes(raw, "big")
            return None if is_empty_id(aid) else aid
        except (NfcError, NfcTimeout):
            return None

    def set_bank_count(self):
        if not self._require_dev():
            return
        val = simpledialog.askinteger("Set bank count", "Number of banks (1-200):",
                                      minvalue=1, maxvalue=200)
        if not val:
            return
        if not messagebox.askyesno(
            "Confirm bank count",
            f"Set the bank count to {val}?\n\nLowering it below a used slot does NOT erase "
            f"that data, but hides those slots from games until you raise it again.",
        ):
            return
        self._busy("Setting bank count…")
        self.worker.submit("bankcount", lambda: (self.dev.activate(timeout=20),
                                                 self.dev.set_bank_count(val), val)[-1])

    def unlock(self):
        if not self._require_dev():
            return
        if not messagebox.askyesno(
            "Unlock N2?",
            "Unlock the N2 into manager mode? This exposes bank management (writing, "
            "erasing, bank count). Are you sure?",
        ):
            return
        self._busy("Unlocking…")

        def job():
            self.dev.activate(timeout=20)
            if self.dev.is_n2_elite():
                return "already"
            self.dev.unlock_prep()
            self.dev.unlock_finalize()
            self.dev._select()
            return "ok" if self.dev.is_n2_elite() else "failed"

        self.worker.submit("unlock", job)

    def lock(self):
        if not self._require_dev():
            return
        if not messagebox.askyesno(
            "Lock N2?",
            "Lock the N2? It will behave as a plain read-only amiibo (the active bank) and "
            "hide the management functions until you unlock it again. Are you sure?",
        ):
            return
        self._busy("Locking…")
        self.worker.submit("lock", lambda: (self.dev.activate(timeout=20), self.dev.lock())[-1])

    # -- file utilities ----------------------------------------------------
    def identify_file(self):
        path = filedialog.askopenfilename(filetypes=[("Amiibo dump", "*.bin")])
        if not path:
            return
        data = Path(path).read_bytes()[:572]
        if is_blank(data):
            self._log(f"{Path(path).name}: (blank tag)")
            return
        aid, name = identify(data)
        self.current_amiibo_id = aid
        self.image_btn.configure(state="normal")
        self._log(f"{Path(path).name}: {name or '(unknown)'}  [{aid}]")

    def show_image(self):
        """Show the amiibo figure. Fetches once from the public image DB (the ONE
        opt-in online action) and caches locally; cached images load offline."""
        from .amiibo import cached_image, fetch_image

        aid = self.current_amiibo_id
        if not aid:
            return
        local = cached_image(aid)
        if local:
            self._set_detail_image(local)
            self._display_image(local)
            return
        if not messagebox.askyesno(
            "Fetch amiibo image?",
            "The image isn't cached yet. Download it once from the public amiibo "
            "image database (AmiiboAPI)? This is the only time the app goes online, "
            "and only a public icon is requested.",
        ):
            return
        self._busy("Fetching image…")
        self._log("Fetching amiibo image (one-time, cached after)…")
        self.worker.submit("image", lambda a=aid: str(fetch_image(a)))

    def _display_image(self, path):
        try:
            img = tk.PhotoImage(file=str(path))
        except tk.TclError as e:
            self._log(f"Could not display image: {e}")
            return
        # Downscale large icons to a friendly size (Tk subsample is integer-only).
        factor = max(1, img.height() // 300)
        if factor > 1:
            img = img.subsample(factor, factor)
        self._photo = img  # keep reference
        top = tk.Toplevel(self)
        top.title("Amiibo")
        top.configure(bg=BG)
        tk.Label(top, image=img, bg=BG).pack(padx=10, pady=10)
        top.transient(self)

    def crypto_file(self, encrypt: bool):
        from .amiibo import AmiiboKeys, pack, unpack

        keys_path = filedialog.askopenfilename(title="Select key_retail.bin",
                                               filetypes=[("Key file", "*.bin")])
        if not keys_path:
            return
        in_path = filedialog.askopenfilename(title="Input .bin",
                                             filetypes=[("Amiibo dump", "*.bin")])
        if not in_path:
            return
        out_path = filedialog.asksaveasfilename(defaultextension=".bin",
                                                filetypes=[("Amiibo dump", "*.bin")])
        if not out_path:
            return
        try:
            keys = AmiiboKeys.load(keys_path)
            data = Path(in_path).read_bytes()
            if encrypt:
                Path(out_path).write_bytes(pack(keys, data))
                self._log(f"Encrypted -> {out_path}")
            else:
                plain, valid = unpack(keys, data)
                Path(out_path).write_bytes(plain)
                self._log(f"Decrypted -> {out_path} (HMAC {'valid' if valid else 'INVALID'})")
        except Exception as e:
            messagebox.showerror("Crypto error", str(e))

    # -- detail panel + settings ------------------------------------------
    def _update_detail(self, uid: bytes | None = None):
        """Populate the detail panel from the currently-read tag."""
        from .amiibo import info, is_blank
        data = self.current_data
        if data is None:
            return
        if is_blank(data):
            self._show_amiibo_detail(None, uid=uid)
            return
        aid, _ = info(data)
        self._show_amiibo_detail(aid, uid=uid)

    def _show_amiibo_detail(self, amiibo_id: str | None, bank: int | None = None,
                            uid: bytes | None = None):
        """Populate the right-hand panel for an amiibo ID (+ image if available)."""
        from .amiibo import info_for_id, cached_image

        lines = []
        if bank is not None:
            lines.append(f"Bank #{bank + 1}")
        self._detail_photo = None
        self.detail_img.configure(image="", text="(no image)")
        if not amiibo_id:
            lines.append("(empty — no amiibo)")
            self.detail_info.configure(text="\n".join(lines))
            return
        rec = info_for_id(amiibo_id)
        if rec:
            lines += [rec.get("name", "?"),
                      f"Character: {rec.get('character', '?')}",
                      f"Series: {rec.get('series', '?')}",
                      f"Game: {rec.get('game', '?')}",
                      f"Type: {rec.get('type', '?')}"]
        else:
            lines.append("(unknown amiibo)")
        lines += ["", f"ID:  {amiibo_id}"]
        if uid is not None:
            lines.append(f"UID: {uid.hex().upper()}")
        self.detail_info.configure(text="\n".join(lines))

        local = cached_image(amiibo_id)
        if local:
            self._set_detail_image(local)
        elif self.cfg.show_images_auto and rec:
            # only auto-fetch for KNOWN amiibo; empty/unknown ids have no image (404)
            self.detail_img.configure(text="fetching…")
            from .amiibo import fetch_image
            self.worker.submit("detail_image", lambda a=amiibo_id: str(fetch_image(a)))

    def _set_detail_image(self, path):
        try:
            img = tk.PhotoImage(file=str(path))
        except tk.TclError:
            return
        factor = max(1, round(img.height() / 150))
        if factor > 1:
            img = img.subsample(factor, factor)
        self._detail_photo = img
        self.detail_img.configure(image=img, text="")


    def _sync_database(self):
        from .amiibo import sync
        self.status_var.set("Downloading amiibo database…")
        self._log("Updating amiibo database (one-time download)…")
        self.worker.submit("sync_db", lambda: sync.download_database())

    def _sync_images(self):
        from .amiibo import images, sync
        images.set_cache_dir(self.cfg.cache_dir)
        ids = sync.all_amiibo_ids()
        self.status_var.set("Downloading amiibo images…")
        self._log(f"Downloading up to {len(ids)} amiibo images for offline use "
                  f"(cached ones are skipped)…")

        def job():
            state = {"last": -1}

            def prog(done, total, ok, failed, nbytes, speed):
                if done == total or done - state["last"] >= 50:
                    state["last"] = done
                    self.events.put(("log", None,
                                     f"  images {done}/{total} "
                                     f"(fetched {ok}, unavailable {failed}) — "
                                     f"{sync.human_bytes(nbytes)} @ "
                                     f"{sync.human_bytes(speed)}/s"))
            return sync.download_all_images(ids=ids, on_progress=prog)

        self.worker.submit("sync_images", job)

    def show_settings(self):
        top = tk.Toplevel(self)
        top.title("Settings")
        top.configure(bg=BG)
        top.geometry("480x330")
        auto = tk.BooleanVar(value=self.cfg.show_images_auto)
        tk.Checkbutton(top, text="Show amiibo images automatically (fetches online once "
                       "per amiibo, then cached)", variable=auto, bg=BG, fg=TEXT,
                       selectcolor=PANEL, activebackground=BG, activeforeground=TEXT,
                       wraplength=440, justify="left", anchor="w").pack(fill="x", padx=12, pady=10)
        cd = tk.Frame(top, bg=BG)
        cd.pack(fill="x", padx=12)
        tk.Label(cd, text="Image cache folder:", bg=BG, fg=TEXT).pack(anchor="w")
        cache_var = tk.StringVar(value=self.cfg.cache_dir)
        row = tk.Frame(cd, bg=BG)
        row.pack(fill="x")
        tk.Entry(row, textvariable=cache_var).pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="Browse…",
                   command=lambda: cache_var.set(filedialog.askdirectory(
                       initialdir=cache_var.get()) or cache_var.get())).pack(side="left", padx=4)

        def apply_and_close():
            from .amiibo import images
            self.cfg.show_images_auto = auto.get()
            self.cfg.cache_dir = cache_var.get().strip() or self.cfg.cache_dir
            self.cfg.save()
            images.set_cache_dir(self.cfg.cache_dir)
            self._log(f"Settings saved. Auto-images: {self.cfg.show_images_auto}; "
                      f"cache: {self.cfg.cache_dir}")
            if self.current_data is not None:
                self._update_detail()
            top.destroy()

        # Offline data — download everything so no network is needed later.
        off = tk.LabelFrame(top, text="Offline data (optional, one-time download)",
                            bg=BG, fg=SUBTLE, padx=10, pady=8)
        off.pack(fill="x", padx=12, pady=(12, 0))
        tk.Label(off, text="Fetch the full amiibo database and every figure image "
                 "so the app works with no internet.", bg=BG, fg=SUBTLE,
                 wraplength=430, justify="left", anchor="w").pack(fill="x")
        obtns = tk.Frame(off, bg=BG)
        obtns.pack(fill="x", pady=(6, 0))

        def sync_and_close(fn):
            self.cfg.cache_dir = cache_var.get().strip() or self.cfg.cache_dir
            self.cfg.save()
            top.destroy()
            fn()

        ttk.Button(obtns, text="Update database",
                   command=lambda: sync_and_close(self._sync_database)).pack(side="left")
        ttk.Button(obtns, text="Download all images",
                   command=lambda: sync_and_close(self._sync_images)).pack(side="left", padx=6)

        btns = tk.Frame(top, bg=BG)
        btns.pack(fill="x", padx=12, pady=12)
        ttk.Button(btns, text="Save", command=apply_and_close).pack(side="right")
        ttk.Button(btns, text="Cancel", command=top.destroy).pack(side="right", padx=6)
        top.transient(self)

    def show_about(self):
        messagebox.showinfo(
            "About n2elite-ng",
            f"n2elite-ng {__version__}\n"
            "by Jona\n\n"
            "An open-source, offline manager for the N2 Elite / Amiiqo USB reader.\n"
            "Reads & backs up amiibo, identifies them, and (with your own "
            "key_retail.bin) decrypts/encrypts amiibo dumps.\n\n"
            "Fully offline. The only online features are opt-in: fetching amiibo "
            "images and the one-time 'Download offline data'. Ships no Nintendo keys.\n\n"
            "License: PolyForm Noncommercial 1.0.0 — free to use/modify/share, "
            "but not for commercial profit.",
        )

    def _require_dev(self) -> bool:
        if self.dev is None:
            messagebox.showwarning("Not connected", "Connect to the reader first.")
            return False
        return True

    # -- event pump --------------------------------------------------------
    def _poll_events(self):
        try:
            while True:
                kind, name, payload = self.events.get_nowait()
                self._handle_event(kind, name, payload)
        except queue.Empty:
            pass
        self.after(80, self._poll_events)

    def _handle_event(self, kind, name, payload):
        if kind == "log":  # progress line from a background download
            self._log(payload)
            return
        if kind == "error":
            if name == "detail_image":
                # image fetch failed (e.g. 404 = no picture for this amiibo) — stay quiet
                self.detail_img.configure(image="", text="(no image)")
                return
            self._log(f"[{name}] error: {payload}")
            self.status_var.set("Ready" if self.dev else "Disconnected")
            self._set_actions(self.dev is not None)
            return
        # success
        if name == "connect":
            self.dev, ver = payload
            self.status_var.set(f"Connected — MFRC522 v0x{ver:02X}")
            self.connect_btn.configure(text="Disconnect")
            self._set_actions(True)
            self._log(f"Connected. Chip version 0x{ver:02X}.")
        elif name in ("scan", "dump"):
            uid, data, *rest = payload
            n2 = rest[0] if (rest and name == "scan") else None
            blank = is_blank(data)
            aid, aname = identify(data)
            label = "(blank)" if blank else (aname or "(unknown)")
            self._set_slot(0, label, not blank, amiibo_id=None if blank else aid)
            self.current_amiibo_id = None if blank else aid
            self.current_data = data
            self.image_btn.configure(state="disabled" if blank else "normal")
            self._log(f"Tag {uid.hex().upper()} -> {describe(data)}")
            self._update_detail(uid)
            if name == "dump":
                self._log(f"Saved backup -> {rest[0]}")
            if name == "scan":
                self.unlocked = bool(n2)
                if n2:
                    self._log("N2 is UNLOCKED (manager mode) — all banks available.")
                    self.status_var.set("Connected — N2 unlocked (manager mode)")
                else:
                    self._log("N2 is LOCKED — only the active amiibo is readable. Use Unlock.")
                    self.status_var.set("Connected — N2 locked")
            else:
                self.status_var.set("Ready")
            self._set_actions(True)
        elif name in ("restore", "empty"):
            bank, aid = payload
            empty = not aid or is_empty_id(aid)
            rec = info_for_id(aid) if aid else None
            lbl = "(empty)" if empty else ((rec.get("name") if rec else None) or "Unknown amiibo")
            self._set_slot(bank, lbl, not empty, amiibo_id=None if empty else aid)
            self._mark_active_bank()
            self._log(f"Bank #{bank + 1} {'emptied' if name == 'empty' else 'written'} -> {lbl}.")
            self._log("Tip: click 'Scan All Banks' to refresh the bank list.")
            self.status_var.set("Ready")
            self._set_actions(True)
        elif name == "bankcount":
            self._log(f"Bank count set to {payload}.")
            self._log("Tip: click 'Scan All Banks' to refresh the bank list.")
            self.status_var.set("Ready")
            self._set_actions(True)
        elif name == "unlock":
            msg = {"already": "Already unlocked.", "ok": "Unlocked!",
                   "failed": "Unlock did not take (disc not answering N2 commands)."}
            self._log(msg.get(payload, str(payload)))
            if payload in ("ok", "already"):
                self.unlocked = True
                self.status_var.set("Connected — N2 unlocked (manager mode)")
            self._set_actions(True)
        elif name == "lock":
            self._log("Lock command sent — the N2 is now locked.")
            self.unlocked = False
            self.status_var.set("Connected — N2 locked")
            self._set_actions(True)
        elif name == "list_banks":
            info, banks = payload
            self.unlocked = True
            self._render_slots(len(banks))
            for b, aid, aname in banks:
                blank = not aid or is_empty_id(aid)
                lbl = "(empty)" if blank else (aname or "Unknown amiibo")
                self._set_slot(b, lbl, not blank, amiibo_id=None if blank else aid)
            self.active_bank = info.active_bank
            self._mark_active_bank()
            self._log(f"Listed {len(banks)} banks — active #{info.active_bank + 1}, "
                      f"count {info.bank_count} (max 200). Click to view, double-click to "
                      f"set active.")
            self.status_var.set("Connected — N2 unlocked (manager mode)")
            self._set_actions(True)
            if banks:
                self._on_slot_click(info.active_bank if info.active_bank < len(banks) else 0)
        elif name == "set_active":
            self.active_bank = payload
            self._mark_active_bank()
            self._log(f"Active bank is now #{payload + 1}.")
            self.status_var.set("Connected — N2 unlocked (manager mode)")
            self._set_actions(True)
        elif name == "image":
            self.status_var.set("Ready" if self.dev else "Disconnected")
            self._set_actions(self.dev is not None)
            self._log("Image cached.")
            self._set_detail_image(payload)
            self._display_image(payload)
        elif name == "detail_image":
            self._set_detail_image(payload)
        elif name == "sync_db":
            self._log(f"Amiibo database updated: {payload} amiibo. "
                      "Re-scan to use the refreshed names.")
            self.status_var.set("Ready" if self.dev else "Disconnected")
            self._set_actions(self.dev is not None)
        elif name == "sync_images":
            from .amiibo.sync import human_bytes
            secs = max(payload["seconds"], 1e-6)
            self._log(f"Image download complete: {payload['ok']} fetched, "
                      f"{payload['skipped']} already cached, {payload['failed']} "
                      f"unavailable — {human_bytes(payload['bytes'])} in {secs:.1f}s "
                      f"({human_bytes(payload['bytes'] / secs)}/s avg). "
                      "Amiibo images are now available offline.")
            self.status_var.set("Ready" if self.dev else "Disconnected")
            self._set_actions(self.dev is not None)
        else:
            self.status_var.set("Ready")
            self._set_actions(self.dev is not None)

    def _on_close(self):
        try:
            if self.dev:
                self.dev.close()
        except Exception:
            pass
        self.worker.stop()
        self.destroy()


def main():
    app = N2App()
    app.mainloop()
    return 0


if __name__ == "__main__":
    main()
