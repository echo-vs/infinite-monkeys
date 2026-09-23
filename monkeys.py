"""Бесконечные обезьяны: GUI.

Запуск:  python3 monkeys.py
"""
import math
import os
import re
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from engine import CTX, DISPLAY_MONKEYS, FORBIDDEN, MonkeyEngine
from search import Search

ALPHABETS = {
    "Русский (а-я)": "абвгдежзийклмнопрстуфхцчшщъыьэюя",
    "Русский + ё и знаки": "абвгдеёжзийклмнопрстуфхцчшщъыьэюя.,!?-",
    "Английский (a-z)": "abcdefghijklmnopqrstuvwxyz",
    "Английский + знаки": "abcdefghijklmnopqrstuvwxyz.,!?'-",
    "Английский A-Z a-z 0-9": "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789",
    "Цифры": "0123456789",
    "Своя": "",
}
DEFAULT_WORDS = "да\nкот\nмама\nобезьяна\nбыть или не быть\ncat\nmonkey\nto be or not to be"
DEFAULT_SAVE_DIR = Path(__file__).resolve().parent / "сохранения"

UNIVERSE_AGE_YEARS = 13.8e9
POLL_MS = 50
STATS_MS = 250
SEARCH_POLL_MS = 100
MAX_LOG_LINES = 500
TYPEWRITER_ROWS = 8
GB = 1024 ** 3
MB = 1024 ** 2


def fmt_int(n):
    return f"{int(n):,}".replace(",", " ")


def fmt_bytes(n):
    for unit, size in (("ГБ", GB), ("МБ", MB), ("КБ", 1024)):
        if n >= size:
            return f"{n / size:.2f} {unit}"
    return f"{int(n)} Б"


def fmt_duration(sec):
    if sec is None or math.isinf(sec):
        return "∞"
    if sec < 1:
        return "< 1 сек"
    for unit, size in (("лет", 365.25 * 86400), ("дн", 86400), ("ч", 3600), ("мин", 60)):
        if sec >= size:
            value = sec / size
            if unit == "лет" and value >= UNIVERSE_AGE_YEARS / 10:
                return f"{value / UNIVERSE_AGE_YEARS:.1e} × возраст Вселенной"
            if unit == "лет" and value >= 1e6:
                return f"{value:.1e} лет"
            return f"{value:.1f} {unit}"
    return f"{sec:.0f} сек"


def fmt_clock(sec):
    sec = int(sec)
    return f"{sec // 3600:02d}:{sec % 3600 // 60:02d}:{sec % 60:02d}"


def slug(name):
    return re.sub(r"[^\w-]+", "_", name).strip("_") or "стая"


def normalize(word, alphabet):
    word = " ".join(word.split()) if " " in alphabet else word.strip()
    if not any(c.isupper() for c in alphabet):
        word = word.lower()
    return word


def missing_keys(word, alphabet):
    return sorted({c for c in word if c not in alphabet})


def keys_text(chars):
    return ", ".join("пробел" if c == " " else f"«{c}»" for c in chars)


class WordState:
    def __init__(self, word):
        self.word = word
        self.found = 0
        self.best = 0
        self.first = None  # (время, обезьяна)


class Group:
    """Стая обезьян со своей клавиатурой."""

    def __init__(self, name, n_monkeys, preset, keys, space, rate, workers=0):
        self.name = name
        self.n_monkeys = n_monkeys
        self.preset = preset
        self.keys = keys
        self.space = space
        self.rate = rate          # 0 = турбо
        self.workers = workers    # 0 = авто
        self.engine = MonkeyEngine()
        self.words = {}
        self.tails = {}
        self.speed = 0.0
        self.last_chars = 0

    @property
    def alphabet(self):
        chars = "".join(c for c in self.keys if c != " " and c not in FORBIDDEN)
        if self.space:
            chars += " "
        return "".join(dict.fromkeys(chars))  # без повторов, порядок сохраняется

    def keyboard_label(self):
        label = self.preset if self.preset != "Своя" else f"своя ({len(self.alphabet)})"
        return label + (" + пробел" if self.space else "")

    def speed_label(self):
        return "турбо" if self.rate == 0 else f"{self.rate}/с"


