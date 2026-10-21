# -*- coding: utf-8 -*-
"""CheckFolders — мониторинг папок на новые файлы."""
import os
import sys
import json
import time
import ctypes
import fnmatch
import threading
from pathlib import Path
from datetime import datetime

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

# Чтобы тосты Windows показывались с именем приложения, а не Python
try:
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("CheckFolders.App")
except Exception:
    pass

try:
    import pystray
    from PIL import Image, ImageDraw
    HAS_TRAY = True
except ImportError:
    HAS_TRAY = False

try:
    from winotify import Notification
    HAS_WINOTIFY = True
except ImportError:
    HAS_WINOTIFY = False

APP_NAME = "CheckFolders"

if getattr(sys, "frozen", False):              # запущено как exe
    APP_DIR = Path(sys.executable).parent
else:
    APP_DIR = Path(__file__).parent
CONFIG_FILE = APP_DIR / "CheckFolders.json"

DEFAULT_CONFIG = {
    "timer": 10,
    "notify_mode": "all", 
    "folders": [
        {"path": r"F:\GU\CUKS\In",                        "filter": "*.cry", "enabled": True},
        {"path": r"\\Comp-01\sfr-fns\311\InputFNS",       "filter": "*.*",   "enabled": True},
        {"path": r"\\Comp-01\sfr-fns\311\InputSFR",       "filter": "*.*",   "enabled": True},
        {"path": r"\\Comp-01\sfr-fns\440\Input440",       "filter": "*.*",   "enabled": True},
        {"path": r"\\Comp-01\sfr-fns\440\Input440ENS",    "filter": "*.xml", "enabled": True},
        {"path": r"F:\Finist\Finist_Exch\SFR\IN",         "filter": "*.xml", "enabled": True},
        {"path": r"F:\TRANSIT\ProgramBank\DeathSertificate","filter": "*.xml","enabled": True},
    ],
}


class Config:
    def __init__(self):
        self.data = self._load()

    def _load(self):
        if CONFIG_FILE.exists():
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                print("Ошибка чтения конфига:", e)
        cfg = DEFAULT_CONFIG.copy()
        cfg["folders"] = [dict(x) for x in DEFAULT_CONFIG["folders"]]
        return cfg

    def save(self):
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)


class FolderScanner(threading.Thread):
    def __init__(self, config, on_new_files, log):
        super().__init__(daemon=True)
        self.config = config
        self.on_new_files = on_new_files
        self.log = log
        self._stop = threading.Event()
        self._known = {}

    def stop(self):
        self._stop.set()

    def _scan(self, folder):
        path = folder.get("path", "")
        filt = folder.get("filter", "*.*") or "*.*"
        if not path or not os.path.isdir(path):
            return None
        try:
            # "*.*" трактуем как "все файлы", включая без расширения
            pattern = "*" if filt == "*.*" else filt.lower()
            files = set()
            for name in os.listdir(path):
                full = os.path.join(path, name)
                if os.path.isfile(full) and fnmatch.fnmatch(name.lower(), pattern):
                    files.add(name)
            return files
        except Exception as e:
            self.log(f"Ошибка доступа к {path}: {e}")
            return None

    def run(self):
        self.log("Мониторинг запущен.")
        import traceback
        while not self._stop.is_set():
            try:
                timer = max(1, int(self.config.data.get("timer", 10)))
                for _ in range(timer * 10):
                    if self._stop.is_set():
                        return
                    time.sleep(0.1)

                mode = self.config.data.get("notify_mode", "all")
                folders = list(self.config.data.get("folders", []))
                found_total = 0

                for folder in folders:
                    if not folder.get("enabled", True):
                        continue
                    path = folder["path"]
                    files = self._scan(folder)
                    if files is None:
                        continue
                    found_total += len(files)

                    if mode == "all":
                        if files:
                            self.on_new_files(path, sorted(files))
                    else:
                        known = self._known.get(path, set())
                        new_files = files - known
                        if new_files:
                            self.on_new_files(path, sorted(new_files))
                        self._known[path] = files

                # heartbeat: видно, что цикл идёт и сколько файлов видит
                self.log(f"[heartbeat] папок: {len(folders)}, подходящих файлов: {found_total}")
            except Exception:
                self.log("!!! Сканер упал:\n" + traceback.format_exc())
                time.sleep(5)


