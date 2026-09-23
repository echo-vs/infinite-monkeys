<p align="center">
  <img src="assets/logo.png" alt="A gorilla with a Gentoo logo typing on a ThinkPad" width="320">
</p>

# Infinite Monkeys 🐒⌨️

**English** | [Русский](README.ru.md)

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE) ![Python 3](https://img.shields.io/badge/Python-3-blue.svg) ![No dependencies](https://img.shields.io/badge/dependencies-none-brightgreen.svg)

A desktop simulator of the [infinite monkey theorem](https://en.wikipedia.org/wiki/Infinite_monkey_theorem): thousands of monkeys hammer random keys, and the program watches in real time for the words and phrases you are waiting for.

Pure Python standard library, no third-party packages. Despite being Python, it is fast: all the heavy lifting (random generation, mapping bytes to keys, substring search) runs inside C code, and every CPU core gets its own process.

| Machine | 1000 monkeys, turbo |
|---|---|
| AMD Ryzen 5 7500F (6C/12T), Gentoo | ~2.5 billion chars/sec |
| 8-core test VM | ~480 million chars/sec |

## Features

- **Monkey packs.** Run several packs at once, each with its own keyboard, size and speed. For example, one pack types in Russian while another types in English.
- **Truly random, unbiased typing.** Randomness comes from `os.urandom`, and every key has exactly the same probability (rejection sampling, no modulo bias).
- **Live watch list.** Enter words or phrases, one per line. Each pack only watches for phrases it can actually type. You can add phrases on the fly while the monkeys work.
- **Records.** For every phrase the program shows the best attempt so far (e.g. `shakespe···`), who typed it first, how many times it was found, and the expected waiting time at the current speed.
- **Matches across chunk boundaries** are found too, including phrases split between two chunks of text.
- **Live view** of monkeys typing, with matches highlighted.
- **Speed control**: turbo (as fast as the CPU allows) or 1–60 keystrokes per second per monkey, to watch them type.
- **Saving everything typed** to a folder, with a total size limit (e.g. 2 GB, after which writing stops) and a per-file size limit (files are split into parts).
- **Search in saved text**: find any word or phrase in the saved output, in parallel on all cores. If there is no match, it shows the closest attempt.

## Installation

You need **Python 3** with **Tkinter** (the standard Python GUI library). Nothing else is required: no `pip install`.

Developed and tested with Python 3.14 on Linux (Fedora, Gentoo).

### Windows

1. Download Python from [python.org](https://www.python.org/downloads/windows/).
2. In the installer, make sure these are checked:
   - **"Add python.exe to PATH"**
   - **"tcl/tk and IDLE"** (under *Customize installation*; it is on by default). This is Tkinter.
3. Download the project (`Code → Download ZIP` on GitHub and unpack it, or use `git clone`).
4. Open the project folder, then type `cmd` in the address bar and press Enter.
5. Run:
   ```bat
   py monkeys.py
   ```

> The Python from the Microsoft Store also includes Tkinter.

### Linux

Install Python and Tkinter with your distribution's package manager:

| Distribution | Command |
|---|---|
| Debian / Ubuntu / Mint / Pop!_OS | `sudo apt install python3 python3-tk` |
| Fedora / RHEL / CentOS Stream | `sudo dnf install python3 python3-tkinter` |
| Arch / Manjaro / EndeavourOS | `sudo pacman -S python tk` |
| openSUSE | `sudo zypper install python3 python3-tk` |
| Void Linux | `sudo xbps-install python3 python3-tkinter` |
| Alpine | `sudo apk add python3 py3-tkinter` |
| Gentoo | see below |

#### Gentoo

On Gentoo, Tkinter is a USE flag of `dev-lang/python`:

```sh
# enable the tk USE flag for Python
echo "dev-lang/python tk" | sudo tee -a /etc/portage/package.use/python

# rebuild Python with the new flag
sudo emerge --ask --oneshot --changed-use dev-lang/python
```

If `/etc/portage/package.use` is a file rather than a directory on your system, append the line to that file instead.

#### Check that Tkinter works

```sh
python3 -m tkinter
```

A small window should appear. If you get `ModuleNotFoundError: No module named 'tkinter'`, the Tkinter package is not installed yet.

#### Run

```sh
git clone https://github.com/echo-vs/infinite-monkeys.git
cd infinite-monkeys
python3 monkeys.py
```

## Usage

### The "Monkeys" tab

1. **Packs.** Two packs exist by default, "Русские" (Russian) and "Англичане" (English), with 1000 monkeys each. Use *Добавить* / *Изменить* / *Удалить* (Add / Edit / Delete) or double-click a pack to set its:
   - number of monkeys;
   - number of processes (0 = auto, CPU threads split between packs);
   - keyboard: a preset (Russian, English, with punctuation, digits…) or your own set of characters, plus an optional space key;
   - speed: turbo, or 1–60 keystrokes per second per monkey.
2. **What to look for.** One word or phrase per line. The quick-add field adds phrases while the monkeys are running.
3. **Saving** (optional): folder, total limit in GB (0 = unlimited), size of one file in MB, and whether to stop the monkeys when the limit is reached.
4. Press **▶ Запустить обезьян (Start)** or **F5**. **Esc** stops them.

The watch table shows, for each phrase: times found, best attempt, progress, first finder and expected waiting time. The log records every first find and every new record ("Почти!", "Almost!").

### The "Search in saved" tab

Choose a folder (the whole save folder, one session, or one pack), enter a word or phrase and press Enter. Results show the pack, monkey number, character position and context, with the match marked `【like this】`.

### Save format

```
сохранения/
└── 2026-09-23_17-38-06/          one folder per run
    ├── 1_Русские/                one folder per pack
    │   ├── meta.json             keyboard, number of monkeys, phrases, start time
    │   ├── w00_0001.txt          process 0, part 1
    │   ├── w00_0002.txt          process 0, part 2
    │   └── w01_0001.txt …
    └── 2_Англичане/ …
```

Each line of a `.txt` file is:

```
<monkey number><TAB><number of the first character><TAB><text>
```

All text typed by one monkey lives, in order, in the files of a single process, so a monkey's full output can be reassembled.

## How long do they need?

With `N` keys, a phrase of length `L` appears on average once every about `N^L` characters. Each extra character multiplies the wait by `N`.

At ~2.5 billion chars/sec, on the English keyboard (26 letters + space = 27 keys):

| Phrase | Length | Average wait |
|---|---|---|
| monkey | 6 | < 1 second |
| shakespe | 8 | ~2 minutes |
| shakespear | 10 | ~1 day |
| shakespeare | 11 | ~26 days |
| to be or not to be | 18 | ~740 million years |

The monkeys have no memory: the chance is the same every second, no matter how long they have already been typing.

## How it works

- `engine.py` is the monkeys. They are spread across processes (`multiprocessing`, `spawn`). Each process takes random bytes from `os.urandom` and maps them to key indices with a single `bytes.translate` call. Bytes that would bias the distribution are dropped. Text stays as key-index bytes, and phrases are encoded the same way and searched with `bytes.find`. A short tail of each monkey's previous chunk is kept, so matches spanning two chunks are not missed. Match counts are batched and sent to the GUI every 0.1 s.
- `search.py` searches saved files. It runs one task per (pack, process) in a process pool and glues each monkey's chunks back together.
- `monkeys.py` is the Tkinter GUI.

## Project structure

```
monkeys.py    GUI, entry point
engine.py     monkey processes, unbiased random typing, live phrase search, saving
search.py     parallel search in saved output
```

## License

[MIT](LICENSE): free and open source. You can use, copy, modify and distribute this code, including in commercial projects. The only requirement is to keep the license text. Pull requests and forks are welcome!
