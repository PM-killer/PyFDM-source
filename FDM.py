import sys
import os
import time
import json
import threading
import requests
import shutil
import zipfile
from pathlib import Path
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLineEdit, QLabel, QProgressBar, QScrollArea,
    QFrame, QFileDialog, QMessageBox, QGraphicsDropShadowEffect
)
from PySide6.QtCore import (
    Qt, Signal, QThread, QPropertyAnimation, QEasingCurve
)
from PySide6.QtGui import QColor, QPixmap

# ============================================================
# تنظیمات
# ============================================================
ICON_PATH = "folder_icon.png" 
SAVE_FILE = str(Path.home() / ".pyfdm_downloads.FASTDOWNLOAD")

# ============================================================
# THEMES
# ============================================================
THEMES = {
    "dark": {
        "bg": "#0b0e14", "surface": "#151a23", "surface_2": "#1f2633",
        "border": "#2b3444", "text": "#e2e8f0", "text_dim": "#94a3b8",
        "accent": "#3b82f6", "accent_hover": "#2563eb",
        "success": "#10b981", "warning": "#f59e0b", "danger": "#ef4444",
        "progress_bg": "#2b3444",
    },
    "light": {
        "bg": "#f8fafc", "surface": "#ffffff", "surface_2": "#f1f5f9",
        "border": "#e2e8f0", "text": "#0f172a", "text_dim": "#64748b",
        "accent": "#3b82f6", "accent_hover": "#2563eb",
        "success": "#10b981", "warning": "#f59e0b", "danger": "#ef4444",
        "progress_bg": "#e2e8f0",
    },
}

# ============================================================
# GLOBAL STATE
# ============================================================
S = {
    "theme": "dark",
    "download_dir": str(Path.home() / "Downloads"),
    "downloads": {}, "cards": {}, "window": None,
    "url_input": None, "dir_label": None, "btn_theme": None,
    "list_layout": None, "empty_widget": None,
    "row_counter": 0
}

# ============================================================
# STYLESHEET
# ============================================================
def build_stylesheet(t):
    return f"""
    QMainWindow, QWidget#root {{ background: {t['bg']}; }}
    QWidget {{
        color: {t['text']};
        font-family: 'Segoe UI', 'San Francisco', 'Roboto', sans-serif;
        font-size: 14px;
    }}
    QLabel {{ background: transparent; }}
    QLabel#title {{ font-size: 24px; font-weight: 800; letter-spacing: -0.5px; }}
    QLabel#subtitle {{ font-size: 13px; color: {t['text_dim']}; }}
    QFrame#card {{
        background: {t['surface']};
        border: 1px solid {t['border']};
        border-radius: 12px;
    }}
    QFrame#downloadCard {{
        background: {t['surface']};
        border: 1px solid {t['border']};
        border-radius: 12px;
    }}
    QFrame#downloadCard:hover {{ border: 1px solid {t['accent']}; }}
    QLineEdit {{
        background: {t['surface_2']};
        border: 2px solid transparent;
        border-radius: 10px;
        padding: 12px 16px;
        color: {t['text']};
        selection-background-color: {t['accent']};
    }}
    QLineEdit:focus {{ border: 2px solid {t['accent']}; background: {t['surface']}; }}
    
    QPushButton {{
        background: {t['surface_2']};
        border: 1px solid {t['border']};
        border-radius: 10px;
        padding: 10px 20px;
        color: {t['text']};
        font-weight: 600;
    }}
    QPushButton:hover {{ background: {t['border']}; }}
    QPushButton:pressed {{ background: {t['accent']}; color: white; }}
    
    QPushButton#primary {{
        background: {t['accent']};
        border: none;
        color: white;
        font-size: 14px;
    }}
    QPushButton#primary:hover {{ background: {t['accent_hover']}; }}
    
    QPushButton#icon {{
        padding: 0; border-radius: 10px; font-size: 18px;
        background: transparent; border: 1px solid transparent;
    }}
    QPushButton#icon:hover {{
        background: {t['surface_2']}; border: 1px solid {t['border']};
    }}

    QProgressBar {{
        background: {t['progress_bg']};
        border: none; border-radius: 4px; height: 6px;
        text-align: center; color: transparent;
    }}
    QProgressBar::chunk {{ background: {t['accent']}; border-radius: 4px; }}
    
    QScrollArea {{ background: transparent; border: none; }}
    QScrollBar:vertical {{ background: transparent; width: 8px; margin: 0; }}
    QScrollBar::handle:vertical {{
        background: {t['border']}; border-radius: 4px; min-height: 40px;
    }}
    QScrollBar::handle:vertical:hover {{ background: {t['text_dim']}; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    
    QLabel#emptyState {{ font-size: 15px; color: {t['text_dim']}; line-height: 1.5; }}

    QMessageBox {{ background-color: {t['surface']}; }}
    QMessageBox QLabel {{ color: {t['text']}; font-size: 13px; }}
    QMessageBox QPushButton {{
        background-color: {t['surface_2']}; color: {t['text']};
        border: 1px solid {t['border']}; padding: 6px 16px; border-radius: 6px;
    }}
    QMessageBox QPushButton:hover {{ background-color: {t['border']}; }}
    """

