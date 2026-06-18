#!/usr/bin/env python3
"""
compare_gui.py -- double-click launcher for the comparison oracle.

A thin tkinter wrapper around compareengine. It holds NO comparison logic of its
own: it collects two folders (GOLD = hand-merged known-answers, CANDIDATE =
CUupdate.exe output), runs compareengine.compare_dirs in a worker thread, and
shows the report that compareengine.build_report produces -- byte-identical to
what run_compare.py prints. A Save button writes that same text to a file.

Runs on any machine with Python (tkinter ships with CPython). Freeze to a
standalone .exe with compare.spec (see compare/BUILD.md) so it runs on a server
with no Python installed -- shipped by pasting the .exe across, same as the main
tool.
"""
import os
import queue
import threading
import traceback

import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext

import compareengine as ce

# Tool version (single source of truth: compare/__init__.py). Imported with a
# fallback so a flat frozen build (modules at top level, no package) still runs.
try:
    from compare import __version__ as _VERSION
except Exception:
    try:
        from __init__ import __version__ as _VERSION
    except Exception:
        _VERSION = "1.0"


class CompareGUI:
    def __init__(self, root):
        self.root = root
        self.q = queue.Queue()
        self.last_report = ""
        root.title(f"CU Compare {_VERSION} -- output oracle")
        root.geometry("900x640")

        pad = dict(padx=8, pady=4)

        # --- folder pickers ---
        top = tk.Frame(root)
        top.pack(fill="x", **pad)

        self.gold_var = tk.StringVar()
        self.cand_var = tk.StringVar()

        self._folder_row(top, 0, "Gold folder (hand-merged):", self.gold_var)
        self._folder_row(top, 1, "Candidate folder (tool output):", self.cand_var)
        top.columnconfigure(1, weight=1)

        # --- action buttons ---
        btns = tk.Frame(root)
        btns.pack(fill="x", **pad)
        self.run_btn = tk.Button(btns, text="Run comparison",
                                 command=self.on_run, width=18)
        self.run_btn.pack(side="left", padx=4)
        self.save_btn = tk.Button(btns, text="Save report...",
                                  command=self.on_save, state="disabled", width=14)
        self.save_btn.pack(side="left", padx=4)

        # --- status line ---
        self.status = tk.StringVar(value="Pick a gold folder and a candidate "
                                          "folder, then Run.")
        tk.Label(root, textvariable=self.status, anchor="w",
                 fg="#555").pack(fill="x", padx=8)

        # --- results pane ---
        self.out = scrolledtext.ScrolledText(root, wrap="none",
                                             font=("Courier New", 10))
        self.out.pack(fill="both", expand=True, padx=8, pady=6)

        self.root.after(100, self._drain_queue)

    def _folder_row(self, parent, r, label, var):
        tk.Label(parent, text=label).grid(row=r, column=0, sticky="w", pady=2)
        tk.Entry(parent, textvariable=var).grid(row=r, column=1,
                                                sticky="ew", padx=6)
        tk.Button(parent, text="Browse...",
                  command=lambda: self._pick(var)).grid(row=r, column=2)

    def _pick(self, var):
        d = filedialog.askdirectory()
        if d:
            var.set(d)

    # --- run (threaded so the UI stays responsive on large customers) ---
    def on_run(self):
        gold = self.gold_var.get().strip()
        cand = self.cand_var.get().strip()
        if not os.path.isdir(gold):
            messagebox.showerror("CU Compare", "Gold folder is not a directory.")
            return
        if not os.path.isdir(cand):
            messagebox.showerror("CU Compare",
                                 "Candidate folder is not a directory.")
            return

        self.run_btn.config(state="disabled")
        self.save_btn.config(state="disabled")
        self.status.set("Comparing...")
        self.out.delete("1.0", "end")
        threading.Thread(target=self._work, args=(gold, cand),
                         daemon=True).start()

    def _work(self, gold, cand):
        try:
            outcome = ce.compare_dirs(gold, cand)
            report = ce.build_report(outcome)
            attention = ce.needs_attention(outcome)
            self.q.put(("done", report, attention))
        except Exception:
            self.q.put(("error", traceback.format_exc(), False))

    def _drain_queue(self):
        try:
            while True:
                kind, payload, attention = self.q.get_nowait()
                if kind == "done":
                    self.last_report = payload
                    self.out.insert("1.0", payload)
                    self.save_btn.config(state="normal")
                    self.status.set(
                        "Needs attention -- see DETAIL below." if attention
                        else "All objects matched (or matched except header).")
                elif kind == "error":
                    self.out.insert("1.0", payload)
                    self.status.set("Error -- see output.")
                self.run_btn.config(state="normal")
        except queue.Empty:
            pass
        self.root.after(100, self._drain_queue)

    def on_save(self):
        if not self.last_report:
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".txt",
            initialfile="compare_report.txt",
            filetypes=[("Text", "*.txt"), ("All files", "*.*")])
        if not path:
            return
        try:
            with open(path, "w", encoding=ce.ENCODING) as f:
                f.write(self.last_report + "\n")
            self.status.set(f"Saved: {path}")
        except OSError as e:
            messagebox.showerror("CU Compare", f"Could not save: {e}")


def main():
    root = tk.Tk()
    CompareGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
