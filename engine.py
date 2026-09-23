"""Движок: процессы с «обезьянами», которые печатают случайный текст, и быстрый поиск слов.

Каждая обезьяна — независимый поток случайных символов. Обезьяны распределены
по рабочим процессам по кругу (обезьяна m живёт в процессе m % W).

Для скорости текст внутри процессов хранится не строками, а байтами-индексами
алфавита (0..N-1): случайные байты из os.urandom переводятся в индексы через
bytes.translate, а искомые слова кодируются так же и ищутся через bytes.find.
Всё это работает на скорости C.

Если включено сохранение, каждый процесс пишет свои файлы w<процесс>_<часть>.txt.
Строка файла: «номер обезьяны<TAB>номер первого символа<TAB>текст». Все куски
одной обезьяны лежат в файлах одного процесса по порядку.
"""
import codecs
import json
import multiprocessing as mp
import os
import queue
import time
from pathlib import Path

CTX = mp.get_context("spawn")

CHUNK = 2048            # символов на обезьяну за такт в режиме «максимум»
TICK = 0.05             # такт в медленном режиме, сек
DISPLAY_MONKEYS = 12    # сколько обезьян показывать «вживую»
DISPLAY_TAIL = 72       # сколько последних символов обезьяны показывать
DISPLAY_EVERY = 0.1     # как часто слать хвосты текста в GUI, сек
MAX_DETAILS = 30        # подробных находок на слово от одного процесса (остальное — счётчиком)
CONTEXT = 18            # символов контекста вокруг находки
SAVE_FLUSH = 2048       # копить столько символов обезьяны перед записью строки в файл
FORBIDDEN = "\t\n\r"    # эти символы не могут быть клавишами — они размечают файлы


def make_tables(n):
    """Таблицы для перевода случайных байтов в индексы 0..n-1 без смещения.

    Байты >= limit (limit кратно n) выбрасываются, остальные берутся по модулю n,
    поэтому каждый символ алфавита выпадает с одинаковой вероятностью.
    """
    limit = 256 - 256 % n
    table = bytes(i % n if i < limit else 0 for i in range(256))
    delete = bytes(range(limit, 256))
    return table, delete, limit


def encode(word, alphabet):
    return bytes(alphabet.index(c) for c in word)


def make_decoder(alphabet):
    return alphabet + "￾" * (256 - len(alphabet))


def decode(data, dec):
    return codecs.charmap_decode(data, "strict", dec)[0]


class _Target:
    __slots__ = ("word", "code", "length", "best", "details")

    def __init__(self, word, alphabet):
        self.word = word
        self.code = encode(word, alphabet)
        self.length = len(self.code)
        self.best = 0       # самый длинный напечатанный префикс (в этом процессе)
        self.details = 0    # сколько подробных находок уже отправлено


class _Saver:
    """Пишет текст одного процесса в файлы с учётом общего лимита на все процессы."""

    def __init__(self, folder, wid, file_limit, limit, used):
        self.folder = Path(folder)
        self.wid = wid
        self.file_limit = file_limit
        self.limit = limit
        self.used = used
        self.part = 0
        self.file = None
        self.size = 0
        self.full = False

    def _rotate(self):
        if self.file:
            self.file.close()
        self.part += 1
        name = f"w{self.wid:02d}_{self.part:04d}.txt"
        self.file = open(self.folder / name, "wb", buffering=1 << 20)
        self.size = 0

    def write(self, lines):
        """Записывает сколько влезает. Возвращает True, если лимит только что заполнился."""
        if self.full or not lines:
            return False
        take = lines
        if self.limit:
            total = sum(map(len, lines))
            with self.used.get_lock():
                room = self.limit - self.used.value
                if total > room:
                    take, s = [], 0
                    for line in lines:
                        if s + len(line) > room:
                            break
                        take.append(line)
                        s += len(line)
                    total = s
                    self.full = True
                self.used.value += total
        else:
            with self.used.get_lock():
                self.used.value += sum(map(len, lines))
        for line in take:
            if self.file is None or (self.file_limit and self.size
                                     and self.size + len(line) > self.file_limit):
                self._rotate()
            self.file.write(line)
            self.size += len(line)
        return self.full

    def close(self):
        if self.file:
            self.file.close()
            self.file = None