class FolderDialog:
    def __init__(self, parent, title, initial=None):
        self.result = None
        self.top = tk.Toplevel(parent)
        self.top.title(title)
        self.top.geometry("560x190")
        self.top.transient(parent)
        self.top.grab_set()

        initial = initial or {"path": "", "filter": "*.*", "enabled": True}

        ttk.Label(self.top, text="Путь к папке:").grid(row=0, column=0, sticky="w", padx=8, pady=8)
        self.path_var = tk.StringVar(value=initial["path"])
        ttk.Entry(self.top, textvariable=self.path_var, width=52).grid(row=0, column=1, padx=4)
        ttk.Button(self.top, text="…", width=3, command=self._browse).grid(row=0, column=2, padx=4)

        ttk.Label(self.top, text="Фильтр:").grid(row=1, column=0, sticky="w", padx=8, pady=8)
        self.filter_var = tk.StringVar(value=initial.get("filter", "*.*"))
        ttk.Entry(self.top, textvariable=self.filter_var, width=20).grid(row=1, column=1, sticky="w", padx=4)

        self.enabled_var = tk.BooleanVar(value=initial.get("enabled", True))
        ttk.Checkbutton(self.top, text="Активна", variable=self.enabled_var).grid(row=2, column=1, sticky="w", padx=4)

        btnf = ttk.Frame(self.top)
        btnf.grid(row=3, column=0, columnspan=3, pady=12)
        ttk.Button(btnf, text="OK", command=self._ok).pack(side=tk.LEFT, padx=5)
        ttk.Button(btnf, text="Отмена", command=self.top.destroy).pack(side=tk.LEFT)

        self.top.wait_window() 

    def _browse(self):
        p = filedialog.askdirectory()
        if p:
            self.path_var.set(p)

    def _ok(self):
        path = self.path_var.get().strip()
        if not path:
            messagebox.showerror("Ошибка", "Укажите путь")
            return
        self.result = {
            "path": path,
            "filter": self.filter_var.get().strip() or "*.*",
            "enabled": self.enabled_var.get(),
        }
        self.top.destroy()


