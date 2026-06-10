#!/usr/bin/env python3
"""
cu_gui.py -- double-click launcher for the CU update batch merge.

A thin tkinter wrapper around the existing engine. It does NOT contain any
merge logic of its own: it collects the inputs run_batch.run() needs, fills
--cust automatically from the Stage 0 census (census.census on A's Version
Lists), runs the batch, and shows the report. Behaviour of the merge is
entirely run_batch / execute / diffengine.

Inputs (what run_batch.run needs):
  - Job root: one folder that CONTAINS A/ and B/ subfolders.
  - CU token (e.g. CU26Q1), developer initials (e.g. RL).
  - Text (changelog boilerplate, default "CU upgrade.").
  - Date (DD/MM/YY, defaults to today).
--cust is auto-derived by the census; --vend/--langs use run_batch defaults.

Runs on any machine with Python (tkinter ships with CPython). Freeze to a
standalone .exe with cu.spec (see BUILD.md) so it runs on the server with no
Python installed.
"""
import os
import queue
import threading
import traceback

import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk

import census
import run_batch


def derive_cust(root):
    """Run the census on <root> and return (cust_csv, summary_str).
    Falls back to run_batch's default if no A-side objects are found."""
    try:
        result = census.census(root, census.DEFAULT_VENDOR_EXCLUSIONS)
    except SystemExit as e:                 # census exits if no A objects
        return None, f"census: {e}"
    prefixes = result['prefixes']
    cust = sorted(p for p, r in prefixes.items() if not r['vendor'])
    vendor = sorted(p for p, r in prefixes.items() if r['vendor'])
    n = len(result['objects_scanned'])
    summary = (f"census: {n} objects -> customer tags "
               f"{','.join(cust) or '(none)'}"
               + (f"  [excluded vendor: {','.join(vendor)}]" if vendor else ""))
    return ','.join(cust), summary