class GroupDialog:
    """Окно добавления и изменения стаи."""

    def __init__(self, parent, mono, group=None):
        self.result = None
        self.win = tk.Toplevel(parent)
        self.win.title("Стая обезьян")
        self.win.transient(parent)
        self.win.resizable(False, False)
        f = ttk.Frame(self.win, padding=12)
        f.pack(fill="both", expand=True)

        g = group or Group("Новая стая", 1000, "Русский (а-я)",
                           ALPHABETS["Русский (а-я)"], True, 0)
        self.name = tk.StringVar(value=g.name)
        self.n = tk.IntVar(value=g.n_monkeys)
        self.workers = tk.IntVar(value=g.workers)
        self.preset = tk.StringVar(value=g.preset)
        self.keys = tk.StringVar(value=g.keys)
        self.space = tk.BooleanVar(value=g.space)
        self.turbo = tk.BooleanVar(value=g.rate == 0)
        self.rate = tk.IntVar(value=g.rate or 5)

        ttk.Label(f, text="Название:").grid(row=0, column=0, sticky="w")
        ttk.Entry(f, textvariable=self.name, width=32).grid(row=0, column=1, sticky="ew", pady=2)
        ttk.Label(f, text="Обезьян:").grid(row=1, column=0, sticky="w")
        ttk.Spinbox(f, from_=1, to=10_000_000, increment=100, textvariable=self.n,
                    width=12).grid(row=1, column=1, sticky="w", pady=2)
        ttk.Label(f, text="Процессов (0 = авто):").grid(row=2, column=0, sticky="w")
        ttk.Spinbox(f, from_=0, to=256, textvariable=self.workers,
                    width=6).grid(row=2, column=1, sticky="w", pady=2)

        ttk.Label(f, text="Клавиатура:").grid(row=3, column=0, sticky="w", pady=(8, 0))
        cb = ttk.Combobox(f, textvariable=self.preset, values=list(ALPHABETS),
                          state="readonly", width=30)
        cb.grid(row=3, column=1, sticky="ew", pady=(8, 2))
        cb.bind("<<ComboboxSelected>>", lambda _e: self._on_preset())
        ttk.Entry(f, textvariable=self.keys, font=mono, width=32).grid(
            row=4, column=0, columnspan=2, sticky="ew")
        ttk.Checkbutton(f, text="Клавиша «пробел»", variable=self.space,
                        command=self._info).grid(row=5, column=0, columnspan=2, sticky="w")
        self.info = ttk.Label(f, foreground="gray")
        self.info.grid(row=6, column=0, columnspan=2, sticky="w")
        self.keys.trace_add("write", lambda *_: self._on_keys())

        ttk.Label(f, text="Скорость:").grid(row=7, column=0, sticky="w", pady=(8, 0))
        ttk.Checkbutton(f, text="Турбо (как можно быстрее)", variable=self.turbo,
                        command=self._info).grid(row=7, column=1, sticky="w", pady=(8, 0))
        ttk.Scale(f, from_=1, to=60, variable=self.rate, orient="horizontal",
                  command=lambda _v: self._info()).grid(row=8, column=1, sticky="ew")
        self.rate_label = ttk.Label(f, foreground="gray")
        self.rate_label.grid(row=9, column=1, sticky="w")

        buttons = ttk.Frame(f)
        buttons.grid(row=10, column=0, columnspan=2, sticky="e", pady=(12, 0))
        ttk.Button(buttons, text="OK", command=self._ok).pack(side="left")
        ttk.Button(buttons, text="Отмена", command=self.win.destroy).pack(side="left", padx=(6, 0))
        self.win.bind("<Return>", lambda _e: self._ok())
        self.win.bind("<Escape>", lambda _e: self.win.destroy())

        self._info()
        self.win.grab_set()
        parent.wait_window(self.win)

    def _alphabet(self):
        return Group("", 1, "", self.keys.get(), self.space.get(), 0).alphabet

    def _on_preset(self):
        chars = ALPHABETS[self.preset.get()]
        if chars:
            self.keys.set(chars)
        self._info()

    def _on_keys(self):
        if self.keys.get() != ALPHABETS.get(self.preset.get()):
            self.preset.set("Своя")
        self._info()

    def _info(self):
        n = len(self._alphabet())
        self.info.configure(text=f"{n} клавиш, шанс каждой 1/{n}" if n else "Клавиатура пуста")
        self.rate_label.configure(text="без ограничений" if self.turbo.get()
                                  else f"{self.rate.get()} нажатий/с на обезьяну")

    def _ok(self):
        try:
            n, workers = int(self.n.get()), int(self.workers.get())
        except (tk.TclError, ValueError):
            messagebox.showerror("Ошибка", "Количество — целые числа.", parent=self.win)
            return
        if n < 1 or workers < 0:
            messagebox.showerror("Ошибка", "Нужна хотя бы одна обезьяна.", parent=self.win)
            return
        if len(self._alphabet()) < 2:
            messagebox.showerror("Ошибка", "Нужно хотя бы 2 клавиши.", parent=self.win)
            return
        self.result = Group(self.name.get().strip() or "Стая", n, self.preset.get(),
                            self.keys.get(), self.space.get(),
                            0 if self.turbo.get() else int(self.rate.get()), workers)
        self.win.destroy()