class App:
    def __init__(self):
        self.config = Config()
        self.scanner = None
        self.tray = None

        self.root = tk.Tk()
        self.root.title(APP_NAME)
        self.root.geometry("820x520")
        self.root.protocol("WM_DELETE_WINDOW", self.hide_to_tray)

        self._build_ui()
        self._reload_tree()
        self._start_scanner()
        if HAS_TRAY:
            self._build_tray()

    # ---------- UI ----------
    def _build_ui(self):
        top = ttk.Frame(self.root, padding=8)
        top.pack(fill=tk.X)
        ttk.Label(top, text="Интервал проверки (сек):").pack(side=tk.LEFT)
        self.timer_var = tk.StringVar(value=str(self.config.data.get("timer", 10)))
        ttk.Entry(top, textvariable=self.timer_var, width=6).pack(side=tk.LEFT, padx=5)
        ttk.Button(top, text="Применить", command=self.apply_timer).pack(side=tk.LEFT)
        self.status_var = tk.StringVar(value="Мониторинг активен")
        ttk.Label(top, textvariable=self.status_var, foreground="#2a7").pack(side=tk.LEFT, padx=20)
        
        self.spam_var = tk.BooleanVar(value=self.config.data.get("notify_mode", "all") == "all")
        ttk.Checkbutton(
            top,
            text="Повторять уведомления (спам)",
            variable=self.spam_var,
            command=self._toggle_mode,
        ).pack(side=tk.LEFT, padx=10)
        
        mid = ttk.Frame(self.root, padding=8)
        mid.pack(fill=tk.BOTH, expand=True)
        cols = ("path", "filter", "enabled")
        self.tree = ttk.Treeview(mid, columns=cols, show="headings", height=12)
        self.tree.heading("path", text="Папка")
        self.tree.heading("filter", text="Фильтр")
        self.tree.heading("enabled", text="Активна")
        self.tree.column("path", width=550)
        self.tree.column("filter", width=110)
        self.tree.column("enabled", width=90, anchor=tk.CENTER)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb = ttk.Scrollbar(mid, orient=tk.VERTICAL, command=self.tree.yview)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.bind("<Double-1>", lambda e: self.edit_folder())

        btn = ttk.Frame(self.root, padding=8)
        btn.pack(fill=tk.X)
        ttk.Button(btn, text="Добавить",  command=self.add_folder).pack(side=tk.LEFT)
        ttk.Button(btn, text="Изменить",  command=self.edit_folder).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn, text="Удалить",   command=self.remove_folder).pack(side=tk.LEFT)
        ttk.Button(btn, text="Вкл/Выкл",  command=self.toggle_folder).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn, text="Тест уведомления", command=self.test_notify).pack(side=tk.LEFT, padx=20)
        ttk.Button(btn, text="Сохранить", command=self.save_config).pack(side=tk.RIGHT)

        logf = ttk.LabelFrame(self.root, text="Журнал", padding=4)
        logf.pack(fill=tk.BOTH, expand=False, padx=8, pady=(0, 8))
        self.log_text = tk.Text(logf, height=8, state=tk.DISABLED, wrap=tk.WORD)
        self.log_text.pack(fill=tk.BOTH, expand=True)

    def _log(self, msg):
        def do():
            self.log_text.configure(state=tk.NORMAL)
            self.log_text.insert(tk.END, f"[{datetime.now().strftime('%H:%M:%S')}] {msg}\n")
            self.log_text.see(tk.END)
            self.log_text.configure(state=tk.DISABLED)
        try:
            self.root.after(0, do)
        except Exception:
            pass

    def _toggle_mode(self):
        self.config.data["notify_mode"] = "all" if self.spam_var.get() else "new"
        self._log(f"Режим уведомлений: {'все файлы' if self.spam_var.get() else 'только новые'}")

    def _reload_tree(self):
        for i in self.tree.get_children():
            self.tree.delete(i)
        for idx, f in enumerate(self.config.data.get("folders", [])):
            self.tree.insert("", tk.END, iid=str(idx), values=(
                f.get("path", ""),
                f.get("filter", "*.*"),
                "Да" if f.get("enabled", True) else "Нет",
            ))

    def _refresh_row(self, idx):
        f = self.config.data["folders"][idx]
        self.tree.item(str(idx), values=(
            f.get("path", ""), f.get("filter", "*.*"),
            "Да" if f.get("enabled", True) else "Нет",
        ))

    # ---------- folder actions ----------
    def add_folder(self):
        dlg = FolderDialog(self.root, "Добавить папку")
        if dlg.result:
            self.config.data["folders"].append(dlg.result)
            self._reload_tree()
            self.config.save() # <-- Автосохранение
            self._log(f"Добавлена папка: {dlg.result['path']}")

    def edit_folder(self):
        sel = self.tree.selection()
        if not sel:
            return
        idx = int(sel[0])
        dlg = FolderDialog(self.root, "Изменить папку", self.config.data["folders"][idx])
        if dlg.result:
            self.config.data["folders"][idx] = dlg.result
            self._refresh_row(idx)
            self.config.save() # <-- Автосохранение
            self._log(f"Изменена папка: {dlg.result['path']}")

    def remove_folder(self):
        sel = self.tree.selection()
        if not sel:
            return
        idx = int(sel[0])
        if messagebox.askyesno("Удалить", f"Удалить папку?\n{self.config.data['folders'][idx]['path']}"):
            del self.config.data["folders"][idx]
            self._reload_tree()
            self.config.save() # <-- Автосохранение

    def toggle_folder(self):
        sel = self.tree.selection()
        if not sel:
            return
        idx = int(sel[0])
        f = self.config.data["folders"][idx]
        f["enabled"] = not f.get("enabled", True)
        self._refresh_row(idx)
        self.config.save() # <-- Автосохранение

    # ---------- settings ----------
    def apply_timer(self):
        try:
            v = int(self.timer_var.get())
            if v < 1:
                raise ValueError
            self.config.data["timer"] = v
            self._log(f"Интервал: {v} сек")
        except ValueError:
            messagebox.showerror("Ошибка", "Введите целое число больше 0")

    def save_config(self):
        self.apply_timer()
        try:
            self.config.save()
            self._log("Конфигурация сохранена")
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось сохранить: {e}")

    # ---------- notifications ----------
    def _notify(self, title, message):
        # 1) звук — слышен даже если тосты глушатся системой
        try:
            import winsound
            winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
        except Exception:
            pass

        # 2) мигание окна в панели задач (если свернуто в трей — не сработает,
        #    но если окно есть — привлечёт внимание)
        try:
            self.root.after(0, lambda: self.root.bell())
        except Exception:
            pass

        # 3) winotify
        if HAS_WINOTIFY:
            try:
                Notification(app_id=APP_NAME, title=title,
                             msg=message, duration="short").show()
                return
            except Exception as e:
                self._log(f"winotify: {e}")

        # 4) pystray toast
        if HAS_TRAY and self.tray:
            try:
                self.tray.notify(message, title)
                return
            except Exception as e:
                self._log(f"tray notify: {e}")

        # 5) messagebox — самый надёжный, но модальный
        #    (не показываем в спам-режиме, чтобы не блокировать)
        if not self.spam_var.get():
            self.root.after(0, lambda: messagebox.showinfo(title, message))

    def test_notify(self):
        self._notify("Проверка", "Это тестовое уведомление")

    def _on_new_files(self, path, files):
        if len(files) == 1:
            msg = f"{path}\nНовый файл: {files[0]}"
        else:
            head = "\n".join(files[:5])
            tail = f"\n… и ещё {len(files) - 5}" if len(files) > 5 else ""
            msg = f"{path}\nНовых файлов: {len(files)}\n{head}{tail}"
        self._log(f"[{path}] новые: {', '.join(files)}")
        self._notify("Новые файлы", msg)
        self._log(f"[{path}] _notify вызван")

    # ---------- lifecycle ----------
    def _start_scanner(self):
        self.scanner = FolderScanner(self.config, self._on_new_files, self._log)
        self.scanner.start()

    def hide_to_tray(self):
        if HAS_TRAY:
            self.root.withdraw()
            self._log("Свёрнуто в трей")
        else:
            self.quit_app()

    def show_window(self, *args):
        self.root.after(0, self.root.deiconify)
        self.root.after(0, self.root.lift)

    def quit_app(self, *args):
        if self.scanner:
            self.scanner.stop()
        if self.tray:
            try:
                self.tray.stop()
            except Exception:
                pass
        self.root.after(0, self.root.destroy)

    def _build_tray(self):
        img = Image.new("RGB", (64, 64), "white")
        d = ImageDraw.Draw(img)
        d.rectangle([8, 16, 56, 56], outline="black", width=3)       # папка
        d.line([8, 16, 22, 8, 30, 16], fill="black", width=3)         # «уголок»
        d.ellipse([30, 30, 46, 46], fill="#2a7")                     # индикатор

        menu = pystray.Menu(
            pystray.MenuItem("Открыть", self.show_window, default=True),
            pystray.MenuItem("Выход", self.quit_app),
        )
        self.tray = pystray.Icon(APP_NAME, img, APP_NAME, menu)
        threading.Thread(target=self.tray.run, daemon=True).start()

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    App().run()