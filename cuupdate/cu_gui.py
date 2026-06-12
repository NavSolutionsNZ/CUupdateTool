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

# Tool version (single source of truth: cuupdate/__init__.py). Imported with a
# fallback so a flat frozen build (modules at top level, no package) still runs.
try:
    from cuupdate import __version__ as _VERSION
except Exception:
    try:
        from __init__ import __version__ as _VERSION
    except Exception:
        _VERSION = "1.9"


def derive_cust(root, force_vendor=None, force_cust=None):
    """Run the census on <root> with the developer's review deltas applied.

    Returns (cust_csv, summary_str, lists) where lists is
    {'cust': [(prefix, count), ...], 'vendor': [(prefix, count), ...]}
    so the GUI can populate its two list boxes. cust_csv is None if no
    A-side objects were found.
    """
    try:
        result = census.census(root, census.DEFAULT_VENDOR_EXCLUSIONS,
                               force_vendor=force_vendor, force_cust=force_cust)
    except SystemExit as e:                 # census exits if no A objects
        return None, f"census: {e}", {'cust': [], 'vendor': []}
    prefixes = result['prefixes']
    cust = sorted(p for p, r in prefixes.items() if not r['vendor'])
    vendor = sorted(p for p, r in prefixes.items() if r['vendor'])
    n = len(result['objects_scanned'])
    summary = (f"census: {n} objects -> customer tags "
               f"{','.join(cust) or '(none)'}"
               + (f"  [excluded vendor: {','.join(vendor)}]" if vendor else ""))
    lists = {
        'cust': [(p, prefixes[p]['count']) for p in cust],
        'vendor': [(p, prefixes[p]['count']) for p in vendor],
    }
    return ','.join(cust), summary, lists