def _random_block(need, table, delete, limit):
    """Ровно need случайных индексов алфавита."""
    ratio = 256 / limit
    data = os.urandom(int(need * ratio) + 64).translate(table, delete)
    while len(data) < need:
        data += os.urandom(int((need - len(data)) * ratio) + 64).translate(table, delete)
    return data[:need]


def _worker(wid, n_workers, n_monkeys, alphabet, words, rate, counters, stop, ctrl, out, save):
    table, delete, limit = make_tables(len(alphabet))
    dec = make_decoder(alphabet)
    targets = [_Target(w, alphabet) for w in words]
    maxlen = max((t.length for t in targets), default=1)

    monkeys = list(range(wid, n_monkeys, n_workers))
    tails = [b""] * len(monkeys)      # хвост для поиска через границу кусков
    typed = [0] * len(monkeys)        # сколько символов напечатала обезьяна
    shown = [i for i, m in enumerate(monkeys) if m < DISPLAY_MONKEYS]
    disp = {i: b"" for i in shown}

    saver = None
    if save:
        saver = _Saver(save["folder"], wid, save["file_limit"], save["limit"], save["used"])
        pend = [bytearray() for _ in monkeys]   # ещё не записанный текст обезьяны
        pend_off = [0] * len(monkeys)           # номер его первого символа

    def line(i):
        text = decode(bytes(pend[i]), dec)
        return f"{monkeys[i] + 1}\t{pend_off[i] + 1}\t{text}\n".encode("utf-8")

    start = time.perf_counter()
    last = start
    last_display = 0.0
    budget = 0.0
    total = 0
    found_counts = {}   # копим и отправляем пачкой, чтобы не завалить очередь

    while not stop.is_set():
        # команды из GUI: новое слово или новая скорость
        try:
            while True:
                cmd, arg = ctrl.get_nowait()
                if cmd == "add" and all(t.word != arg for t in targets):
                    targets.append(_Target(arg, alphabet))
                    maxlen = max(maxlen, len(arg))
                elif cmd == "rate":
                    rate = arg
                    budget = 0.0
        except queue.Empty:
            pass

        now = time.perf_counter()
        if rate > 0:
            budget += (now - last) * rate
            last = now
            per = min(int(budget), CHUNK)
            if per == 0:
                time.sleep(TICK)
                continue
            budget -= per
        else:
            last = now
            per = CHUNK

        data = _random_block(per * len(monkeys), table, delete, limit)
        elapsed = now - start
        lines = []

        for i, m in enumerate(monkeys):
            chunk = data[i * per:(i + 1) * per]
            tail = tails[i]
            buf = tail + chunk
            tl = len(tail)
            base = typed[i] - tl  # номер символа buf[0] в потоке обезьяны

            for t in targets:
                code, L = t.code, t.length
                # полные совпадения, заканчивающиеся в новом куске
                p = buf.find(code, max(0, tl - L + 1))
                while p != -1:
                    found_counts[t.word] = found_counts.get(t.word, 0) + 1
                    if t.details < MAX_DETAILS:
                        t.details += 1
                        a, b = max(0, p - CONTEXT), p + L + CONTEXT
                        out.put(("found", t.word, m, base + p, elapsed,
                                 decode(buf[a:b], dec), p - a))
                    p = buf.find(code, p + 1)

                # лучшая попытка: самый длинный префикс слова
                if t.best < L and code[:t.best + 1] in buf:
                    k = t.best + 1
                    while k < L and code[:k + 1] in buf:
                        k += 1
                    t.best = k
                    p = buf.find(code[:k])
                    a, b = max(0, p - CONTEXT), p + k + CONTEXT
                    out.put(("best", t.word, k, m, decode(buf[a:b], dec), p - a))

            tails[i] = buf[-(maxlen - 1):] if maxlen > 1 else b""
            if i in disp:
                disp[i] = (disp[i] + chunk)[-DISPLAY_TAIL:]
            if saver:
                pend[i] += chunk
                if len(pend[i]) >= SAVE_FLUSH:
                    lines.append(line(i))
                    pend[i].clear()
                    pend_off[i] = typed[i] + per
            typed[i] += per

        total += per * len(monkeys)
        counters[wid] = total
        if saver and saver.write(lines):
            saver.close()
            saver = None
            out.put(("save_full",))
        if now - last_display >= DISPLAY_EVERY:
            last_display = now
            if found_counts:
                out.put(("counts", found_counts))
                found_counts = {}
            if shown:
                out.put(("tails", {monkeys[i]: decode(disp[i], dec) for i in shown}))

    if found_counts:
        out.put(("counts", found_counts))

    if saver:
        saver.write([line(i) for i in range(len(monkeys)) if pend[i]])
        saver.close()


