"""
LitePDF v2.0 - Lightweight PDF Reader & Editor
New in v2: Search, Highlight Tool, Visual Thumbnails, upgraded UI
Stack: Python + PyMuPDF (fitz) + tkinter
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
import fitz  # PyMuPDF
import os, sys, threading, queue
from PIL import Image, ImageTk, ImageDraw

# ─── Theme ────────────────────────────────────────────────────────────────────
APP_NAME    = "LitePDF"
APP_VER     = "2.0.0"
ZOOM_STEPS  = [0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0, 2.5, 3.0]
DEFAULT_ZOOM = 3   # index → 1.0×

BG          = "#1e1e2e"
SIDEBAR_BG  = "#181825"
ACCENT      = "#cba6f7"
ACCENT2     = "#89b4fa"
GREEN       = "#a6e3a1"
YELLOW      = "#f9e2af"
RED         = "#f38ba8"
FG          = "#cdd6f4"
FG_DIM      = "#6c7086"
BTN_BG      = "#313244"
BTN_HOV     = "#45475a"
CANVAS_BG   = "#11111b"
SEARCH_HL   = (1.0, 0.9, 0.2, 0.5)   # fitz RGBA  – yellow
SEARCH_CUR  = (1.0, 0.5, 0.1, 0.6)   # orange for current match
HIGHLIGHT_C = (1.0, 0.84, 0.0, 0.4)  # gold highlight

THUMB_W, THUMB_H = 130, 170          # sidebar thumbnail dimensions


# ─── Thumbnail Worker (background thread) ────────────────────────────────────
class ThumbWorker(threading.Thread):
    """Renders page thumbnails on a background thread."""
    def __init__(self, callback):
        super().__init__(daemon=True)
        self._q        = queue.Queue()
        self._callback = callback
        self._stop     = threading.Event()
        self.start()

    def request(self, doc_path, page_no):
        self._q.put((doc_path, page_no))

    def clear(self):
        with self._q.mutex:
            self._q.queue.clear()

    def run(self):
        while not self._stop.is_set():
            try:
                path, pno = self._q.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                doc  = fitz.open(path)
                page = doc[pno]
                mat  = fitz.Matrix(THUMB_W / page.rect.width,
                                   THUMB_H / page.rect.height)
                pix  = page.get_pixmap(matrix=mat, alpha=False)
                img  = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                # Add subtle white border + drop-shadow feel
                bordered = Image.new("RGB", (THUMB_W + 4, THUMB_H + 4), "#313244")
                bordered.paste(img, (2, 2))
                self._callback(pno, bordered)
                doc.close()
            except Exception:
                pass


# ─── Main Application ─────────────────────────────────────────────────────────
class LitePDF(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_NAME)
        self.geometry("1280x860")
        self.minsize(960, 640)
        self.configure(bg=BG)

        # ── Core state ──
        self.doc           = None
        self.doc_path      = None
        self.current_page  = 0
        self.zoom_idx      = DEFAULT_ZOOM
        self.rotation      = 0
        self.photo_cache   = {}          # (page, zoom_idx, rot) → PhotoImage
        self.thumb_photos  = {}          # page_no → PhotoImage (sidebar)
        self.thumb_items   = {}          # page_no → canvas item id
        self.thumb_labels  = {}          # page_no → label item id

        # ── Search state ──
        self.search_results  = []        # list of (page_no, fitz.Quad)
        self.search_idx      = -1        # current match index
        self.search_active   = False

        # ── Highlight tool state ──
        self.highlight_mode  = False
        self._hl_start       = None      # (x_pdf, y_pdf)

        # ── Text annotation ──
        self.text_mode       = False

        # ── Thumbnail worker ──
        self._thumb_worker   = ThumbWorker(self._on_thumb_ready)

        self._build_styles()
        self._build_ui()
        self._bind_shortcuts()
        self._update_ui_state()

    # ── ttk styles ────────────────────────────────────────────────────────────
    def _build_styles(self):
        s = ttk.Style(self)
        s.theme_use("clam")
        s.configure("TScrollbar", background=BTN_BG, troughcolor=SIDEBAR_BG,
                    bordercolor=SIDEBAR_BG, arrowcolor=FG_DIM)
        s.configure("Search.TEntry", fieldbackground=BTN_BG, foreground=FG,
                    insertcolor=FG, borderwidth=0)

    # ─────────────────────────────────────────────────────────────────────────
    # UI Construction
    # ─────────────────────────────────────────────────────────────────────────
    def _build_ui(self):
        self._build_menu()
        self._build_toolbar()
        self._build_search_bar()          # collapsible search bar
        main = tk.Frame(self, bg=BG)
        main.pack(fill=tk.BOTH, expand=True)
        self._build_sidebar(main)
        self._build_viewer(main)
        self._build_statusbar()

    # ── Menu ──────────────────────────────────────────────────────────────────
    def _build_menu(self):
        def menu(parent, **kw):
            return tk.Menu(parent, tearoff=False, bg=SIDEBAR_BG, fg=FG,
                           activebackground=ACCENT, activeforeground=BG, **kw)

        mb = menu(self)
        self.config(menu=mb)

        fm = menu(mb)
        fm.add_command(label="Open…          Ctrl+O",   command=self.open_file)
        fm.add_command(label="Save Copy…     Ctrl+S",   command=self.save_copy)
        fm.add_separator()
        fm.add_command(label="Merge PDFs…",              command=self.merge_pdfs)
        fm.add_command(label="Split PDF…",               command=self.split_pdf)
        fm.add_separator()
        fm.add_command(label="Exit",                     command=self.quit)
        mb.add_cascade(label="File", menu=fm)

        em = menu(mb)
        em.add_command(label="Find…          Ctrl+F",   command=self.toggle_search)
        em.add_separator()
        em.add_command(label="Highlight Tool Ctrl+H",   command=self.toggle_highlight)
        em.add_command(label="Add Text Note  Ctrl+T",   command=self.toggle_text_mode)
        em.add_separator()
        em.add_command(label="Rotate CW",               command=lambda: self.rotate(90))
        em.add_command(label="Rotate CCW",              command=lambda: self.rotate(-90))
        em.add_separator()
        em.add_command(label="Extract Text…",           command=self.extract_text)
        em.add_command(label="Password Protect…",       command=self.password_protect)
        mb.add_cascade(label="Edit", menu=em)

        vm = menu(mb)
        vm.add_command(label="Zoom In   Ctrl++",        command=self.zoom_in)
        vm.add_command(label="Zoom Out  Ctrl+-",        command=self.zoom_out)
        vm.add_command(label="Fit Width  Ctrl+0",       command=self.zoom_fit)
        vm.add_separator()
        vm.add_command(label="Toggle Sidebar  F9",      command=self.toggle_sidebar)
        mb.add_cascade(label="View", menu=vm)

        hm = menu(mb)
        hm.add_command(label=f"About {APP_NAME}",       command=self.show_about)
        mb.add_cascade(label="Help", menu=hm)

    # ── Toolbar ───────────────────────────────────────────────────────────────
    def _build_toolbar(self):
        self.tb = tk.Frame(self, bg=SIDEBAR_BG, pady=4)
        self.tb.pack(fill=tk.X, side=tk.TOP)

        def sep():
            tk.Frame(self.tb, bg=BTN_HOV, width=1, height=26).pack(
                side=tk.LEFT, padx=6, pady=2)

        def btn(text, cmd, color=BTN_BG, width=None):
            kw = dict(width=width) if width else {}
            b = tk.Button(self.tb, text=text, command=cmd,
                          bg=color, fg=FG, relief=tk.FLAT,
                          padx=9, pady=4, font=("Segoe UI", 9),
                          activebackground=BTN_HOV, activeforeground=FG,
                          cursor="hand2", **kw)
            b.pack(side=tk.LEFT, padx=2)
            return b

        btn("📂", self.open_file)
        btn("💾", self.save_copy)
        sep()
        btn("◀◀", self.go_first)
        btn("◀",  self.prev_page)

        self.page_var   = tk.StringVar(value="1")
        self.page_entry = tk.Entry(self.tb, textvariable=self.page_var, width=4,
                                   bg=BTN_BG, fg=FG, insertbackground=FG,
                                   relief=tk.FLAT, font=("Segoe UI", 9),
                                   justify=tk.CENTER)
        self.page_entry.pack(side=tk.LEFT, padx=2)
        self.page_entry.bind("<Return>", self.jump_to_page)

        self.total_lbl = tk.Label(self.tb, text="/ —", bg=SIDEBAR_BG, fg=FG_DIM,
                                  font=("Segoe UI", 9))
        self.total_lbl.pack(side=tk.LEFT)

        btn("▶",  self.next_page)
        btn("▶▶", self.go_last)
        sep()
        btn("🔍+", self.zoom_in)
        self.zoom_lbl = tk.Label(self.tb, text="100%", width=5,
                                  bg=SIDEBAR_BG, fg=ACCENT,
                                  font=("Segoe UI", 9, "bold"))
        self.zoom_lbl.pack(side=tk.LEFT, padx=2)
        btn("🔍−", self.zoom_out)
        btn("↔",  self.zoom_fit)
        sep()
        btn("↻",  lambda: self.rotate(90))
        btn("↺",  lambda: self.rotate(-90))
        sep()

        # Tool buttons – keep refs to toggle colour
        self.search_btn = btn("🔎 Find",      self.toggle_search)
        self.hl_btn     = btn("🖍 Highlight",  self.toggle_highlight)
        self.txt_btn    = btn("✏ Text",       self.toggle_text_mode)
        sep()
        btn("📄 Extract", self.extract_text)

    # ── Search bar (collapsible) ───────────────────────────────────────────────
    def _build_search_bar(self):
        self.search_bar = tk.Frame(self, bg=BTN_BG, pady=5)
        # hidden by default – shown on Ctrl+F

        inner = tk.Frame(self.search_bar, bg=BTN_BG)
        inner.pack(side=tk.LEFT, padx=12)

        tk.Label(inner, text="Find:", bg=BTN_BG, fg=FG,
                 font=("Segoe UI", 9)).pack(side=tk.LEFT, padx=(0, 6))

        self.search_var = tk.StringVar()
        self.search_entry = tk.Entry(inner, textvariable=self.search_var,
                                     width=30, bg=SIDEBAR_BG, fg=FG,
                                     insertbackground=FG, relief=tk.FLAT,
                                     font=("Segoe UI", 10))
        self.search_entry.pack(side=tk.LEFT, ipady=4, padx=(0, 6))
        self.search_entry.bind("<Return>",       lambda e: self.search_next())
        self.search_entry.bind("<Shift-Return>", lambda e: self.search_prev())
        self.search_entry.bind("<Escape>",       lambda e: self.close_search())
        self.search_entry.bind("<KeyRelease>",   self._on_search_key)

        def sbtn(text, cmd, color=BTN_HOV):
            b = tk.Button(inner, text=text, command=cmd,
                          bg=color, fg=FG, relief=tk.FLAT,
                          padx=8, pady=3, font=("Segoe UI", 9),
                          activebackground=ACCENT, activeforeground=BG,
                          cursor="hand2")
            b.pack(side=tk.LEFT, padx=2)
            return b

        sbtn("▲ Prev",  self.search_prev)
        sbtn("▼ Next",  self.search_next)

        self.match_lbl = tk.Label(inner, text="", bg=BTN_BG, fg=ACCENT,
                                   font=("Segoe UI", 9, "bold"), width=14)
        self.match_lbl.pack(side=tk.LEFT, padx=8)

        self.case_var = tk.BooleanVar(value=False)
        tk.Checkbutton(inner, text="Aa case", variable=self.case_var,
                       bg=BTN_BG, fg=FG, selectcolor=SIDEBAR_BG,
                       activebackground=BTN_BG, activeforeground=FG,
                       font=("Segoe UI", 9),
                       command=self._run_search).pack(side=tk.LEFT, padx=4)

        # Close button on right
        tk.Button(self.search_bar, text="✕", command=self.close_search,
                  bg=BTN_BG, fg=FG_DIM, relief=tk.FLAT,
                  font=("Segoe UI", 10), padx=8,
                  activebackground=RED, activeforeground=BG,
                  cursor="hand2").pack(side=tk.RIGHT, padx=8)

    # ── Sidebar (thumbnail canvas) ────────────────────────────────────────────
    def _build_sidebar(self, parent):
        self.sidebar_frame = tk.Frame(parent, bg=SIDEBAR_BG, width=THUMB_W + 30)
        self.sidebar_frame.pack(side=tk.LEFT, fill=tk.Y)
        self.sidebar_frame.pack_propagate(False)

        tk.Label(self.sidebar_frame, text="PAGES", bg=SIDEBAR_BG, fg=ACCENT,
                 font=("Segoe UI", 8, "bold"), pady=6).pack()

        # Scrollable canvas for thumbnails
        thumb_outer = tk.Frame(self.sidebar_frame, bg=SIDEBAR_BG)
        thumb_outer.pack(fill=tk.BOTH, expand=True)

        self.thumb_canvas = tk.Canvas(thumb_outer, bg=SIDEBAR_BG,
                                      highlightthickness=0,
                                      width=THUMB_W + 24)
        thumb_scroll = ttk.Scrollbar(thumb_outer, orient=tk.VERTICAL,
                                     command=self.thumb_canvas.yview)
        self.thumb_canvas.configure(yscrollcommand=thumb_scroll.set)
        thumb_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.thumb_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.thumb_canvas.bind("<Configure>", self._on_thumb_canvas_resize)
        self.thumb_canvas.bind("<Button-1>", self._on_thumb_click)
        self.thumb_canvas.bind("<MouseWheel>",
            lambda e: self.thumb_canvas.yview_scroll(-1*(e.delta//120), "units"))

        # Inner frame inside canvas for items
        self.thumb_inner = tk.Frame(self.thumb_canvas, bg=SIDEBAR_BG)
        self._thumb_window = self.thumb_canvas.create_window(
            0, 0, anchor=tk.NW, window=self.thumb_inner)
        self.thumb_inner.bind("<Configure>",
            lambda e: self.thumb_canvas.configure(
                scrollregion=self.thumb_canvas.bbox("all")))

    # ── Main viewer ───────────────────────────────────────────────────────────
    def _build_viewer(self, parent):
        viewer = tk.Frame(parent, bg=BG)
        viewer.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.canvas = tk.Canvas(viewer, bg=CANVAS_BG, highlightthickness=0)
        vscroll = ttk.Scrollbar(viewer, orient=tk.VERTICAL,
                                command=self.canvas.yview)
        hscroll = ttk.Scrollbar(viewer, orient=tk.HORIZONTAL,
                                command=self.canvas.xview)
        self.canvas.configure(yscrollcommand=vscroll.set,
                               xscrollcommand=hscroll.set)
        vscroll.pack(side=tk.RIGHT,  fill=tk.Y)
        hscroll.pack(side=tk.BOTTOM, fill=tk.X)
        self.canvas.pack(fill=tk.BOTH, expand=True)

        self.welcome_lbl = tk.Label(self.canvas,
            text="📄  Drop a PDF here  or  File → Open\n\nCtrl+O to open  •  Ctrl+F to search",
            bg=CANVAS_BG, fg=FG_DIM, font=("Segoe UI", 14),
            justify=tk.CENTER)
        self.canvas.create_window(600, 350, window=self.welcome_lbl, tags="welcome")

        self.canvas.bind("<Configure>",    self._on_canvas_resize)
        self.canvas.bind("<MouseWheel>",   self._on_mousewheel)
        self.canvas.bind("<ButtonPress-1>",  self._on_btn1_press)
        self.canvas.bind("<B1-Motion>",      self._on_btn1_drag)
        self.canvas.bind("<ButtonRelease-1>",self._on_btn1_release)
        self.canvas.bind("<ButtonPress-2>",  self._pan_start)
        self.canvas.bind("<B2-Motion>",      self._pan_move)
        self.canvas.bind("<ButtonPress-3>",  self._pan_start)
        self.canvas.bind("<B3-Motion>",      self._pan_move)

        # Highlight drag overlay rect
        self._hl_rect_id = None

    # ── Status bar ────────────────────────────────────────────────────────────
    def _build_statusbar(self):
        sb = tk.Frame(self, bg=SIDEBAR_BG, pady=3)
        sb.pack(fill=tk.X, side=tk.BOTTOM)
        self.status_var = tk.StringVar(value="Ready — open a PDF to begin")
        tk.Label(sb, textvariable=self.status_var, bg=SIDEBAR_BG, fg=FG,
                 font=("Segoe UI", 8), anchor=tk.W, padx=10).pack(side=tk.LEFT)
        self.info_var = tk.StringVar()
        tk.Label(sb, textvariable=self.info_var, bg=SIDEBAR_BG, fg=FG_DIM,
                 font=("Segoe UI", 8), anchor=tk.E, padx=10).pack(side=tk.RIGHT)

    # ─────────────────────────────────────────────────────────────────────────
    # Keyboard shortcuts
    # ─────────────────────────────────────────────────────────────────────────
    def _bind_shortcuts(self):
        self.bind("<Control-o>",     lambda e: self.open_file())
        self.bind("<Control-s>",     lambda e: self.save_copy())
        self.bind("<Control-f>",     lambda e: self.toggle_search())
        self.bind("<Control-h>",     lambda e: self.toggle_highlight())
        self.bind("<Control-t>",     lambda e: self.toggle_text_mode())
        self.bind("<Control-equal>", lambda e: self.zoom_in())
        self.bind("<Control-minus>", lambda e: self.zoom_out())
        self.bind("<Control-0>",     lambda e: self.zoom_fit())
        self.bind("<Right>",         lambda e: self.next_page())
        self.bind("<Left>",          lambda e: self.prev_page())
        self.bind("<Home>",          lambda e: self.go_first())
        self.bind("<End>",           lambda e: self.go_last())
        self.bind("<F9>",            lambda e: self.toggle_sidebar())
        self.bind("<Escape>",        lambda e: self._escape())

    # ─────────────────────────────────────────────────────────────────────────
    # File operations
    # ─────────────────────────────────────────────────────────────────────────
    def open_file(self):
        path = filedialog.askopenfilename(
            title="Open PDF",
            filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")])
        if path:
            self._load_pdf(path)

    def _load_pdf(self, path):
        try:
            if self.doc:
                self.doc.close()
            self.doc           = fitz.open(path)
            self.doc_path      = path
            self.current_page  = 0
            self.rotation      = 0
            self.photo_cache.clear()
            self.search_results = []
            self.search_idx     = -1
            self._clear_thumbnails()
            self._populate_thumbnails()
            self._render_page()
            self._update_ui_state()
            name = os.path.basename(path)
            self.title(f"{name} — {APP_NAME}")
            self.status_var.set(f"Opened: {name}")
            self.info_var.set(
                f"{len(self.doc)} pages  •  "
                f"{os.path.getsize(path)//1024} KB")
            self.canvas.itemconfigure("welcome", state="hidden")
        except Exception as exc:
            messagebox.showerror("Error", f"Could not open PDF:\n{exc}")

    def save_copy(self):
        if not self.doc:
            return
        path = filedialog.asksaveasfilename(
            title="Save PDF Copy",
            defaultextension=".pdf",
            initialfile=os.path.basename(self.doc_path or "copy.pdf"),
            filetypes=[("PDF files", "*.pdf")])
        if path:
            try:
                self.doc.save(path, garbage=4, deflate=True)
                self.status_var.set(f"Saved: {os.path.basename(path)}")
            except Exception as exc:
                messagebox.showerror("Error", f"Could not save:\n{exc}")

    def merge_pdfs(self):
        files = filedialog.askopenfilenames(
            title="Select PDFs to Merge",
            filetypes=[("PDF files", "*.pdf")])
        if not files:
            return
        out = filedialog.asksaveasfilename(
            title="Save Merged PDF", defaultextension=".pdf",
            filetypes=[("PDF files", "*.pdf")])
        if not out:
            return
        try:
            writer = fitz.open()
            for f in files:
                writer.insert_pdf(fitz.open(f))
            writer.save(out, garbage=4, deflate=True)
            if messagebox.askyesno("Done", f"Merged {len(files)} PDFs.\nOpen result?"):
                self._load_pdf(out)
        except Exception as exc:
            messagebox.showerror("Error", f"Merge failed:\n{exc}")

    def split_pdf(self):
        if not self.doc:
            messagebox.showinfo("Split", "Open a PDF first.")
            return
        folder = filedialog.askdirectory(title="Output Folder")
        if not folder:
            return
        try:
            base = os.path.splitext(os.path.basename(self.doc_path))[0]
            for i in range(len(self.doc)):
                out = fitz.open()
                out.insert_pdf(self.doc, from_page=i, to_page=i)
                out.save(os.path.join(folder, f"{base}_page{i+1:03d}.pdf"))
            messagebox.showinfo("Done",
                f"Split into {len(self.doc)} files in:\n{folder}")
        except Exception as exc:
            messagebox.showerror("Error", f"Split failed:\n{exc}")

    def extract_text(self):
        if not self.doc:
            return
        text = self.doc[self.current_page].get_text("text")
        win  = tk.Toplevel(self)
        win.title(f"Text — Page {self.current_page+1}")
        win.geometry("640x500")
        win.configure(bg=BG)
        txt = tk.Text(win, bg=SIDEBAR_BG, fg=FG, font=("Consolas", 10),
                      wrap=tk.WORD, relief=tk.FLAT, padx=10, pady=10)
        sb  = ttk.Scrollbar(win, command=txt.yview)
        txt.configure(yscrollcommand=sb.set)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        txt.pack(fill=tk.BOTH, expand=True)
        txt.insert(tk.END,
            text if text.strip() else "[No selectable text on this page]")
        txt.config(state=tk.DISABLED)

    def password_protect(self):
        if not self.doc:
            return
        pwd = simpledialog.askstring("Password", "Enter password:", show="*")
        if not pwd:
            return
        path = filedialog.asksaveasfilename(
            title="Save Encrypted PDF", defaultextension=".pdf",
            filetypes=[("PDF files", "*.pdf")])
        if not path:
            return
        try:
            self.doc.save(path, encryption=fitz.PDF_ENCRYPT_AES_256,
                          user_pw=pwd, owner_pw=pwd)
            messagebox.showinfo("Done", "PDF saved with password protection.")
        except Exception as exc:
            messagebox.showerror("Error", f"Could not encrypt:\n{exc}")

    # ─────────────────────────────────────────────────────────────────────────
    # ① SEARCH ────────────────────────────────────────────────────────────────
    # ─────────────────────────────────────────────────────────────────────────
    def toggle_search(self):
        if self.search_bar.winfo_ismapped():
            self.close_search()
        else:
            self.search_bar.pack(fill=tk.X, after=self.tb)
            self.search_entry.focus_set()
            self.search_btn.config(bg=ACCENT, fg=BG)

    def close_search(self):
        self.search_bar.pack_forget()
        self.search_btn.config(bg=BTN_BG, fg=FG)
        self._clear_search_highlights()
        self.search_results = []
        self.search_idx     = -1
        self.search_active  = False
        self.match_lbl.config(text="")
        self.photo_cache.clear()
        if self.doc:
            self._render_page()

    def _on_search_key(self, _event=None):
        # Live search – small debounce via after()
        if hasattr(self, "_search_after"):
            self.after_cancel(self._search_after)
        self._search_after = self.after(300, self._run_search)

    def _run_search(self):
        if not self.doc:
            return
        query = self.search_var.get().strip()
        if not query:
            self._clear_search_highlights()
            self.match_lbl.config(text="")
            self.search_results = []
            self.search_active  = False
            self.photo_cache.clear()
            self._render_page()
            return

        flags = 0 if self.case_var.get() else fitz.TEXT_PRESERVE_LIGATURES
        # fitz search flags: TEXT_DEHYPHENATE | case ignore
        quads = []
        for pno in range(len(self.doc)):
            page    = self.doc[pno]
            matches = page.search_for(query, quads=True)
            for q in matches:
                quads.append((pno, q))

        self.search_results = quads
        self.search_active  = True
        self.photo_cache.clear()   # force re-render with highlights

        if quads:
            # Jump to first match on a different page, or stay
            first_page = quads[0][0]
            self.search_idx = 0
            if first_page != self.current_page:
                self.current_page = first_page
            self._render_page()
            self._update_match_label()
        else:
            self.search_idx = -1
            self.match_lbl.config(text="No matches", fg=RED)
            self._render_page()

    def search_next(self):
        if not self.search_results:
            return
        self.search_idx = (self.search_idx + 1) % len(self.search_results)
        self._jump_to_match()

    def search_prev(self):
        if not self.search_results:
            return
        self.search_idx = (self.search_idx - 1) % len(self.search_results)
        self._jump_to_match()

    def _jump_to_match(self):
        pno, _ = self.search_results[self.search_idx]
        if pno != self.current_page:
            self.current_page = pno
            self.photo_cache.clear()
        self._render_page()
        self._update_match_label()

    def _update_match_label(self):
        n = len(self.search_results)
        i = self.search_idx + 1
        self.match_lbl.config(text=f"{i} / {n} match{'es' if n!=1 else ''}",
                               fg=GREEN)

    def _clear_search_highlights(self):
        self.search_active = False

    # ─────────────────────────────────────────────────────────────────────────
    # ② HIGHLIGHT TOOL ────────────────────────────────────────────────────────
    # ─────────────────────────────────────────────────────────────────────────
    def toggle_highlight(self):
        self.highlight_mode = not self.highlight_mode
        self.text_mode      = False
        self.hl_btn.config(bg=ACCENT if self.highlight_mode else BTN_BG,
                           fg=BG      if self.highlight_mode else FG)
        self.txt_btn.config(bg=BTN_BG, fg=FG)
        if self.highlight_mode:
            self.canvas.config(cursor="crosshair")
            self.status_var.set("Highlight mode — drag across text to highlight")
        else:
            self.canvas.config(cursor="arrow")
            self.status_var.set("Highlight mode off")

    def _canvas_to_pdf(self, cx, cy):
        """Convert canvas pixel coords to PDF page coords."""
        page = self.doc[self.current_page]
        # Account for canvas scroll offset
        x_off = self.canvas.canvasx(0)
        y_off = self.canvas.canvasy(0)
        # Canvas image starts at x_img, 10
        cw    = self.canvas.winfo_width()
        key   = (self.current_page, self.zoom_idx, self.rotation)
        photo = self.photo_cache.get(key)
        x_img = max((photo.width() if photo else 0) // 2, cw // 2) - \
                (photo.width() if photo else 0) // 2 if photo else 0
        rx = (cx + x_off - x_img) / self.zoom
        ry = (cy + y_off - 10)    / self.zoom
        return rx, ry

    def _on_btn1_press(self, event):
        if self.highlight_mode and self.doc:
            self._hl_start = (event.x, event.y)
            if self._hl_rect_id:
                self.canvas.delete(self._hl_rect_id)
            self._hl_rect_id = self.canvas.create_rectangle(
                event.x, event.y, event.x, event.y,
                outline=ACCENT, width=2, fill="#cba6f740", tags="hl_drag")
        elif self.text_mode and self.doc:
            self._place_text_annotation(event)

    def _on_btn1_drag(self, event):
        if self.highlight_mode and self._hl_start and self._hl_rect_id:
            x0, y0 = self._hl_start
            self.canvas.coords(self._hl_rect_id, x0, y0, event.x, event.y)

    def _on_btn1_release(self, event):
        if not (self.highlight_mode and self._hl_start and self.doc):
            return
        x0, y0 = self._hl_start
        x1, y1 = event.x, event.y
        if abs(x1 - x0) < 4 and abs(y1 - y0) < 4:
            self._hl_start = None
            if self._hl_rect_id:
                self.canvas.delete(self._hl_rect_id)
            return

        # Convert both corners to PDF space
        px0, py0 = self._canvas_to_pdf(min(x0,x1), min(y0,y1))
        px1, py1 = self._canvas_to_pdf(max(x0,x1), max(y0,y1))
        rect = fitz.Rect(px0, py0, px1, py1)

        page = self.doc[self.current_page]
        # Find words that intersect the drag rectangle
        words = page.get_text("words")
        hit_quads = []
        for w in words:
            wr = fitz.Rect(w[:4])
            if wr.intersects(rect):
                hit_quads.append(wr.quad)

        if hit_quads:
            annot = page.add_highlight_annot(hit_quads)
            annot.set_colors(stroke=(1, 0.84, 0))   # gold
            annot.update()
            self.status_var.set(
                f"Highlighted {len(hit_quads)} word(s) on page {self.current_page+1}")
        else:
            # Fallback: highlight the raw rectangle area
            annot = page.add_highlight_annot(rect.quad)
            annot.update()
            self.status_var.set(f"Area highlighted on page {self.current_page+1}")

        if self._hl_rect_id:
            self.canvas.delete(self._hl_rect_id)
        self._hl_start   = None
        self._hl_rect_id = None

        # Invalidate cache for this page and re-render
        keys_to_drop = [k for k in self.photo_cache if k[0] == self.current_page]
        for k in keys_to_drop:
            del self.photo_cache[k]
        self._render_page()

    # ─────────────────────────────────────────────────────────────────────────
    # Text annotation
    # ─────────────────────────────────────────────────────────────────────────
    def toggle_text_mode(self):
        self.text_mode      = not self.text_mode
        self.highlight_mode = False
        self.txt_btn.config(bg=ACCENT if self.text_mode else BTN_BG,
                            fg=BG      if self.text_mode else FG)
        self.hl_btn.config(bg=BTN_BG, fg=FG)
        if self.text_mode:
            self.canvas.config(cursor="xterm")
            self.status_var.set("Text mode — click on page to place annotation")
        else:
            self.canvas.config(cursor="arrow")
            self.status_var.set("Text mode off")

    def _place_text_annotation(self, event):
        text = simpledialog.askstring("Add Text", "Enter annotation text:")
        if not text:
            return
        px, py = self._canvas_to_pdf(event.x, event.y)
        page   = self.doc[self.current_page]
        page.insert_text((px, py), text, fontsize=12,
                         color=(0.55, 0.4, 0.9))
        keys_to_drop = [k for k in self.photo_cache if k[0] == self.current_page]
        for k in keys_to_drop:
            del self.photo_cache[k]
        self._render_page()
        self.status_var.set(f"Text added to page {self.current_page+1}")

    # ─────────────────────────────────────────────────────────────────────────
    # Navigation
    # ─────────────────────────────────────────────────────────────────────────
    def next_page(self):
        if self.doc and self.current_page < len(self.doc)-1:
            self.current_page += 1
            self._render_page(); self._update_ui_state()

    def prev_page(self):
        if self.doc and self.current_page > 0:
            self.current_page -= 1
            self._render_page(); self._update_ui_state()

    def go_first(self):
        if self.doc:
            self.current_page = 0
            self._render_page(); self._update_ui_state()

    def go_last(self):
        if self.doc:
            self.current_page = len(self.doc)-1
            self._render_page(); self._update_ui_state()

    def jump_to_page(self, _=None):
        if not self.doc:
            return
        try:
            n = max(0, min(int(self.page_var.get())-1, len(self.doc)-1))
            self.current_page = n
            self._render_page(); self._update_ui_state()
        except ValueError:
            self._update_ui_state()

    # ─────────────────────────────────────────────────────────────────────────
    # Zoom / Rotate
    # ─────────────────────────────────────────────────────────────────────────
    @property
    def zoom(self):
        return ZOOM_STEPS[self.zoom_idx]

    def zoom_in(self):
        if self.zoom_idx < len(ZOOM_STEPS)-1:
            self.zoom_idx += 1; self._render_page(); self._update_ui_state()

    def zoom_out(self):
        if self.zoom_idx > 0:
            self.zoom_idx -= 1; self._render_page(); self._update_ui_state()

    def zoom_fit(self):
        if not self.doc:
            return
        rect  = self.doc[self.current_page].rect
        w_fit = self.canvas.winfo_width() / rect.width
        best  = min(ZOOM_STEPS, key=lambda z: abs(z - w_fit * 0.93))
        self.zoom_idx = ZOOM_STEPS.index(best)
        self._render_page(); self._update_ui_state()

    def rotate(self, deg):
        if not self.doc:
            return
        self.rotation = (self.rotation + deg) % 360
        self.photo_cache.clear()
        self._render_page()

    # ─────────────────────────────────────────────────────────────────────────
    # ③ THUMBNAIL SIDEBAR ─────────────────────────────────────────────────────
    # ─────────────────────────────────────────────────────────────────────────
    def _clear_thumbnails(self):
        for w in self.thumb_inner.winfo_children():
            w.destroy()
        self.thumb_photos.clear()
        self.thumb_items.clear()
        self.thumb_labels.clear()
        self._thumb_worker.clear()

    def _populate_thumbnails(self):
        """Create placeholder frames for each page, then queue renders."""
        if not self.doc:
            return
        for pno in range(len(self.doc)):
            frame = tk.Frame(self.thumb_inner, bg=SIDEBAR_BG,
                             pady=5, padx=5, cursor="hand2")
            frame.pack(fill=tk.X)
            frame.bind("<Button-1>", lambda e, p=pno: self._goto_page(p))

            # Placeholder label (shown until thumbnail renders)
            ph_img = self._make_placeholder(pno)
            self.thumb_photos[pno] = ph_img
            lbl = tk.Label(frame, image=ph_img, bg="#313244",
                           relief=tk.FLAT, cursor="hand2")
            lbl.image = ph_img
            lbl.pack()
            lbl.bind("<Button-1>", lambda e, p=pno: self._goto_page(p))

            num = tk.Label(frame, text=f"{pno+1}", bg=SIDEBAR_BG,
                           fg=FG_DIM, font=("Segoe UI", 8))
            num.pack()
            num.bind("<Button-1>", lambda e, p=pno: self._goto_page(p))

            self.thumb_items[pno]  = lbl
            self.thumb_labels[pno] = frame

            # Queue background render
            self._thumb_worker.request(self.doc_path, pno)

    def _make_placeholder(self, pno):
        """Grey rectangle with page number as placeholder."""
        img = Image.new("RGB", (THUMB_W, THUMB_H), "#2a2a3e")
        d   = ImageDraw.Draw(img)
        d.text((THUMB_W//2-6, THUMB_H//2-7), str(pno+1), fill="#585b70")
        return ImageTk.PhotoImage(img)

    def _on_thumb_ready(self, pno, img):
        """Called from background thread — schedule UI update on main thread."""
        self.after(0, lambda: self._apply_thumb(pno, img))

    def _apply_thumb(self, pno, img):
        if pno not in self.thumb_items:
            return
        photo = ImageTk.PhotoImage(img)
        self.thumb_photos[pno] = photo
        lbl = self.thumb_items[pno]
        lbl.config(image=photo)
        lbl.image = photo

    def _on_thumb_canvas_resize(self, _=None):
        w = self.thumb_canvas.winfo_width()
        self.thumb_canvas.itemconfig(self._thumb_window, width=w)

    def _on_thumb_click(self, event):
        pass  # handled per-label

    def _goto_page(self, pno):
        self.current_page = pno
        self._render_page()
        self._update_ui_state()

    def _highlight_thumb(self, pno):
        """Add visual selection ring to current page thumbnail."""
        for p, frame in self.thumb_labels.items():
            color = ACCENT if p == pno else SIDEBAR_BG
            frame.config(bg=color)
            for child in frame.winfo_children():
                child.config(bg=color if isinstance(child, tk.Label)
                                      and child != self.thumb_items.get(p)
                             else child.cget("bg")
                             if p != pno else ACCENT)
        # Scroll sidebar to show current thumbnail
        if pno in self.thumb_labels:
            frame = self.thumb_labels[pno]
            # Approximate scroll position
            total = len(self.doc) * (THUMB_H + 36)
            y_pos = pno * (THUMB_H + 36)
            self.thumb_canvas.yview_moveto(max(0, (y_pos - THUMB_H) / total))

    # ─────────────────────────────────────────────────────────────────────────
    # Page Rendering
    # ─────────────────────────────────────────────────────────────────────────
    def _render_page(self):
        if not self.doc:
            return
        key = (self.current_page, self.zoom_idx, self.rotation)
        if key not in self.photo_cache:
            page   = self.doc[self.current_page]
            matrix = fitz.Matrix(self.zoom, self.zoom).prerotate(self.rotation)
            pix    = page.get_pixmap(matrix=matrix, alpha=False)
            img    = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)

            # Draw search highlights on top of rendered image
            if self.search_active and self.search_results:
                draw = ImageDraw.Draw(img, "RGBA")
                for idx, (pno, quad) in enumerate(self.search_results):
                    if pno != self.current_page:
                        continue
                    # quad → scaled pixel rect
                    pts  = [quad.ul, quad.ur, quad.lr, quad.ll]
                    poly = [(p.x * self.zoom, p.y * self.zoom) for p in pts]
                    color = (255, 140, 30, 160) if idx == self.search_idx \
                            else (255, 230, 50, 130)
                    draw.polygon(poly, fill=color)

            self.photo_cache[key] = ImageTk.PhotoImage(img)

        photo = self.photo_cache[key]
        self.canvas.delete("page")
        cw = self.canvas.winfo_width()
        x  = max(photo.width() // 2, cw // 2)
        self.canvas.create_image(x, 10, image=photo, anchor=tk.N, tags="page")
        self.canvas.config(scrollregion=(
            0, 0, max(photo.width(), cw), photo.height() + 20))
        self.canvas.yview_moveto(0)

        self._highlight_thumb(self.current_page)

    def _on_canvas_resize(self, _=None):
        if self.doc:
            self.photo_cache.clear()
            self._render_page()

    def _on_mousewheel(self, event):
        if event.state & 0x4:
            self.zoom_in() if event.delta > 0 else self.zoom_out()
        else:
            self.canvas.yview_scroll(-1*(event.delta//120), "units")

    def _pan_start(self, event):
        self.canvas.scan_mark(event.x, event.y)

    def _pan_move(self, event):
        self.canvas.scan_dragto(event.x, event.y, gain=1)

    # ─────────────────────────────────────────────────────────────────────────
    # UI State sync
    # ─────────────────────────────────────────────────────────────────────────
    def _update_ui_state(self):
        if self.doc:
            n = len(self.doc)
            self.page_var.set(str(self.current_page+1))
            self.total_lbl.config(text=f"/ {n}")
            self.zoom_lbl.config(text=f"{int(self.zoom*100)}%")
        else:
            self.page_var.set("—")
            self.total_lbl.config(text="/ —")
            self.zoom_lbl.config(text="—")

    def toggle_sidebar(self):
        if self.sidebar_frame.winfo_ismapped():
            self.sidebar_frame.pack_forget()
        else:
            self.sidebar_frame.pack(side=tk.LEFT, fill=tk.Y,
                                    before=self.canvas.master)

    def _escape(self):
        if self.highlight_mode:
            self.toggle_highlight()
        elif self.text_mode:
            self.toggle_text_mode()
        elif self.search_bar.winfo_ismapped():
            self.close_search()

    # ─────────────────────────────────────────────────────────────────────────
    # About
    # ─────────────────────────────────────────────────────────────────────────
    def show_about(self):
        messagebox.showinfo(f"About {APP_NAME}",
            f"{APP_NAME} v{APP_VER}\n\n"
            "Lightweight PDF reader & editor for Windows\n\n"
            "New in v2.0:\n"
            "  🔎 Full-document text search with live highlighting\n"
            "  🖍  Drag-to-highlight tool (saved to PDF)\n"
            "  🖼  Visual page thumbnails in sidebar\n\n"
            "Shortcuts:\n"
            "  Ctrl+F    Search   Ctrl+H  Highlight\n"
            "  Ctrl+T    Text     Ctrl+O  Open\n"
            "  ←/→       Pages    Ctrl+0  Fit\n"
            "  F9        Sidebar  Escape  Cancel tool"
        )


# ─── Entry ────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app = LitePDF()
    if len(sys.argv) > 1 and os.path.isfile(sys.argv[1]):
        app.after(150, lambda: app._load_pdf(sys.argv[1]))
    app.mainloop()
