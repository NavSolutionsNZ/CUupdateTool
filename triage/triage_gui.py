#!/usr/bin/env python3
"""
triage_gui.py -- double-click launcher for vendor-delta triage (Stage 1).

Pick the Existing and New vendor baseline folders (and optionally an output
folder to stage the changed + new objects into), click Run, and get the
type-grouped pipe-separated export report plus tallies. A thin tkinter wrapper
around triageengine; no triage logic of its own.

Freeze to a standalone .exe with triage.spec (see triage/BUILD.md).
"""
import os
import queue
import threading
import traceback

import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext

import triageengine as te

try:
    from triage import __version__ as _VERSION
except Exception:
    try:
        from __init__ import __version__ as _VERSION
    except Exception:
        _VERSION = "0.1"


class TriageGUI:
    def __init__(self, root):
        self.root = root
        self.q = queue.Queue()
        self.last_report = ""
        root.title(f"CU Triage {_VERSION} -- vendor delta")
        root.geometry("900x660")

        pad = dict(padx=8, pady=4)
        top = tk.Frame(root)
        top.pack(fill="x", **pad)

        self.existing_var = tk.StringVar()
        self.new_var = tk.StringVar()
        self.stage_var = tk.StringVar()

        self._folder_row(top, 0, "Existing baseline (current CU):",
                         self.existing_var)
        self._folder_row(top, 1, "New baseline (upgrade CU):", self.new_var)
        self._folder_row(top, 2, "Stage changed+new into (optional):",
                         self.stage_var)
        top.columnconfigure(1, weight=1)

        # --- Export-from-DB panel (populates the two baseline folders) ---
        exp = tk.LabelFrame(root, text="Export baselines from database "
                                       "(Windows auth)")
        exp.pack(fill="x", **pad)
        self.server_var = tk.StringVar()
        self.existing_db_var = tk.StringVar()
        self.new_db_var = tk.StringVar()
        self.export_root_var = tk.StringVar()

        self._entry_row(exp, 0, "SQL server:", self.server_var)
        self._entry_row(exp, 1, "Existing DB (-> OB-):", self.existing_db_var)
        self._entry_row(exp, 2, "New DB (-> CU-):", self.new_db_var)
        self._folder_row(exp, 3, "Export into root:", self.export_root_var)
        exp.columnconfigure(1, weight=1)
        self.export_btn = tk.Button(
            exp, text="Export from DB, then triage",
            command=self.on_export_and_triage)
        self.export_btn.grid(row=4, column=1, sticky="w", padx=6, pady=4)

        btns = tk.Frame(root)
        btns.pack(fill="x", **pad)
        self.run_btn = tk.Button(btns, text="Run triage",
                                 command=self.on_run, width=16)
        self.run_btn.pack(side="left", padx=4)
        self.save_btn = tk.Button(btns, text="Save report...",
                                  command=self.on_save, state="disabled",
                                  width=14)
        self.save_btn.pack(side="left", padx=4)

        self.status = tk.StringVar(
            value="Pick the two vendor baseline folders, then Run.")
        tk.Label(root, textvariable=self.status, anchor="w",
                 fg="#555").pack(fill="x", padx=8)

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

    def _entry_row(self, parent, r, label, var):
        tk.Label(parent, text=label).grid(row=r, column=0, sticky="w", pady=2)
        tk.Entry(parent, textvariable=var).grid(row=r, column=1,
                                                sticky="ew", padx=6)

    def _pick(self, var):
        d = filedialog.askdirectory()
        if d:
            var.set(d)

    def on_run(self):
        existing = self.existing_var.get().strip()
        new = self.new_var.get().strip()
        if not os.path.isdir(existing):
            messagebox.showerror("CU Triage",
                                 "Existing baseline is not a directory.")
            return
        if not os.path.isdir(new):
            messagebox.showerror("CU Triage",
                                 "New baseline is not a directory.")
            return
        stage = self.stage_var.get().strip() or None

        self.run_btn.config(state="disabled")
        self.save_btn.config(state="disabled")
        self.status.set("Comparing baselines...")
        self.out.delete("1.0", "end")
        threading.Thread(target=self._work, args=(existing, new, stage),
                         daemon=True).start()

    def _work(self, existing, new, stage):
        try:
            result = te.triage_baselines(existing, new)
            report = te.export_report(result)
            staged_note = ""
            if stage:
                staged = te.stage_new_baseline(result, new, stage)
                staged_note = f"\n\n[staged] {len(staged)} object(s) -> {stage}"
            text = report + "\n\nSummary: " + te.summary(result) + staged_note
            self.q.put(("done", text, te.summary(result)))
        except Exception:
            self.q.put(("error", traceback.format_exc(), ""))

    def on_export_and_triage(self):
        server = self.server_var.get().strip()
        edb = self.existing_db_var.get().strip()
        ndb = self.new_db_var.get().strip()
        root = self.export_root_var.get().strip()
        if not (server and edb and ndb and root):
            messagebox.showerror(
                "CU Triage",
                "Fill in server, both database names, and the export root.")
            return
        self.run_btn.config(state="disabled")
        self.export_btn.config(state="disabled")
        self.save_btn.config(state="disabled")
        self.status.set("Exporting baselines from database (this can take a "
                        "while)...")
        self.out.delete("1.0", "end")
        threading.Thread(target=self._export_work,
                         args=(server, edb, ndb, root), daemon=True).start()

    def _export_work(self, server, edb, ndb, root):
        try:
            ok, log, existing_dir, new_dir = te.export_both_baselines(
                server, edb, ndb, root)
            if not ok:
                self.q.put(("export_error", log, ""))
                return
            # Populate the folder fields and run the triage on the exports.
            self.existing_var.set(existing_dir)
            self.new_var.set(new_dir)
            result = te.triage_baselines(existing_dir, new_dir)
            report = te.export_report(result)
            text = (log + "\n\n" + report + "\n\nSummary: "
                    + te.summary(result))
            self.q.put(("done", text, te.summary(result)))
        except Exception:
            self.q.put(("error", traceback.format_exc(), ""))

    def _drain_queue(self):
        try:
            while True:
                kind, payload, summ = self.q.get_nowait()
                if kind == "done":
                    self.last_report = payload
                    self.out.insert("1.0", payload)
                    self.save_btn.config(state="normal")
                    self.status.set(summ)
                elif kind == "export_error":
                    self.out.insert("1.0",
                                    "Export failed:\n\n" + payload)
                    self.status.set("Export failed -- see output.")
                elif kind == "error":
                    self.out.insert("1.0", payload)
                    self.status.set("Error -- see output.")
                self.run_btn.config(state="normal")
                self.export_btn.config(state="normal")
        except queue.Empty:
            pass
        self.root.after(100, self._drain_queue)

    def on_save(self):
        if not self.last_report:
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".txt",
            initialfile="triage_report.txt",
            filetypes=[("Text", "*.txt"), ("All files", "*.*")])
        if not path:
            return
        try:
            with open(path, "w", encoding=te.ce.ENCODING) as f:
                f.write(self.last_report + "\n")
            self.status.set(f"Saved: {path}")
        except OSError as e:
            messagebox.showerror("CU Triage", f"Could not save: {e}")


def main():
    root = tk.Tk()
    TriageGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