class App:
    def __init__(self, master):
        self.master = master
        master.title("CU Update - batch merge")
        master.geometry("760x560")
        self.q = queue.Queue()

        pad = dict(padx=8, pady=4)
        frm = ttk.Frame(master)
        frm.pack(fill='x', **pad)

        # Job root picker
        ttk.Label(frm, text="Job folder (contains A\\ and B\\):").grid(row=0, column=0, sticky='w')
        self.root_var = tk.StringVar()
        ttk.Entry(frm, textvariable=self.root_var, width=64).grid(row=1, column=0, sticky='we')
        ttk.Button(frm, text="Browse...", command=self.pick_root).grid(row=1, column=1, padx=4)

        # Params
        self.cu_var = tk.StringVar()
        self.initials_var = tk.StringVar()
        self.text_var = tk.StringVar(value="CU upgrade.")
        self.date_var = tk.StringVar(value="")            # blank = use today (per format)
        self.date_fmt_var = tk.StringVar(value="DDMMYY")  # customer DB date locale

        grid = ttk.Frame(master)
        grid.pack(fill='x', **pad)
        self._field(grid, "CU token (e.g. CU26Q1):", self.cu_var, 0)
        self._field(grid, "Initials (e.g. RL):", self.initials_var, 1)
        self._field(grid, "Changelog text:", self.text_var, 2)
        self._field(grid, "Date (blank = today):", self.date_var, 3)

        # Customer DB date format: NAV writes the header Date= in the source
        # database's locale, so the dev declares which it is. Doc-trigger date is
        # always DD.MM.YY regardless.
        ttk.Label(grid, text="Customer DB date format:", width=22).grid(
            row=4, column=0, sticky='w', pady=2)
        fmt = ttk.Frame(grid)
        fmt.grid(row=4, column=1, sticky='w')
        ttk.Radiobutton(fmt, text="DD/MM/YY", variable=self.date_fmt_var,
                        value="DDMMYY").pack(side='left')
        ttk.Radiobutton(fmt, text="MM/DD/YY", variable=self.date_fmt_var,
                        value="MMDDYY").pack(side='left', padx=8)

        # Buttons
        btns = ttk.Frame(master)
        btns.pack(fill='x', **pad)
        self.run_btn = ttk.Button(btns, text="Run merge", command=self.on_run)
        self.run_btn.pack(side='left')
        self.dry_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(btns, text="Dry run (classify only, move nothing)",
                        variable=self.dry_var).pack(side='left', padx=12)

        # Busy indicator (shown only while a run is in progress)
        self.progress = ttk.Progressbar(btns, mode='indeterminate', length=120)
        self.status = ttk.Label(btns, text="")

        # Log
        self.log = scrolledtext.ScrolledText(master, height=20, wrap='word',
                                             font=('Consolas', 9))
        self.log.pack(fill='both', expand=True, padx=8, pady=6)
        self._write("Pick a job folder, fill the fields, and click Run merge.\n")

        self.master.after(100, self._drain)

    def _field(self, parent, label, var, row):
        ttk.Label(parent, text=label, width=22).grid(row=row, column=0, sticky='w', pady=2)
        ttk.Entry(parent, textvariable=var, width=40).grid(row=row, column=1, sticky='w')

    def pick_root(self):
        d = filedialog.askdirectory(title="Select job folder (contains A and B)")
        if d:
            self.root_var.set(d)

    def _write(self, s):
        self.log.insert('end', s)
        self.log.see('end')

    def _set_busy(self, busy):
        """Show + animate the spinner while working; hide + stop when done."""
        if busy:
            self.run_btn.config(state='disabled')
            self.status.config(text="Working\u2026")
            self.status.pack(side='left', padx=(12, 4))
            self.progress.pack(side='left')
            self.progress.start(12)          # ms per step
        else:
            self.progress.stop()
            self.progress.pack_forget()
            self.status.config(text="")
            self.status.pack_forget()
            self.run_btn.config(state='normal')

    def on_run(self):
        root = self.root_var.get().strip()
        cu = self.cu_var.get().strip()
        initials = self.initials_var.get().strip()
        text = self.text_var.get().strip() or "CU upgrade."
        date = self.date_var.get().strip()
        date_format = self.date_fmt_var.get()

        if not root or not os.path.isdir(root):
            messagebox.showerror("Missing", "Pick a valid job folder.")
            return
        if not (os.path.isdir(os.path.join(root, 'A')) and
                os.path.isdir(os.path.join(root, 'B'))):
            messagebox.showerror("Layout", "Job folder must contain A\\ and B\\ subfolders.")
            return
        if not cu or not initials:
            messagebox.showerror("Missing", "CU token and initials are required.")
            return

        self._set_busy(True)
        self.log.delete('1.0', 'end')
        t = threading.Thread(target=self._work,
                             args=(root, cu, initials, date, text, date_format,
                                   self.dry_var.get()),
                             daemon=True)
        t.start()

    def _work(self, root, cu, initials, date, text, date_format, dry):
        try:
            cust, summary = derive_cust(root)
            self.q.put(summary + "\n")
            if cust is None:
                self.q.put("No customer tags derived; aborting.\n")
                self.q.put(("DONE", None))
                return
            report, results = run_batch.run(
                root, cu, initials, date, text=text, cust=cust,
                date_format=date_format, dry_run=dry)
            self.q.put(report + "\n")
            self.q.put(("DONE", results))
        except Exception:
            self.q.put("\nERROR:\n" + traceback.format_exc())
            self.q.put(("DONE", None))

    def _drain(self):
        try:
            while True:
                item = self.q.get_nowait()
                if isinstance(item, tuple) and item and item[0] == "DONE":
                    self._set_busy(False)
                    r = item[1]
                    if r is not None:
                        n_m, n_d = len(r['merged']), len(r['dev'])
                        self._write(f"\n--- {n_m} auto-merged, {n_d} left for manual review ---\n")
                else:
                    self._write(item)
        except queue.Empty:
            pass
        self.master.after(100, self._drain)


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == '__main__':
    main()