# ============================================================
# WORKER THREAD (بدون محدودیت سرعت، 32 اتصال همزمان)
# ============================================================
class Worker(QThread):
    progress_sig = Signal(int, int, int)
    status_sig = Signal(int, str)
    error_sig = Signal(int, str)
    finished_sig = Signal(int, bool)

    SEGMENTS = 32       
    CHUNK = 128 * 1024  

    def __init__(self, row, url, filepath, existing_size=0):
        super().__init__()
        self.row = row
        self.url = url
        self.filepath = filepath
        self.existing_size = existing_size
        self._pause = threading.Event()
        self._pause.set()
        self._stop = False
        self._lock = threading.Lock()
        self._downloaded = 0
        self._total = 0
        self._threads = []

    def pause(self):
        self._pause.clear()
        self.status_sig.emit(self.row, "paused")

    def resume(self):
        self._pause.set()
        self.status_sig.emit(self.row, "downloading")

    def cancel(self):
        self._stop = True
        self._pause.set()

    def run(self):
        try:
            head = requests.head(self.url, allow_redirects=True, timeout=15)
            head.raise_for_status()
            self._total = int(head.headers.get("Content-Length", 0))
            accept_ranges = head.headers.get("Accept-Ranges", "").lower() == "bytes"

            if not self._total:
                self.error_sig.emit(self.row, "Server did not return file size.")
                self.finished_sig.emit(self.row, False)
                return

            if self.existing_size >= self._total:
                self.progress_sig.emit(self.row, 100, 0)
                self.status_sig.emit(self.row, "done")
                self.finished_sig.emit(self.row, True)
                return

            remaining = self._total - self.existing_size
            seg_size = remaining // self.SEGMENTS if accept_ranges else remaining

            mode = "r+b" if os.path.exists(self.filepath) and self.existing_size else "wb"
            with open(self.filepath, mode) as f:
                if accept_ranges: f.truncate(self._total)

            self.status_sig.emit(self.row, "downloading")
            self._spawn(seg_size, accept_ranges)

            last_bytes = 0
            last_t = time.time()
            while any(t.is_alive() for t in self._threads):
                if self._stop: break
                time.sleep(0.3)
                with self._lock: done = self._downloaded
                now = time.time()
                speed = int((done - last_bytes) / max(now - last_t, 0.001))
                last_bytes = done
                last_t = now
                pct = int((done / self._total) * 100) if self._total else 0
                self.progress_sig.emit(self.row, min(pct, 100), speed)

            for t in self._threads: t.join()

            if self._stop:
                self.status_sig.emit(self.row, "paused")
                self.finished_sig.emit(self.row, False)
                return

            self.progress_sig.emit(self.row, 100, 0)
            self.status_sig.emit(self.row, "done")
            self.finished_sig.emit(self.row, True)

        except Exception as e:
            self.error_sig.emit(self.row, str(e))
            self.status_sig.emit(self.row, "error")
            self.finished_sig.emit(self.row, False)

    def _spawn(self, seg_size, accept_ranges):
        if not accept_ranges:
            t = threading.Thread(target=self._segment, args=(self.existing_size, self._total - 1, 0), daemon=True)
            self._threads = [t]
            t.start()
            return
        self._threads = []
        for i in range(self.SEGMENTS):
            start = self.existing_size + i * seg_size
            end = self._total - 1 if i == self.SEGMENTS - 1 else start + seg_size - 1
            if start > end: continue
            t = threading.Thread(target=self._segment, args=(start, end, i), daemon=True)
            self._threads.append(t)
            t.start()

    def _segment(self, start, end, idx):
        try:
            headers = {"Range": f"bytes={start}-{end}"}
            with requests.get(self.url, headers=headers, stream=True, timeout=30) as r:
                r.raise_for_status()
                with open(self.filepath, "r+b") as f:
                    f.seek(start)
                    for chunk in r.iter_content(chunk_size=self.CHUNK):
                        if self._stop: return
                        self._pause.wait()
                        if not chunk: continue
                        
                        f.write(chunk)

                        with self._lock:
                            self._downloaded += len(chunk)
        except Exception as e:
            self.error_sig.emit(self.row, f"Segment {idx}: {e}")