class MonkeyEngine:
    def __init__(self):
        self.procs = []
        self.ctrls = []
        self.out = None
        self.stop_event = None
        self.counters = None
        self.alphabet = ""
        self.n_monkeys = 0
        self.saving = False
        self._pending = []

    @property
    def running(self):
        return bool(self.procs)

    def start(self, n_monkeys, alphabet, words, rate=0, n_workers=None, save=None, name=""):
        """rate — символов в секунду на одну обезьяну, 0 = максимально быстро.

        save — None или словарь: folder (папка стаи), limit (общий лимит, байт, 0 = нет),
        file_limit (размер одного файла, байт, 0 = нет), used (общий CTX.Value('q')).
        """
        if self.running:
            self.stop()
        self._pending = []
        if not 2 <= len(alphabet) <= 256:
            raise ValueError("В алфавите должно быть от 2 до 256 символов")
        if any(c in alphabet for c in FORBIDDEN):
            raise ValueError("Табуляция и перевод строки не могут быть клавишами")
        n_workers = max(1, min(n_workers or os.cpu_count() or 1, n_monkeys))
        self.alphabet = alphabet
        self.n_monkeys = n_monkeys
        self.saving = bool(save)
        if save:
            folder = Path(save["folder"])
            folder.mkdir(parents=True, exist_ok=True)
            meta = {
                "name": name,
                "alphabet": alphabet,
                "monkeys": n_monkeys,
                "workers": n_workers,
                "rate": rate,
                "words": list(words),
                "started": time.strftime("%Y-%m-%d %H:%M:%S"),
                "format": "w<процесс>_<часть>.txt, строка: номер обезьяны<TAB>"
                          "номер первого символа<TAB>текст",
            }
            (folder / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2),
                                              encoding="utf-8")
        self.out = CTX.Queue()
        self.stop_event = CTX.Event()
        self.counters = CTX.Array("Q", n_workers, lock=False)
        self.ctrls = [CTX.Queue() for _ in range(n_workers)]
        self.procs = [
            CTX.Process(
                target=_worker,
                args=(w, n_workers, n_monkeys, alphabet, list(words), rate,
                      self.counters, self.stop_event, self.ctrls[w], self.out, save),
                daemon=True,
            )
            for w in range(n_workers)
        ]
        for p in self.procs:
            p.start()

    def stop(self):
        if not self.running:
            return
        self.stop_event.set()
        # дочитываем очередь, пока процессы завершаются: иначе они не смогут выйти,
        # а последние находки потеряются
        deadline = time.monotonic() + (15 if self.saving else 3)
        while any(p.is_alive() for p in self.procs) and time.monotonic() < deadline:
            self._pending += self._drain(100000)
            time.sleep(0.01)
        for p in self.procs:
            if p.is_alive():
                p.terminate()
            p.join()
        self._pending += self._drain(100000)
        self.procs = []
        self.ctrls = []

    def add_word(self, word):
        for q in self.ctrls:
            q.put(("add", word))

    def set_rate(self, rate):
        for q in self.ctrls:
            q.put(("rate", rate))

    def total_chars(self):
        return sum(self.counters) if self.counters is not None else 0

    def events(self, limit=5000):
        result, self._pending = self._pending, []
        return result + self._drain(limit)

    def _drain(self, limit):
        result = []
        if self.out is None:
            return result
        try:
            for _ in range(limit):
                result.append(self.out.get_nowait())
        except queue.Empty:
            pass
        return result