class App:
    def __init__(self, root):
        self.root = root
        self.groups = [
            Group("Русские", 1000, "Русский (а-я)", ALPHABETS["Русский (а-я)"], True, 0),
            Group("Англичане", 1000, "Английский (a-z)", ALPHABETS["Английский (a-z)"], True, 0),
        ]
        self.running = False
        self.started_at = None
        self.elapsed_before = 0.0
        self.saved_used = None
        self.save_limit = 0
        self.session_dir = None
        self.search = None
        self.search_started = 0.0

        root.title("Бесконечные обезьяны")
        w = min(1300, root.winfo_screenwidth() - 40)
        h = min(860, root.winfo_screenheight() - 80)
        root.geometry(f"{w}x{h}+10+10")
        root.minsize(min(1000, w), min(600, h))
        root.bind("<F5>", lambda _e: self.start() if not self.running else None)
        root.bind("<Escape>", lambda _e: self.stop())
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.mono = ("DejaVu Sans Mono", 11) if os.name != "nt" else ("Consolas", 11)

        nb = ttk.Notebook(root)
        nb.pack(fill="both", expand=True)
        run_tab = ttk.Frame(nb)
        search_tab = ttk.Frame(nb, padding=10)
        nb.add(run_tab, text="  Обезьяны  ")
        nb.add(search_tab, text="  Поиск в сохранённом  ")

        self._build_settings(run_tab)
        self._build_main(run_tab)
        self._build_search(search_tab)
        self.refresh_groups()
        self.root.after(POLL_MS, self.poll)
        self.root.after(STATS_MS, self.update_stats)

    # ---------- интерфейс: запуск ----------

    def _build_settings(self, parent):
        side = ttk.Frame(parent, padding=10)
        side.pack(side="left", fill="y")
        bold = ("", 12, "bold")

        # кнопки сверху, чтобы их не обрезало на маленьком экране
        row = ttk.Frame(side)
        row.pack(fill="x", pady=(0, 10))
        self.start_btn = ttk.Button(row, text="▶ Запустить обезьян (F5)", command=self.start)
        self.start_btn.pack(side="left", fill="x", expand=True, ipady=4)
        self.stop_btn = ttk.Button(row, text="■ Стоп (Esc)", command=self.stop, state="disabled")
        self.stop_btn.pack(side="left", padx=(6, 0), ipady=4)

        ttk.Label(side, text="Стаи обезьян", font=bold).pack(anchor="w")
        self.groups_tree = ttk.Treeview(side, columns=("n", "keys", "speed"), height=4,
                                        show="tree headings", selectmode="browse")
        self.groups_tree.heading("#0", text="Стая")
        self.groups_tree.heading("n", text="Обезьян")
        self.groups_tree.heading("keys", text="Клавиатура")
        self.groups_tree.heading("speed", text="Скорость")
        for col, width in (("#0", 95), ("n", 70), ("keys", 150), ("speed", 60)):
            self.groups_tree.column(col, width=width, stretch=False)
        self.groups_tree.pack(fill="x", pady=4)
        self.groups_tree.bind("<Double-1>", lambda _e: self.edit_group())
        row = ttk.Frame(side)
        row.pack(fill="x")
        self.group_buttons = [
            ttk.Button(row, text="Добавить", command=self.add_group),
            ttk.Button(row, text="Изменить", command=self.edit_group),
            ttk.Button(row, text="Удалить", command=self.remove_group),
        ]
        for b in self.group_buttons:
            b.pack(side="left", padx=(0, 4))

        ttk.Label(side, text="Что ищем (по фразе в строке)", font=bold).pack(anchor="w", pady=(10, 0))
        self.words_text = tk.Text(side, width=34, height=5, font=self.mono)
        self.words_text.pack(fill="x", pady=4)
        self.words_text.insert("1.0", DEFAULT_WORDS)
        ttk.Label(side, text="Каждая стая ищет то, что может напечатать.",
                  foreground="gray").pack(anchor="w")
        ttk.Label(side, text="Быстро добавить (можно на ходу):").pack(anchor="w", pady=(4, 0))
        row = ttk.Frame(side)
        row.pack(fill="x", pady=4)
        self.quick = tk.StringVar()
        entry = ttk.Entry(row, textvariable=self.quick, font=self.mono)
        entry.pack(side="left", fill="x", expand=True)
        entry.bind("<Return>", lambda _e: self.quick_add())
        ttk.Button(row, text="+", width=3, command=self.quick_add).pack(side="left", padx=(4, 0))

        box = ttk.LabelFrame(side, text="Сохранение напечатанного", padding=6)
        box.pack(fill="x", pady=(10, 0))
        self.save_on = tk.BooleanVar(value=False)
        ttk.Checkbutton(box, text="Сохранять всё в папку", variable=self.save_on).grid(
            row=0, column=0, columnspan=3, sticky="w")
        self.save_dir = tk.StringVar(value=str(DEFAULT_SAVE_DIR))
        ttk.Entry(box, textvariable=self.save_dir).grid(row=1, column=0, columnspan=2, sticky="ew")
        ttk.Button(box, text="…", width=3, command=self.pick_save_dir).grid(row=1, column=2, padx=(4, 0))
        ttk.Label(box, text="Лимит всего, ГБ (0 = нет):").grid(row=2, column=0, sticky="w", pady=(4, 0))
        self.save_limit_gb = tk.DoubleVar(value=2.0)
        ttk.Spinbox(box, from_=0, to=100000, increment=0.5, width=8,
                    textvariable=self.save_limit_gb).grid(row=2, column=1, sticky="w", pady=(4, 0))
        ttk.Label(box, text="Размер одного файла, МБ:").grid(row=3, column=0, sticky="w")
        self.file_limit_mb = tk.IntVar(value=100)
        ttk.Spinbox(box, from_=1, to=100000, increment=50, width=8,
                    textvariable=self.file_limit_mb).grid(row=3, column=1, sticky="w")
        self.stop_on_full = tk.BooleanVar(value=False)
        ttk.Checkbutton(box, text="Остановить обезьян, когда лимит заполнен",
                        variable=self.stop_on_full).grid(row=4, column=0, columnspan=3, sticky="w")
        box.columnconfigure(0, weight=1)

        self.stop_when_done = tk.BooleanVar(value=False)
        ttk.Checkbutton(side, text="Стоп, когда найдено всё",
                        variable=self.stop_when_done).pack(anchor="w", pady=(8, 0))

    def _build_main(self, parent):
        main = ttk.Frame(parent, padding=(0, 10, 10, 10))
        main.pack(side="left", fill="both", expand=True)

        stats = ttk.Frame(main)
        stats.pack(fill="x")
        self.stat_vars = {}
        for i, (key, title) in enumerate((("time", "Время"), ("chars", "Напечатано символов"),
                                          ("speed", "Скорость, симв/с"), ("monkeys", "Обезьян"),
                                          ("saved", "Сохранено"))):
            box = ttk.LabelFrame(stats, text=title, padding=(8, 2))
            box.grid(row=0, column=i, sticky="ew", padx=(0 if i == 0 else 6, 0))
            stats.columnconfigure(i, weight=1)
            var = tk.StringVar(value="—")
            ttk.Label(box, textvariable=var, font=("", 13, "bold")).pack(anchor="w")
            self.stat_vars[key] = var

        box = ttk.LabelFrame(main, text="Обезьяны за работой", padding=4)
        box.pack(fill="x", pady=(10, 0))
        self.typewriters = tk.Text(box, height=TYPEWRITER_ROWS, font=self.mono, wrap="none",
                                   bg="#1e1e1e", fg="#d4d4d4", insertwidth=0,
                                   state="disabled", cursor="arrow")
        self.typewriters.pack(fill="x")
        self.typewriters.tag_configure("name", foreground="#c586c0")
        self.typewriters.tag_configure("hit", background="#2e7d32", foreground="white")
        self.typewriters.tag_configure("caret", foreground="#ffcc00")

        box = ttk.LabelFrame(main, text="Слежка за словами", padding=4)
        box.pack(fill="both", expand=True, pady=(10, 0))
        cols = ("found", "best", "progress", "first", "expect")
        self.table = ttk.Treeview(box, columns=cols, show="tree headings", height=8)
        self.table.heading("#0", text="Стая / слово")
        self.table.column("#0", width=200)
        for col, title, width in (("found", "Найдено раз", 100), ("best", "Лучшая попытка", 190),
                                  ("progress", "Прогресс", 75), ("first", "Впервые", 190),
                                  ("expect", "Ожидание ≈", 220)):
            self.table.heading(col, text=title)
            self.table.column(col, width=width, anchor="w")
        scroll = ttk.Scrollbar(box, command=self.table.yview)
        self.table.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.table.pack(fill="both", expand=True)
        self.table.tag_configure("done", background="#d9f2d9")
        self.table.tag_configure("group", font=("", 10, "bold"))

        box = ttk.LabelFrame(main, text="Журнал находок", padding=4)
        box.pack(fill="both", expand=True, pady=(10, 0))
        self.log = tk.Text(box, height=7, font=self.mono, wrap="none", state="disabled")
        scroll = ttk.Scrollbar(box, command=self.log.yview)
        self.log.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.log.pack(fill="both", expand=True)
        self.log.tag_configure("hit", foreground="#2e7d32", font=self.mono + ("bold",))
        self.log.tag_configure("best", foreground="#1565c0")
        self.log.tag_configure("warn", foreground="#c62828")

    # ---------- интерфейс: поиск ----------

    def _build_search(self, parent):
        row = ttk.Frame(parent)
        row.pack(fill="x")
        ttk.Label(row, text="Где искать:").pack(side="left")
        self.search_dir = tk.StringVar(value=str(DEFAULT_SAVE_DIR))
        ttk.Entry(row, textvariable=self.search_dir).pack(side="left", fill="x", expand=True, padx=6)
        ttk.Button(row, text="Обзор…", command=self.pick_search_dir).pack(side="left")
        ttk.Label(parent, foreground="gray",
                  text="Можно выбрать всю папку сохранений, один запуск или одну стаю — "
                       "поиск пройдёт по всем стаям внутри.").pack(anchor="w", pady=(2, 8))

        row = ttk.Frame(parent)
        row.pack(fill="x")
        ttk.Label(row, text="Что ищем:").pack(side="left")
        self.search_query = tk.StringVar()
        entry = ttk.Entry(row, textvariable=self.search_query, font=self.mono)
        entry.pack(side="left", fill="x", expand=True, padx=6)
        entry.bind("<Return>", lambda _e: self.start_search())
        ttk.Label(row, text="Показать до:").pack(side="left")
        self.search_max = tk.IntVar(value=1000)
        ttk.Spinbox(row, from_=1, to=100000, increment=100, width=7,
                    textvariable=self.search_max).pack(side="left", padx=(4, 8))
        self.search_btn = ttk.Button(row, text="Искать", command=self.start_search)
        self.search_btn.pack(side="left")
        self.cancel_btn = ttk.Button(row, text="Отмена", command=self.cancel_search, state="disabled")
        self.cancel_btn.pack(side="left", padx=(6, 0))

        self.search_bar = ttk.Progressbar(parent, maximum=1.0)
        self.search_bar.pack(fill="x", pady=(10, 4))
        self.search_summary = tk.StringVar(value="Введите слово или фразу и нажмите «Искать».")
        ttk.Label(parent, textvariable=self.search_summary, font=("", 11)).pack(anchor="w", pady=(0, 6))

        box = ttk.Frame(parent)
        box.pack(fill="both", expand=True)
        cols = ("group", "monkey", "pos", "context")
        self.results = ttk.Treeview(box, columns=cols, show="headings")
        for col, title, width, stretch in (("group", "Запуск / стая", 260, False),
                                           ("monkey", "Обезьяна", 90, False),
                                           ("pos", "Символ №", 130, False),
                                           ("context", "Контекст", 500, True)):
            self.results.heading(col, text=title)
            self.results.column(col, width=width, anchor="w", stretch=stretch)
        scroll = ttk.Scrollbar(box, command=self.results.yview)
        self.results.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.results.pack(fill="both", expand=True)
        self.results.tag_configure("best", foreground="#1565c0")

    # ---------- стаи ----------

    def refresh_groups(self):
        self.groups_tree.delete(*self.groups_tree.get_children())
        for i, g in enumerate(self.groups):
            self.groups_tree.insert("", "end", iid=str(i), text=g.name,
                                    values=(fmt_int(g.n_monkeys), g.keyboard_label(), g.speed_label()))

    def selected_group(self):
        sel = self.groups_tree.selection()
        return int(sel[0]) if sel else None

    def add_group(self):
        g = GroupDialog(self.root, self.mono).result
        if g:
            self.groups.append(g)
            self.refresh_groups()

    def edit_group(self):
        i = self.selected_group()
        if i is None or self.running:
            return
        g = GroupDialog(self.root, self.mono, self.groups[i]).result
        if g:
            self.groups[i] = g
            self.refresh_groups()

    def remove_group(self):
        i = self.selected_group()
        if i is not None and not self.running:
            del self.groups[i]
            self.refresh_groups()

    # ---------- сохранение ----------

    def pick_save_dir(self):
        d = filedialog.askdirectory(initialdir=self.save_dir.get(), mustexist=False)
        if d:
            self.save_dir.set(d)
            self.search_dir.set(d)

    def pick_search_dir(self):
        d = filedialog.askdirectory(initialdir=self.search_dir.get(), mustexist=True)
        if d:
            self.search_dir.set(d)

    # ---------- запуск и остановка ----------

    def phrases(self):
        return [line for line in self.words_text.get("1.0", "end").splitlines() if line.strip()]

    def words_for(self, group, phrases):
        words = []
        for line in phrases:
            w = normalize(line, group.alphabet)
            if w and w not in words and not missing_keys(w, group.alphabet):
                words.append(w)
        return words

    def start(self):
        if not self.groups:
            messagebox.showerror("Ошибка", "Добавьте хотя бы одну стаю.")
            return
        phrases = self.phrases()
        orphans = [p for p in phrases
                   if not any(self.words_for(g, [p]) for g in self.groups)]
        if orphans:
            messagebox.showwarning(
                "Никто не напечатает",
                "Этих фраз нет ни на одной клавиатуре, за ними никто не будет следить:\n\n"
                + "\n".join(orphans))

        save = None
        self.saved_used = None
        self.session_dir = None
        if self.save_on.get():
            try:
                limit = int(float(self.save_limit_gb.get()) * GB)
                file_limit = int(self.file_limit_mb.get()) * MB
            except (tk.TclError, ValueError):
                messagebox.showerror("Ошибка", "Лимиты сохранения — числа.")
                return
            self.session_dir = Path(self.save_dir.get()) / time.strftime("%Y-%m-%d_%H-%M-%S")
            try:
                self.session_dir.mkdir(parents=True, exist_ok=False)
            except OSError as e:
                messagebox.showerror("Ошибка", f"Не удалось создать папку:\n{e}")
                return
            self.saved_used = CTX.Value("q", 0)
            self.save_limit = limit
            save = {"limit": limit, "file_limit": file_limit, "used": self.saved_used}

        self.table.delete(*self.table.get_children())
        self._clear_log()
        cpu = os.cpu_count() or 1
        auto_workers = max(1, cpu // len(self.groups))
        total_monkeys = 0
        for gi, g in enumerate(self.groups):
            words = self.words_for(g, phrases)
            g.words = {w: WordState(w) for w in words}
            g.tails = {}
            g.speed = 0.0
            g.last_chars = 0
            self.table.insert("", "end", iid=f"g{gi}", text=g.name, open=True, tags=("group",))
            for w in words:
                self.table.insert(f"g{gi}", "end", iid=f"{gi}:{w}", text=w)
            gsave = None
            if save:
                gsave = dict(save, folder=str(self.session_dir / f"{gi + 1}_{slug(g.name)}"))
            g.engine.start(g.n_monkeys, g.alphabet, words, g.rate,
                           g.workers or auto_workers, gsave, g.name)
            total_monkeys += g.n_monkeys
            self._log(f"Стая «{g.name}»: {fmt_int(g.n_monkeys)} обезьян, "
                      f"{len(g.alphabet)} клавиш, следим за {len(words)} фразами\n")
        if self.session_dir:
            self._log(f"Всё напечатанное пишется в {self.session_dir}\n")
            self.search_dir.set(str(self.session_dir))

        self.running = True
        self.started_at = time.perf_counter()
        self.last_stats_time = self.started_at
        self.stat_vars["monkeys"].set(fmt_int(total_monkeys))
        self.stat_vars["saved"].set("выкл" if not save else "0 Б")
        self.start_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        for b in self.group_buttons:
            b.configure(state="disabled")

    def stop(self):
        if not self.running:
            return
        self.running = False
        self.elapsed_before = time.perf_counter() - self.started_at
        self.started_at = None
        for gi, g in enumerate(self.groups):
            self._handle_events(gi, g, g.engine.events(100000))
            g.engine.stop()
            self._handle_events(gi, g, g.engine.events(100000))
            g.speed = 0.0
        self.stat_vars["time"].set(fmt_clock(self.elapsed_before))
        total = sum(g.engine.total_chars() for g in self.groups)
        self.stat_vars["chars"].set(fmt_int(total))
        self.stat_vars["speed"].set("0")
        self._update_saved()
        self.start_btn.configure(state="normal")
        self.stop_btn.configure(state="disabled")
        for b in self.group_buttons:
            b.configure(state="normal")
        self._log(f"Остановлено. Всего напечатано {fmt_int(total)} символов\n")
        if self.session_dir:
            self._log(f"Сохранено {fmt_bytes(self.saved_used.value)} в {self.session_dir}\n")
        self.refresh_table()

    def elapsed(self):
        if self.started_at is None:
            return self.elapsed_before
        return time.perf_counter() - self.started_at

    def quick_add(self):
        line = self.quick.get()
        if not line.strip():
            return
        if not any(self.words_for(g, [line]) for g in self.groups):
            alphabet = "".join(dict.fromkeys("".join(g.alphabet for g in self.groups)))
            messagebox.showwarning("Нет таких клавиш",
                                   f"«{line.strip()}» не напечатает ни одна стая: нет клавиш "
                                   f"{keys_text(missing_keys(line.strip().lower(), alphabet))}.")
            return
        self.quick.set("")
        if line.strip() not in (p.strip() for p in self.phrases()):
            tail = "" if self.words_text.get("end-2c") == "\n" else "\n"
            self.words_text.insert("end", tail + line.strip())
        if not self.running:
            return
        for gi, g in enumerate(self.groups):
            for w in self.words_for(g, [line]):
                if w not in g.words:
                    g.words[w] = WordState(w)
                    self.table.insert(f"g{gi}", "end", iid=f"{gi}:{w}", text=w)
                    g.engine.add_word(w)
                    self._log(f"[{fmt_clock(self.elapsed())}] {g.name}: следим за «{w}»\n")

    def on_close(self):
        self.cancel_search()
        for g in self.groups:
            g.engine.stop()
        self.root.destroy()

    # ---------- обновление ----------

    def poll(self):
        if self.running:
            full = False
            for gi, g in enumerate(self.groups):
                full |= self._handle_events(gi, g, g.engine.events())
            self._draw_typewriters()
            if full:
                self._log(f"[{fmt_clock(self.elapsed())}] Лимит сохранения "
                          f"{fmt_bytes(self.save_limit)} заполнен — дальше не записываем\n", "warn")
                if self.stop_on_full.get():
                    self.stop()
        self.root.after(POLL_MS, self.poll)

    def _handle_events(self, gi, g, events):
        """Возвращает True, если пришло первое сообщение о заполненном лимите."""
        full = False
        for ev in events:
            kind = ev[0]
            if kind == "tails":
                g.tails.update(ev[1])
            elif kind == "counts":
                for w, k in ev[1].items():
                    if w in g.words:
                        g.words[w].found += k
            elif kind == "found":
                _, w, monkey, pos, _t, ctx, off = ev
                st = g.words.get(w)
                if st is None or st.first is not None:
                    continue
                st.first = (self.elapsed(), monkey)
                self._log_hit(f"[{fmt_clock(self.elapsed())}] {g.name}, обезьяна №{monkey + 1} "
                              f"напечатала «{w}» (её символ №{fmt_int(pos + 1)}):  ",
                              ctx, off, len(w), "hit")
            elif kind == "best":
                _, w, k, monkey, ctx, off = ev
                st = g.words.get(w)
                if st is None or k <= st.best:
                    continue
                st.best = k
                if 3 <= k < len(w):  # короткие префиксы не засоряют журнал
                    self._log_hit(f"[{fmt_clock(self.elapsed())}] Почти! {g.name}, обезьяна "
                                  f"№{monkey + 1}: {k}/{len(w)} букв «{w}»:  ",
                                  ctx, off, k, "best")
            elif kind == "save_full":
                if not getattr(self, "_full_reported", False):
                    self._full_reported = full = True
        return full

    def _draw_typewriters(self):
        tw = self.typewriters
        tw.configure(state="normal")
        tw.delete("1.0", "end")
        per_group = min(DISPLAY_MONKEYS, max(1, TYPEWRITER_ROWS // len(self.groups)))
        first = True
        for g in self.groups:
            for m in range(min(per_group, g.n_monkeys)):
                if not first:
                    tw.insert("end", "\n")
                first = False
                text = g.tails.get(m, "")
                tw.insert("end", f"{g.name[:10]:<10} №{m + 1:<4}│ ", "name")
                start = tw.index("end-1c")
                tw.insert("end", text)
                tw.insert("end", "▌", "caret")
                for w in g.words:
                    p = text.find(w)
                    while p != -1:
                        tw.tag_add("hit", f"{start}+{p}c", f"{start}+{p + len(w)}c")
                        p = text.find(w, p + 1)
        tw.configure(state="disabled")

    def update_stats(self):
        if self.running:
            now = time.perf_counter()
            dt = now - self.last_stats_time
            self.last_stats_time = now
            total = speed = 0
            for g in self.groups:
                chars = g.engine.total_chars()
                if dt > 0:
                    inst = (chars - g.last_chars) / dt
                    g.speed = inst if g.speed == 0 else g.speed * 0.7 + inst * 0.3
                g.last_chars = chars
                total += chars
                speed += g.speed
            self.stat_vars["time"].set(fmt_clock(self.elapsed()))
            self.stat_vars["chars"].set(fmt_int(total))
            self.stat_vars["speed"].set(fmt_int(speed))
            self._update_saved()
            self.refresh_table()
            all_words = [st for g in self.groups for st in g.words.values()]
            if self.stop_when_done.get() and all_words and all(st.found for st in all_words):
                self._log("Всё найдено!\n")
                self.stop()
        self.root.after(STATS_MS, self.update_stats)

    def _update_saved(self):
        if self.saved_used is None:
            return
        text = fmt_bytes(self.saved_used.value)
        if self.save_limit:
            text += f" / {fmt_bytes(self.save_limit)}"
        self.stat_vars["saved"].set(text)

    def refresh_table(self):
        for gi, g in enumerate(self.groups):
            n = len(g.alphabet)
            found_total = 0
            for w, st in g.words.items():
                L = len(w)
                best = L if st.found else st.best
                found_total += st.found
                attempt = w[:best] + "·" * (L - best)
                first = (f"{fmt_clock(st.first[0])}, обезьяна №{st.first[1] + 1}"
                         if st.first else "—")
                # в среднем нужно около n^L символов, чтобы фраза встретилась
                if g.speed > 0:
                    expect = fmt_duration(math.exp(L * math.log(n) - math.log(g.speed)))
                else:
                    expect = f"≈ {n}^{L} символов"
                self.table.item(f"{gi}:{w}", values=(fmt_int(st.found), attempt,
                                                     f"{100 * best // L}%", first, expect),
                                tags=("done",) if st.found else ())
            self.table.item(f"g{gi}", values=(fmt_int(found_total), "", "",
                                              f"{fmt_int(g.engine.total_chars())} симв.",
                                              f"{fmt_int(g.speed)} симв/с"))

    # ---------- журнал ----------

    def _log(self, text, tag=None):
        self.log.configure(state="normal")
        self.log.insert("end", text, tag)
        excess = int(self.log.index("end-1c").split(".")[0]) - MAX_LOG_LINES
        if excess > 0:
            self.log.delete("1.0", f"{excess + 1}.0")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _log_hit(self, prefix, ctx, off, length, tag):
        self._log(prefix + "…" + ctx[:off])
        self._log(ctx[off:off + length], tag)
        self._log(ctx[off + length:] + "…\n")

    def _clear_log(self):
        self._full_reported = False
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")

    # ---------- поиск в сохранённом ----------

    def start_search(self):
        if self.search:
            return
        query = " ".join(self.search_query.get().split())
        folder = self.search_dir.get()
        if not query:
            return
        if not Path(folder).is_dir():
            messagebox.showerror("Ошибка", f"Папки нет:\n{folder}")
            return
        try:
            max_hits = max(1, int(self.search_max.get()))
        except (tk.TclError, ValueError):
            max_hits = 1000
        self.results.delete(*self.results.get_children())
        self.search = Search(folder, query, max_hits)
        if not self.search.tasks:
            self.search = None
            self.search_summary.set("В этой папке нет сохранённого текста обезьян.")
            return
        self.search_started = time.perf_counter()
        self.search_btn.configure(state="disabled")
        self.cancel_btn.configure(state="normal")
        self.search_summary.set(f"Ищем «{query}» в {fmt_bytes(self.search.total_bytes)}…")
        self.root.after(SEARCH_POLL_MS, self.poll_search)

    def cancel_search(self):
        if self.search:
            self.search.cancel()

    def poll_search(self):
        s = self.search
        if s is None:
            return
        self.search_bar["value"] = s.fraction()
        if not s.done():
            self.root.after(SEARCH_POLL_MS, self.poll_search)
            return
        r = s.result()
        self.search = None
        self.search_btn.configure(state="normal")
        self.cancel_btn.configure(state="disabled")
        took = time.perf_counter() - self.search_started
        for label, monkey, pos, ctx, off, length in r["hits"]:
            self.results.insert("", "end", values=(
                label, f"№{monkey}", fmt_int(pos),
                f"…{ctx[:off]}【{ctx[off:off + length]}】{ctx[off + length:]}…"))
        head = "Поиск прерван. " if r["cancelled"] else ""
        where = f"{fmt_bytes(r['bytes'])} за {took:.1f} с"
        if r["count"]:
            shown = len(r["hits"])
            more = f" (показаны первые {shown})" if shown < r["count"] else ""
            self.search_summary.set(f"{head}«{s.query}» найдено {fmt_int(r['count'])} раз "
                                    f"в {where}{more}.")
        else:
            text = f"{head}«{s.query}» не найдено в {where}."
            if r["best_hit"]:
                label, monkey, pos, ctx, off, length = r["best_hit"]
                text += f" Ближе всех: {r['best']}/{len(s.query)} символов, показано ниже."
                self.results.insert("", "end", tags=("best",), values=(
                    label, f"№{monkey}", fmt_int(pos),
                    f"…{ctx[:off]}【{ctx[off:off + length]}】{ctx[off + length:]}…"))
            self.search_summary.set(text)


def main():
    root = tk.Tk()
    try:
        ttk.Style().theme_use("clam")
    except tk.TclError:
        pass
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