# ============================================================
# HELPERS & SAVE/LOAD/EXPORT/IMPORT
# ============================================================
def human_speed(bps):
    if bps > 1024 * 1024: return f"{bps/1024/1024:.1f} MB/s"
    if bps > 1024: return f"{bps/1024:.1f} KB/s"
    return f"{bps} B/s"

def save_state():
    data = []
    for row, info in S["downloads"].items():
        data.append({
            "url": info["url"],
            "path": info["path"],
            "status": info.get("status", "paused")
        })
    try:
        with open(SAVE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"Save error: {e}")

def load_state():
    if not os.path.exists(SAVE_FILE): return
    try:
        with open(SAVE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            for item in data:
                url = item.get("url")
                path = item.get("path")
                if item.get("status") != "done":
                    add_download(url=url, filepath=path, auto_start=False)
    except Exception as e:
        print(f"Load error: {e}")

def export_file():
    path, _ = QFileDialog.getSaveFileName(S["window"], "Export Download", "", "Fast Download (*.FASTDOWNLOAD)")
    if path:
        if not path.endswith(".FASTDOWNLOAD"):
            path += ".FASTDOWNLOAD"
        try:
            with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
                data = []
                for row, info in S["downloads"].items():
                    data.append({
                        "url": info["url"],
                        "filename": os.path.basename(info["path"]),
                        "status": info.get("status", "paused")
                    })
                zf.writestr("downloads.json", json.dumps(data, indent=2))
                for info in S["downloads"].values():
                    if os.path.exists(info["path"]):
                        zf.write(info["path"], os.path.basename(info["path"]))
            QMessageBox.information(S["window"], "Success", "Export successful! File includes partial downloads.")
        except Exception as e:
            QMessageBox.warning(S["window"], "Error", str(e))

def import_file():
    path, _ = QFileDialog.getOpenFileName(S["window"], "Import Download", "", "Fast Download (*.FASTDOWNLOAD)")
    if path:
        try:
            with zipfile.ZipFile(path, "r") as zf:
                for name in zf.namelist():
                    if name != "downloads.json":
                        target = os.path.join(S["download_dir"], name)
                        with zf.open(name) as source, open(target, "wb") as target_file:
                            shutil.copyfileobj(source, target_file)
                json_data = zf.read("downloads.json").decode("utf-8")
                data = json.loads(json_data)
                for item in data:
                    url = item["url"]
                    filepath = os.path.join(S["download_dir"], item["filename"])
                    add_download(url=url, filepath=filepath, auto_start=False)
            QMessageBox.information(S["window"], "Success", "Import successful! Files are ready to resume.")
        except Exception as e:
            QMessageBox.warning(S["window"], "Error", str(e))

def apply_theme(theme):
    S["theme"] = theme
    S["window"].setStyleSheet(build_stylesheet(THEMES[theme]))
    S["btn_theme"].setText("☀️" if theme == "dark" else "🌙")
    if S["theme"] == "light":
        S["dir_label"].setStyleSheet("font-size: 13px; color: #64748b;")
    else:
        S["dir_label"].setStyleSheet("font-size: 13px; color: #94a3b8;")

def toggle_theme():
    apply_theme("light" if S["theme"] == "dark" else "dark")

# ============================================================
# DOWNLOAD CARD
# ============================================================
def make_card(row, filename):
    card = QFrame()
    card.setObjectName("downloadCard")
    card.setMinimumHeight(84)

    layout = QHBoxLayout(card)
    layout.setContentsMargins(20, 16, 20, 16)
    layout.setSpacing(16)

    icon_lbl = QLabel("📄")
    icon_lbl.setStyleSheet("font-size: 26px;")
    layout.addWidget(icon_lbl)

    mid = QVBoxLayout()
    mid.setSpacing(8)

    name_lbl = QLabel(filename)
    name_lbl.setStyleSheet("font-weight: 600; font-size: 14px;")
    mid.addWidget(name_lbl)

    progress = QProgressBar()
    progress.setTextVisible(False)
    progress.setValue(0)
    mid.addWidget(progress)

    stats_row = QHBoxLayout()
    size_lbl = QLabel("—")
    speed_lbl = QLabel("—")
    status_lbl = QLabel("در انتظار")
    
    for lbl in [size_lbl, speed_lbl, status_lbl]:
        lbl.setStyleSheet(f"font-size: 12px; color: {THEMES[S['theme']]['text_dim']}; font-weight: 500;")
    
    stats_row.addWidget(size_lbl)
    stats_row.addWidget(speed_lbl)
    stats_row.addStretch()
    stats_row.addWidget(status_lbl)
    mid.addLayout(stats_row)

    layout.addLayout(mid, 1)

    btn_pause = QPushButton("⏸")
    btn_pause.setObjectName("icon")
    btn_pause.setFixedSize(36, 36)
    btn_pause.setVisible(False)
    btn_pause.clicked.connect(lambda: pause_row(row))

    btn_resume = QPushButton("▶")
    btn_resume.setObjectName("icon")
    btn_resume.setFixedSize(36, 36)
    btn_resume.setVisible(False)
    btn_resume.clicked.connect(lambda: resume_row(row))

    btn_remove = QPushButton("🗑")
    btn_remove.setObjectName("icon")
    btn_remove.setFixedSize(36, 36)
    btn_remove.setToolTip("حذف از لیست")
    btn_remove.clicked.connect(lambda: remove_row(row))

    layout.addWidget(btn_pause)
    layout.addWidget(btn_resume)
    layout.addWidget(btn_remove)

    card.setMaximumHeight(0)
    anim = QPropertyAnimation(card, b"maximumHeight")
    anim.setDuration(300)
    anim.setStartValue(0)
    anim.setEndValue(84)
    anim.setEasingCurve(QEasingCurve.OutCubic)
    anim.start()
    card._anim = anim

    return {
        "frame": card, "name_lbl": name_lbl, "progress": progress,
        "size_lbl": size_lbl, "speed_lbl": speed_lbl, "status_lbl": status_lbl,
        "btn_pause": btn_pause, "btn_resume": btn_resume, "btn_remove": btn_remove
    }

def set_card_status(row, st):
    card = S["cards"].get(row)
    if not card: return
    t = THEMES[S["theme"]]
    colors = {"downloading": t["success"], "paused": t["warning"], "done": t["accent"], "error": t["danger"], "starting": t["text_dim"]}
    labels = {"downloading": "در حال دانلود", "paused": "متوقف", "done": "کامل شد", "error": "خطا", "starting": "در انتظار"}
    
    card["status_lbl"].setText(labels.get(st, st))
    card["status_lbl"].setStyleSheet(f"font-size: 12px; font-weight: 700; color: {colors.get(st, t['text_dim'])};")

    if st == "downloading":
        card["btn_pause"].setVisible(True)
        card["btn_resume"].setVisible(False)
    elif st == "paused":
        card["btn_pause"].setVisible(False)
        card["btn_resume"].setVisible(True)
    else:
        card["btn_pause"].setVisible(False)
        card["btn_resume"].setVisible(False)
    
    save_state()

# ============================================================
# ROW ACTIONS & SIGNALS
# ============================================================
def pause_row(row):
    if row in S["downloads"]: S["downloads"][row]["worker"].pause()

def resume_row(row):
    if row in S["downloads"]:
        w = S["downloads"][row]["worker"]
        if w.isRunning():
            w.resume()
        else:
            w.start()

def resume_all():
    for row in list(S["downloads"].keys()):
        w = S["downloads"][row]["worker"]
        if not w.isRunning():
            w.start()
        else:
            w.resume()

def remove_row(row):
    if row in S["downloads"]:
        S["downloads"][row]["worker"].cancel()
        S["cards"][row]["frame"].hide()
        S["cards"][row]["frame"].deleteLater()
        del S["downloads"][row]
        del S["cards"][row]
        check_empty()
        save_state()

def on_progress(row, pct, speed):
    card = S["cards"].get(row)
    if not card: return
    card["progress"].setValue(pct)
    card["size_lbl"].setText(f"{pct}%")
    card["speed_lbl"].setText(human_speed(speed) if speed else "—")

def on_status(row, st):
    set_card_status(row, st)
    if row in S["downloads"]: S["downloads"][row]["status"] = st

def on_error(row, msg):
    QMessageBox.warning(S["window"], "Download error", msg)

def on_finished(row, ok):
    if ok and row in S["downloads"]:
        S["downloads"][row]["status"] = "done"
        save_state()

# ============================================================
# ACTIONS
# ============================================================
def check_empty():
    if not S["downloads"]:
        S["empty_widget"].setVisible(True)
    else:
        S["empty_widget"].setVisible(False)

def add_download(url=None, filepath=None, auto_start=True):
    try:
        if url is None:
            url = S["url_input"].text().strip()
        if not url: 
            return
        
        if not url.startswith("http://") and not url.startswith("https://"):
            url = "https://" + url
        
        if filepath is None:
            name = url.split("/")[-1].split("?")[0] or f"file_{int(time.time())}"
            filepath = os.path.join(S["download_dir"], name)
        
        existing = os.path.getsize(filepath) if os.path.exists(filepath) else 0

        row = S["row_counter"]
        S["row_counter"] += 1

        card = make_card(row, os.path.basename(filepath))
        S["list_layout"].insertWidget(S["list_layout"].count() - 1, card["frame"])
        S["cards"][row] = card
        S["empty_widget"].setVisible(False)
        set_card_status(row, "starting")

        w = Worker(row, url, filepath, existing)
        w.progress_sig.connect(on_progress)
        w.status_sig.connect(on_status)
        w.error_sig.connect(on_error)
        w.finished_sig.connect(on_finished)

        S["downloads"][row] = {"worker": w, "url": url, "path": filepath, "status": "starting"}
        
        if auto_start:
            w.start()
        else:
            set_card_status(row, "paused")
        
        if S["url_input"]: 
            S["url_input"].clear()
        save_state()

    except Exception as e:
        QMessageBox.critical(S["window"], "Error", f"Could not add download: {str(e)}")

def change_dir():
    d = QFileDialog.getExistingDirectory(S["window"], "Choose folder", S["download_dir"])
    if d:
        S["download_dir"] = d
        S["dir_label"].setText(d)

def on_close(event):
    save_state()
    for d in S["downloads"].values(): d["worker"].cancel()
    for d in S["downloads"].values(): d["worker"].wait(2000)
    event.accept()

# ============================================================
# BUILD UI
# ============================================================
def build_window():
    window = QMainWindow()
    window.setWindowTitle("PyFDM — Fast Download Manager")
    window.resize(920, 650) 
    S["window"] = window

    root = QWidget()
    root.setObjectName("root")
    window.setCentralWidget(root)

    main_layout = QVBoxLayout(root)
    main_layout.setContentsMargins(32, 28, 32, 28)
    main_layout.setSpacing(24)

    # هدر
    header = QHBoxLayout()
    title_box = QVBoxLayout()
    title_box.setSpacing(4)
    title = QLabel("PyFDM"); title.setObjectName("title")
    subtitle = QLabel("Fast Download Manager"); subtitle.setObjectName("subtitle")
    title_box.addWidget(title); title_box.addWidget(subtitle)
    
    header.addLayout(title_box)
    header.addStretch()

    # دکمه‌های ابزار بالا
    btn_import = QPushButton("📥 Import")
    btn_import.clicked.connect(import_file)
    btn_export = QPushButton("📤 Export")
    btn_export.clicked.connect(export_file)
    
    btn_resume_all = QPushButton("▶ Resume All")
    btn_resume_all.setToolTip("ادامه دادن همه دانلودهای متوقف شده")
    btn_resume_all.clicked.connect(resume_all)
    
    header.addWidget(btn_import)
    header.addWidget(btn_export)
    header.addWidget(btn_resume_all)
    header.addSpacing(16)

    btn_theme = QPushButton("☀️")
    btn_theme.setObjectName("icon")
    btn_theme.setFixedSize(40, 40)
    btn_theme.clicked.connect(toggle_theme)
    S["btn_theme"] = btn_theme
    header.addWidget(btn_theme)
    main_layout.addLayout(header)

    # کارت ورودی
    input_card = QFrame()
    input_card.setObjectName("card")
    shadow = QGraphicsDropShadowEffect()
    shadow.setBlurRadius(20); shadow.setColor(QColor(0, 0, 0, 30)); shadow.setOffset(0, 4)
    input_card.setGraphicsEffect(shadow)

    input_layout = QVBoxLayout(input_card)
    input_layout.setContentsMargins(24, 24, 24, 24)
    input_layout.setSpacing(16)

    url_row = QHBoxLayout(); url_row.setSpacing(12)
    url_input = QLineEdit()
    url_input.setPlaceholderText("Paste download link here…")
    url_input.returnPressed.connect(add_download)
    S["url_input"] = url_input
    """
    btn_add = QPushButton("➕  Add Download")
    btn_add.setObjectName("primary")
    btn_add.clicked.connect(add_download)
    btn_add.setCursor(Qt.PointingHandCursor)"""
    
    url_row.addWidget(url_input, 1)

    input_layout.addLayout(url_row)

    dir_row = QHBoxLayout(); dir_row.setSpacing(12)
    
    dir_lbl = QLabel()
    if os.path.exists(ICON_PATH):
        pixmap = QPixmap(ICON_PATH)
        dir_lbl.setPixmap(pixmap.scaled(24, 24, Qt.KeepAspectRatio, Qt.SmoothTransformation))
    else:
        dir_lbl.setText("📁")
        dir_lbl.setStyleSheet("font-size: 18px;")
    
    dir_label = QLabel(S["download_dir"])
    dir_label.setStyleSheet(f"font-size: 13px; color: {THEMES['dark']['text_dim']};")
    S["dir_label"] = dir_label
    
    btn_dir = QPushButton("Change Folder")
    btn_dir.setCursor(Qt.PointingHandCursor)
    btn_dir.clicked.connect(change_dir)
    
    dir_row.addWidget(dir_lbl)
    dir_row.addWidget(dir_label, 1)
    dir_row.addWidget(btn_dir)
    input_layout.addLayout(dir_row)

    main_layout.addWidget(input_card)

    # هدر لیست دانلودها
    downloads_header = QHBoxLayout()
    d_title = QLabel("Downloads")
    d_title.setStyleSheet("font-size: 16px; font-weight: 700;")
    downloads_header.addWidget(d_title)
    downloads_header.addStretch()
    main_layout.addLayout(downloads_header)

    # اسکرول لیست
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    scroll.setStyleSheet("QScrollArea { background: transparent; } QWidget#scrollContent { background: transparent; }")

    list_container = QWidget()
    list_container.setObjectName("scrollContent")
    list_layout = QVBoxLayout(list_container)
    list_layout.setContentsMargins(0, 0, 4, 0)
    list_layout.setSpacing(12)
    list_layout.addStretch()
    S["list_layout"] = list_layout

    scroll.setWidget(list_container)
    main_layout.addWidget(scroll, 1)

    # حالت خالی
    empty_widget = QWidget()
    empty_layout = QVBoxLayout(empty_widget)
    empty_layout.setAlignment(Qt.AlignCenter)
    empty_layout.setSpacing(16)

    empty_icon = QLabel("📥")
    empty_icon.setStyleSheet("font-size: 64px;")
    empty_icon.setAlignment(Qt.AlignCenter)

    empty_text = QLabel("No downloads yet\nPaste a link above to get started")
    empty_text.setObjectName("emptyState")
    empty_text.setAlignment(Qt.AlignCenter)

    empty_layout.addWidget(empty_icon)
    empty_layout.addWidget(empty_text)
    
    S["empty_widget"] = empty_widget
    list_layout.insertWidget(0, empty_widget)

    window.closeEvent = on_close
    return window

# ============================================================
def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    win = build_window()
    apply_theme("dark")
    load_state()
    win.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()