class App:
    def __init__(self, master):
        self.master = master
        master.title("CU Update v%s - batch merge" % _VERSION)
        master.geometry("760x560")
        self.q = queue.Queue()

        pad = dict(padx=8, pady=4)
        frm = ttk.Frame(master)
        frm.pack(fill='x', **pad)

        # Job root picker
        ttk.Label(frm, text="Job folder (contains A\\ and B\\):").grid(row=0, column=0, sticky='w')
        self.root_var = tk.StringVar()
        self.root_entry = ttk.Entry(frm, textvariable=self.root_var, width=64)
        self.root_entry.grid(row=1, column=0, sticky='we')
        # Auto-census when the developer finishes editing the path (focus-out) or
        # presses Return. Browse-select triggers it directly (see pick_root).
        self.root_entry.bind('<FocusOut>', lambda e: self._maybe_census())
        self.root_entry.bind('<Return>', lambda e: self._maybe_census())
        ttk.Button(frm, text="Browse...", command=self.pick_root).grid(row=1, column=1, padx=4)

        # Folder the attribution lists were last populated from, so a repeated
        # focus-out on the SAME folder doesn't wipe the developer's manual moves.
        self._censused_root = None

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

        # Customer prefixes that only count as a tag WITH trailing digits.
        # Customer prefixes themselves are derived automatically from the census
        # (the version lists). This field is the per-customer SHAPE addendum: most
        # prefixes (e.g. WBL) are safe as bare letters because the combination
        # never appears in ordinary words, but a prose-risky prefix (e.g. AP,
        # which would otherwise match inside "Mapping") must be listed here so it
        # is only recognised when followed by digits (AP001662, AP_001662).
        # Blank = all prefixes digits-optional.
        self.cust_digits_var = tk.StringVar(value="")
        ttk.Label(grid, text="Prefixes needing digits:", width=22).grid(
            row=5, column=0, sticky='w', pady=2)
        ttk.Entry(grid, textvariable=self.cust_digits_var, width=40).grid(
            row=5, column=1, sticky='w')
        ttk.Label(grid, text="comma-separated, e.g. AP  (blank = none; "
                             "prevents matching letters inside words)",
                  foreground="#666").grid(row=6, column=1, sticky='w')

        # --- Tag attribution review (two-list view) -----------------------
        # The census proposes a customer/vendor split from each object's
        # Version List. The startswith vendor filter is only a first pass; a
        # prefix can be mis-attributed (a vendor prefix the filter missed, or a
        # customer prefix it wrongly swallowed). After a dry run populates these
        # lists, the developer moves any mis-attributed prefix to the correct
        # side with the arrow buttons. Customer prefixes gate customer
        # code-block carries; vendor prefixes do not. Empty until the first
        # (dry) run has produced a census.
        attr = ttk.LabelFrame(master, text="Tag attribution "
                              "(run a dry run to populate; move mis-attributed prefixes)")
        attr.pack(fill='x', padx=8, pady=4)

        ttk.Label(attr, text="Customer tags").grid(row=0, column=0, padx=4, pady=(4, 0))
        ttk.Label(attr, text="Excluded as vendor").grid(row=0, column=2, padx=4, pady=(4, 0))

        self.cust_list = tk.Listbox(attr, height=6, width=24,
                                    exportselection=False, font=('Consolas', 9))
        self.cust_list.grid(row=1, column=0, padx=4, pady=4, sticky='ns')

        movebtns = ttk.Frame(attr)
        movebtns.grid(row=1, column=1, padx=2)
        ttk.Button(movebtns, text="\u2192", width=3,
                   command=self.move_to_vendor).pack(pady=2)
        ttk.Button(movebtns, text="\u2190", width=3,
                   command=self.move_to_cust).pack(pady=2)

        self.vendor_list = tk.Listbox(attr, height=6, width=24,
                                      exportselection=False, font=('Consolas', 9))
        self.vendor_list.grid(row=1, column=2, padx=4, pady=4, sticky='ns')

        ttk.Label(attr, text="\u2192 marks a prefix as vendor (no customer carry);  "
                             "\u2190 marks it as a customer tag.",
                  foreground="#666").grid(row=2, column=0, columnspan=3,
                                          sticky='w', padx=4, pady=(0, 4))

        # Buttons
        btns = ttk.Frame(master)
        btns.pack(fill='x', **pad)
        self.run_btn = ttk.Button(btns, text="Run merge", command=self.on_run)
        self.run_btn.pack(side='left')
        # Default ON: the first run is a dry run so the census populates the
        # attribution lists for review before anything mutates the filesystem.
        # The developer unticks it for the real run.
        self.dry_var = tk.BooleanVar(value=True)
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

    # --- attribution list state --------------------------------------------
    # _counts: prefix -> occurrence count (for the display label).
    # _orig_cust/_orig_vendor: the census's FIRST-PASS proposal (before any
    # developer move), so the deltas we send back are computed relative to it:
    #   force_vendor = prefixes now on the vendor side that started customer
    #   force_cust   = prefixes now on the customer side that started vendor
    _counts = {}
    _orig_cust = set()
    _orig_vendor = set()

    def _fmt(self, pfx):
        return f"{pfx:8} x{self._counts.get(pfx, 0)}"

    def _pfx_of(self, label):
        return label.split()[0] if label else ''

    def populate_lists(self, lists):
        """Fill both list boxes from a census result, recording the original
        proposal so subsequent moves can be expressed as deltas."""
        self._counts = {p: c for p, c in lists['cust'] + lists['vendor']}
        self._orig_cust = {p for p, _ in lists['cust']}
        self._orig_vendor = {p for p, _ in lists['vendor']}
        self.cust_list.delete(0, 'end')
        self.vendor_list.delete(0, 'end')
        for p, _ in lists['cust']:
            self.cust_list.insert('end', self._fmt(p))
        for p, _ in lists['vendor']:
            self.vendor_list.insert('end', self._fmt(p))

    def _move(self, src, dst):
        sel = src.curselection()
        if not sel:
            return
        label = src.get(sel[0])
        src.delete(sel[0])
        dst.insert('end', label)

    def move_to_vendor(self):
        self._move(self.cust_list, self.vendor_list)

    def move_to_cust(self):
        self._move(self.vendor_list, self.cust_list)

    def current_overrides(self):
        """Return (force_vendor, force_cust) as the delta from the original
        census proposal to the current list state."""
        cur_vendor = {self._pfx_of(self.vendor_list.get(i))
                      for i in range(self.vendor_list.size())}
        cur_cust = {self._pfx_of(self.cust_list.get(i))
                    for i in range(self.cust_list.size())}
        force_vendor = sorted(cur_vendor - self._orig_vendor)   # moved cust->vendor
        force_cust = sorted(cur_cust - self._orig_cust)         # moved vendor->cust
        return force_vendor, force_cust

    def _maybe_census(self):
        """Auto-populate the attribution lists from the selected folder.

        Fires on Browse-select and on path-field focus-out / Return. Census-only
        (no merge), on a background thread, and silent on failure (no A/ tree or
        no Version Lists yet -> lists simply stay empty). Skips when the folder
        is unchanged AND the lists are already populated, so a stray focus-out
        never wipes the developer's manual moves. A genuinely new folder always
        repopulates (old corrections don't apply to a different job).
        """
        root = self.root_var.get().strip()
        if not root or not os.path.isdir(root):
            return
        already_populated = self.cust_list.size() or self.vendor_list.size()
        if root == self._censused_root and already_populated:
            return
        self._censused_root = root
        threading.Thread(target=self._census_work, args=(root,),
                         daemon=True).start()

    def _census_work(self, root):
        """Background census-only pass; hands lists back via the queue. Silent
        on any failure - the lists just stay as they were."""
        try:
            _cust, _summary, lists = derive_cust(root)
            if lists['cust'] or lists['vendor']:
                self.q.put(("CENSUS", lists))
        except Exception:
            pass            # no A/ tree yet, unreadable headers, etc. - stay quiet

    def pick_root(self):
        d = filedialog.askdirectory(title="Select job folder (contains A and B)")
        if d:
            self.root_var.set(d)
            self._maybe_census()

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
        cust_digits = self.cust_digits_var.get().strip()

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
        force_vendor, force_cust = self.current_overrides()
        t = threading.Thread(target=self._work,
                             args=(root, cu, initials, date, text, date_format,
                                   cust_digits, self.dry_var.get(),
                                   force_vendor, force_cust),
                             daemon=True)
        t.start()

    def _work(self, root, cu, initials, date, text, date_format, cust_digits, dry,
              force_vendor, force_cust):
        try:
            cust, summary, lists = derive_cust(root, force_vendor=force_vendor,
                                               force_cust=force_cust)
            self.q.put(summary + "\n")
            # Hand the classified lists back to the UI thread to repopulate the
            # two boxes (Tkinter widgets must only be touched on the main thread).
            self.q.put(("LISTS", lists))
            if cust is None:
                self.q.put("No customer tags derived; aborting.\n")
                self.q.put(("DONE", None))
                return
            report, results = run_batch.run(
                root, cu, initials, date, text=text, cust=cust,
                cust_digits=cust_digits,
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
                        n_n = len(r.get('nocu', []))
                        self._write(f"\n--- {n_m} auto-merged, {n_n} no CU change, "
                                    f"{n_d} left for manual review ---\n")
                elif isinstance(item, tuple) and item and item[0] == "LISTS":
                    self.populate_lists(item[1])
                elif isinstance(item, tuple) and item and item[0] == "CENSUS":
                    # Auto-census result (folder select). Populate only if the
                    # developer hasn't already started correcting this job.
                    self.populate_lists(item[1])
                    self._write("tags read from version lists; "
                                "review the attribution lists if needed.\n")
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
