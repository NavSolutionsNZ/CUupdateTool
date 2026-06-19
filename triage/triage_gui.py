#!/usr/bin/env python3
"""
triage_gui.py -- double-click launcher for the CU upgrade tooling.

Two tabs:
  - Baseline triage : compare Existing vs New vendor baselines (Stage 1), or
    export both from the database first. Produces the type-grouped pipe-
    separated carry list.
  - CU Pipeline     : HQ-file-driven Stage 2+3, run step by step so each
    subprocess hop (split, export, merge) surfaces its own result before the
    next. Split HQ file -> export customer+old-baseline -> classify ->
    stage+run CUupdate -> build import set.

Thin tkinter wrapper; all logic lives in triageengine / pipeline. Freeze with
triage.spec (see triage/BUILD.md).
"""
import os
import queue
import threading
import traceback

import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk

import triageengine as te
import pipeline as pl

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
        # Pipeline state carried between steps.
        self.pl_state = {}
        root.title(f"CU Tooling {_VERSION}")
        root.geometry("960x720")

        nb = ttk.Notebook(root)
        nb.pack(fill="x", padx=8, pady=(8, 0))
        self.baseline_tab = tk.Frame(nb)
        self.pipeline_tab = tk.Frame(nb)
        nb.add(self.baseline_tab, text="Baseline triage")
        nb.add(self.pipeline_tab, text="CU Pipeline")

        self._build_baseline_tab(self.baseline_tab)
        self._build_pipeline_tab(self.pipeline_tab)

        # Shared status + output.
        self.status = tk.StringVar(value="Ready.")
        tk.Label(root, textvariable=self.status, anchor="w",
                 fg="#555").pack(fill="x", padx=8)
        self.out = scrolledtext.ScrolledText(root, wrap="none",
                                             font=("Courier New", 10))
        self.out.pack(fill="both", expand=True, padx=8, pady=6)
        self.save_btn_holder = tk.Frame(root)
        self.save_btn_holder.pack(fill="x", padx=8, pady=(0, 6))
        self.save_btn = tk.Button(self.save_btn_holder, text="Save output...",
                                  command=self.on_save, state="disabled")
        self.save_btn.pack(side="left")

        self.root.after(100, self._drain_queue)

    # ---- shared helpers ----
    def _folder_row(self, parent, r, label, var):
        tk.Label(parent, text=label).grid(row=r, column=0, sticky="w", pady=2)
        tk.Entry(parent, textvariable=var, width=60).grid(
            row=r, column=1, sticky="ew", padx=6)
        tk.Button(parent, text="Browse...",
                  command=lambda: self._pick_dir(var)).grid(row=r, column=2)

    def _file_row(self, parent, r, label, var):
        tk.Label(parent, text=label).grid(row=r, column=0, sticky="w", pady=2)
        tk.Entry(parent, textvariable=var, width=60).grid(
            row=r, column=1, sticky="ew", padx=6)
        tk.Button(parent, text="Browse...",
                  command=lambda: self._pick_file(var)).grid(row=r, column=2)

    def _entry_row(self, parent, r, label, var, width=30):
        tk.Label(parent, text=label).grid(row=r, column=0, sticky="w", pady=2)
        tk.Entry(parent, textvariable=var, width=width).grid(
            row=r, column=1, sticky="w", padx=6)

    def _pick_dir(self, var):
        d = filedialog.askdirectory()
        if d:
            var.set(d)

    def _pick_file(self, var):
        f = filedialog.askopenfilename(filetypes=[("Text", "*.txt"),
                                                  ("All files", "*.*")])
        if f:
            var.set(f)

    def _emit(self, text, summ=""):
        self.out.delete("1.0", "end")
        self.out.insert("1.0", text)
        self.last_report = text
        self.save_btn.config(state="normal")
        if summ:
            self.status.set(summ)

    def _run_bg(self, fn, *args):
        self.status.set("Working...")
        threading.Thread(target=fn, args=args, daemon=True).start()

    # ================= Baseline triage tab =================
    def _build_baseline_tab(self, tab):
        pad = dict(padx=8, pady=4)
        top = tk.Frame(tab)
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

        exp = tk.LabelFrame(tab, text="Export baselines from database "
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
        tk.Button(exp, text="Export from DB, then triage",
                  command=self.on_export_and_triage).grid(
            row=4, column=1, sticky="w", padx=6, pady=4)

        btns = tk.Frame(tab)
        btns.pack(fill="x", **pad)
        tk.Button(btns, text="Run triage (folders above)",
                  command=self.on_run_baseline).pack(side="left", padx=4)

    def on_run_baseline(self):
        existing = self.existing_var.get().strip()
        new = self.new_var.get().strip()
        if not os.path.isdir(existing) or not os.path.isdir(new):
            messagebox.showerror("CU Tooling",
                                 "Both baseline folders must be directories.")
            return
        stage = self.stage_var.get().strip() or None
        self._run_bg(self._work_baseline, existing, new, stage)

    def _work_baseline(self, existing, new, stage):
        try:
            result = te.triage_baselines(existing, new)
            report = te.export_report(result)
            note = ""
            if stage:
                staged = te.stage_new_baseline(result, new, stage)
                note = f"\n\n[staged] {len(staged)} object(s) -> {stage}"
            text = report + "\n\nSummary: " + te.summary(result) + note
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
                "CU Tooling",
                "Fill in server, both database names, and the export root.")
            return
        self._run_bg(self._work_export_baseline, server, edb, ndb, root)

    def _work_export_baseline(self, server, edb, ndb, root):
        try:
            ok, log, existing_dir, new_dir = te.export_both_baselines(
                server, edb, ndb, root)
            if not ok:
                self.q.put(("error", "Export failed:\n\n" + log, ""))
                return
            self.existing_var.set(existing_dir)
            self.new_var.set(new_dir)
            result = te.triage_baselines(existing_dir, new_dir)
            report = te.export_report(result)
            text = log + "\n\n" + report + "\n\nSummary: " + te.summary(result)
            self.q.put(("done", text, te.summary(result)))
        except Exception:
            self.q.put(("error", traceback.format_exc(), ""))

    # ================= CU Pipeline tab =================
    def _build_pipeline_tab(self, tab):
        pad = dict(padx=8, pady=3)

        paths = tk.LabelFrame(tab, text="Inputs")
        paths.pack(fill="x", **pad)
        self.hq_file_var = tk.StringVar()
        self.job_root_var = tk.StringVar()
        self.server2_var = tk.StringVar()
        self.cust_db_var = tk.StringVar()
        self.old_db_var = tk.StringVar()
        self.cuupdate_var = tk.StringVar()
        self._file_row(paths, 0, "HQ changed-objects file:", self.hq_file_var)
        self._folder_row(paths, 1, "Job root (work folder):", self.job_root_var)
        self._entry_row(paths, 2, "SQL server:", self.server2_var)
        self._entry_row(paths, 3, "Customer DB (-> EX-):", self.cust_db_var)
        self._entry_row(paths, 4, "Old baseline DB (-> OB-):", self.old_db_var)
        self._file_row(paths, 5, "CUupdate exe (or run_batch.py):",
                       self.cuupdate_var)
        paths.columnconfigure(1, weight=1)

        mp = tk.LabelFrame(tab, text="Merge parameters (for the CUupdate step)")
        mp.pack(fill="x", **pad)
        self.cu_var = tk.StringVar()
        self.initials_var = tk.StringVar()
        self.date_var = tk.StringVar()
        self.datefmt_var = tk.StringVar(value="DDMMYY")
        self._entry_row(mp, 0, "CU token (e.g. CU26Q2):", self.cu_var)
        self._entry_row(mp, 1, "Initials:", self.initials_var, width=10)
        self._entry_row(mp, 2, "Date (DD/MM/YY, blank=today):", self.date_var,
                        width=14)
        tk.Label(mp, text="Date format:").grid(row=3, column=0, sticky="w")
        ttk.Combobox(mp, textvariable=self.datefmt_var, width=10,
                     values=["DDMMYY", "MMDDYY"], state="readonly").grid(
            row=3, column=1, sticky="w", padx=6)
        mp.columnconfigure(1, weight=1)

        steps = tk.LabelFrame(tab, text="Run step by step")
        steps.pack(fill="x", **pad)
        self.step_btns = {}
        for i, (key, label, cmd) in enumerate([
            ('split', "1. Split HQ file", self.on_pl_split),
            ('export', "2. Export customer + old baseline", self.on_pl_export),
            ('classify', "3. Classify + report", self.on_pl_classify),
            ('merge', "4. Stage + run CUupdate", self.on_pl_merge),
            ('import', "5. Build import set", self.on_pl_import),
        ]):
            b = tk.Button(steps, text=label, width=30, command=cmd)
            b.grid(row=i // 2, column=i % 2, sticky="w", padx=4, pady=3)
            self.step_btns[key] = b

    def _need(self, **fields):
        missing = [name for name, val in fields.items() if not val]
        if missing:
            messagebox.showerror("CU Pipeline",
                                 "Missing: " + ", ".join(missing))
            return False
        return True

    def on_pl_split(self):
        hq = self.hq_file_var.get().strip()
        root = self.job_root_var.get().strip()
        if not self._need(hq_file=hq, job_root=root):
            return
        if not os.path.isfile(hq):
            messagebox.showerror("CU Pipeline", "HQ file not found.")
            return
        self._run_bg(self._work_pl_split, hq, root)

    def _work_pl_split(self, hq, root):
        try:
            hq_dir = os.path.join(root, 'hq')
            keys, log = pl.split_hq_file(hq, hq_dir)
            self.pl_state['hq_dir'] = hq_dir
            self.pl_state['keys'] = keys
            text = (f"Split HQ file -> {hq_dir}\n{log}\n\n"
                    f"{len(keys)} object(s): {', '.join(keys) if keys else '-'}")
            self.q.put(("done", text, f"Split: {len(keys)} objects"))
        except Exception:
            self.q.put(("error", traceback.format_exc(), ""))

    def on_pl_export(self):
        root = self.job_root_var.get().strip()
        server = self.server2_var.get().strip()
        cdb = self.cust_db_var.get().strip()
        odb = self.old_db_var.get().strip()
        if not self._need(job_root=root, server=server, customer_db=cdb,
                          old_db=odb):
            return
        if not self.pl_state.get('keys'):
            messagebox.showerror("CU Pipeline", "Run step 1 (split) first.")
            return
        self._run_bg(self._work_pl_export, root, server, cdb, odb)

    def _work_pl_export(self, root, server, cdb, odb):
        try:
            flt = pl.keys_to_filter(self.pl_state['keys'])
            cust_dir = os.path.join(root, 'customer')
            old_dir = os.path.join(root, 'oldbase')
            ok_c, out_c = te.export_baseline(server, cdb, cust_dir, 'EX',
                                             filter_str=flt)
            ok_o, out_o = te.export_baseline(server, odb, old_dir, 'OB',
                                             filter_str=flt)
            self.pl_state['customer_dir'] = cust_dir
            self.pl_state['oldbase_dir'] = old_dir
            text = (f"Filter: {flt}\n\n[Customer/EX] {cdb}\n{out_c}\n\n"
                    f"[Old baseline/OB] {odb}\n{out_o}")
            if not (ok_c and ok_o):
                self.q.put(("error", "Export failed:\n\n" + text, ""))
                return
            self.q.put(("done", text, "Exported customer + old baseline"))
        except Exception:
            self.q.put(("error", traceback.format_exc(), ""))

    def on_pl_classify(self):
        if not (self.pl_state.get('hq_dir') and
                self.pl_state.get('customer_dir')):
            messagebox.showerror("CU Pipeline",
                                 "Run steps 1-2 first.")
            return
        self._run_bg(self._work_pl_classify)

    def _work_pl_classify(self):
        try:
            rows = pl.classify(self.pl_state['hq_dir'],
                               self.pl_state['customer_dir'],
                               self.pl_state['oldbase_dir'])
            self.pl_state['rows'] = rows
            report = pl.treatment_report(rows)
            self.q.put(("done", report,
                        f"Classified {len(rows)} object(s)"))
        except Exception:
            self.q.put(("error", traceback.format_exc(), ""))

    def on_pl_merge(self):
        if not self.pl_state.get('rows'):
            messagebox.showerror("CU Pipeline", "Run step 3 (classify) first.")
            return
        exe = self.cuupdate_var.get().strip()
        cu = self.cu_var.get().strip()
        initials = self.initials_var.get().strip()
        if not self._need(cuupdate=exe, cu_token=cu, initials=initials):
            return
        self._run_bg(self._work_pl_merge, exe, cu, initials,
                     self.date_var.get().strip(), self.datefmt_var.get())

    def _work_pl_merge(self, exe, cu, initials, date, datefmt):
        try:
            root = self.job_root_var.get().strip()
            n = pl.stage_merge_job(self.pl_state['rows'],
                                   self.pl_state['hq_dir'],
                                   self.pl_state['customer_dir'], root)
            ok, out = pl.run_cuupdate(exe, root, cu, initials,
                                      date or None, date_format=datefmt)
            text = (f"Staged {n} merge object(s) into A/ B/.\n\n"
                    f"CUupdate output:\n{out}")
            self.q.put(("done" if ok else "error",
                        text if ok else "CUupdate step failed:\n\n" + text,
                        f"Merge run: {n} staged"))
        except Exception:
            self.q.put(("error", traceback.format_exc(), ""))

    def on_pl_import(self):
        if not self.pl_state.get('rows'):
            messagebox.showerror("CU Pipeline", "Run steps 1-4 first.")
            return
        self._run_bg(self._work_pl_import)

    def _work_pl_import(self):
        try:
            root = self.job_root_var.get().strip()
            import_dir = os.path.join(root, 'Import')
            imported, manual = pl.build_import_set(
                self.pl_state['rows'], self.pl_state['hq_dir'], root,
                import_dir)
            report = pl.treatment_report(self.pl_state['rows'], imported,
                                         manual)
            text = (f"Import set -> {import_dir}\n"
                    f"{len(imported)} ready, {len(manual)} need manual merge.\n\n"
                    + report)
            self.q.put(("done", text,
                        f"Import: {len(imported)} ready, {len(manual)} manual"))
        except Exception:
            self.q.put(("error", traceback.format_exc(), ""))

    # ---- shared queue drain + save ----
    def _drain_queue(self):
        try:
            while True:
                kind, payload, summ = self.q.get_nowait()
                if kind == "done":
                    self._emit(payload, summ)
                elif kind == "error":
                    self._emit(payload, "Error -- see output.")
        except queue.Empty:
            pass
        self.root.after(100, self._drain_queue)

    def on_save(self):
        if not self.last_report:
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".txt", initialfile="cu_report.txt",
            filetypes=[("Text", "*.txt"), ("All files", "*.*")])
        if not path:
            return
        try:
            with open(path, "w", encoding=te.ce.ENCODING) as f:
                f.write(self.last_report + "\n")
            self.status.set(f"Saved: {path}")
        except OSError as e:
            messagebox.showerror("CU Tooling", f"Could not save: {e}")


def main():
    root = tk.Tk()
    TriageGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
