"""Поиск слов и фраз в сохранённом тексте обезьян.

Ищет во всех папках стай (в которых есть meta.json) внутри выбранной папки.
Файлы одного рабочего процесса обрабатываются по порядку, а разные процессы
и стаи — параллельно. Куски одной обезьяны склеиваются, поэтому находятся
и фразы, разорванные между строками или файлами.
"""
import json
import os
from pathlib import Path

from engine import CONTEXT, CTX

PROGRESS_STEP = 1 << 20

_progress = None
_cancel = None


def _init(progress, cancel):
    global _progress, _cancel
    _progress, _cancel = progress, cancel


def find_groups(folder):
    """[(папка стаи, meta)] внутри folder, включая её саму."""
    groups = []
    for meta_path in sorted(Path(folder).rglob("meta.json")):
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        groups.append((meta_path.parent, meta))
    return groups


def plan(folder):
    """Разбивает поиск на задачи: одна задача — файлы одного процесса одной стаи."""
    root = Path(folder)
    tasks, total = [], 0
    for gdir, meta in find_groups(root):
        rel = gdir.relative_to(root)
        label = str(rel) if str(rel) != "." else (meta.get("name") or gdir.name)
        by_worker = {}
        for f in sorted(gdir.glob("w*_*.txt")):
            by_worker.setdefault(f.name.split("_")[0], []).append(str(f))
            total += f.stat().st_size
        for paths in by_worker.values():
            tasks.append((label, meta.get("alphabet", ""), paths))
    return tasks, total


def prepare_query(query, alphabet):
    """Как и при слежке: если на клавиатуре нет заглавных, ищем строчными."""
    if alphabet and not any(c.isupper() for c in alphabet):
        return query.lower()
    return query


def _hit(label, monkey, pos, buf, p, length):
    a = max(0, p - CONTEXT)
    return (label, monkey, pos, buf[a:p + length + CONTEXT], p - a, length)


def _search_task(label, alphabet, paths, query, max_hits):
    q = prepare_query(query, alphabet)
    L = len(q)
    keep = L - 1
    tails = {}          # обезьяна -> (хвост, номер его первого символа)
    count = 0
    hits = []
    best = 0
    best_hit = None
    pending = 0
    cancelled = False

    for path in paths:
        with open(path, "rb") as f:
            for raw in f:
                pending += len(raw)
                if pending >= PROGRESS_STEP:
                    with _progress.get_lock():
                        _progress.value += pending
                    pending = 0
                    if _cancel.is_set():
                        cancelled = True
                        break
                try:
                    m, off, text = raw.decode("utf-8").rstrip("\n").split("\t", 2)
                    m, off = int(m), int(off)
                except ValueError:
                    continue
                tail, tstart = tails.get(m, ("", off))
                if tstart + len(tail) != off:  # пропуск в тексте — не склеиваем
                    tail, tstart = "", off
                buf = tail + text
                tl = len(tail)

                p = buf.find(q, max(0, tl - L + 1))
                while p != -1:
                    count += 1
                    if len(hits) < max_hits:
                        hits.append(_hit(label, m, tstart + p, buf, p, L))
                    p = buf.find(q, p + 1)

                if best < L and q[:best + 1] in buf:
                    k = best + 1
                    while k < L and q[:k + 1] in buf:
                        k += 1
                    best = k
                    p = buf.find(q[:k])
                    best_hit = _hit(label, m, tstart + p, buf, p, k)

                if keep > 0:
                    k2 = min(keep, len(buf))
                    tails[m] = (buf[len(buf) - k2:], tstart + len(buf) - k2)
                else:
                    tails[m] = ("", off + len(text))
        if cancelled:
            break

    with _progress.get_lock():
        _progress.value += pending
    return {"count": count, "hits": hits, "best": best, "best_hit": best_hit}


class Search:
    """Фоновый поиск. Опрашивай done() и fraction(), потом забери result()."""

    def __init__(self, folder, query, max_hits=1000, workers=None):
        self.query = query
        self.max_hits = max_hits
        self.tasks, self.total_bytes = plan(folder)
        self.progress = CTX.Value("q", 0)
        self.cancel_event = CTX.Event()
        self.pool = None
        self.async_results = []
        if not self.tasks:
            return
        n = max(1, min(workers or os.cpu_count() or 1, len(self.tasks)))
        self.pool = CTX.Pool(n, initializer=_init, initargs=(self.progress, self.cancel_event))
        self.async_results = [
            self.pool.apply_async(_search_task, (label, alphabet, paths, query, max_hits))
            for label, alphabet, paths in self.tasks
        ]
        self.pool.close()

    @property
    def groups(self):
        return len({t[0] for t in self.tasks})

    def done(self):
        return all(r.ready() for r in self.async_results)

    def fraction(self):
        if not self.total_bytes:
            return 1.0
        return min(1.0, self.progress.value / self.total_bytes)

    def result(self):
        count, hits, best, best_hit = 0, [], 0, None
        for r in self.async_results:
            part = r.get()
            count += part["count"]
            hits.extend(part["hits"])
            if part["best"] > best:
                best, best_hit = part["best"], part["best_hit"]
        if self.pool:
            self.pool.join()
        hits.sort(key=lambda h: (h[0], h[1], h[2]))
        return {"count": count, "hits": hits[:self.max_hits],
                "best": best, "best_hit": best_hit, "bytes": self.progress.value,
                "cancelled": self.cancel_event.is_set()}

    def cancel(self):
        self.cancel_event.set()
