"""Interface gráfica do Consolidador de Carteiras de Investimento."""

import os
import shutil
import subprocess
import sys
import tempfile
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext

# Ensure project root is in path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

PRIMARY = "#2F5496"
BG = "#FFFFFF"
FONT_FAMILY = ("Segoe UI", "Arial")
FONT_MAIN = (FONT_FAMILY[0], 10)
FONT_LOG = ("Consolas", 9)
FONT_TITLE = (FONT_FAMILY[0], 16, "bold")
FONT_BTN = (FONT_FAMILY[0], 11, "bold")


class ConsolidadorApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Consolidador de Carteiras")
        self.root.geometry("750x650")
        self.root.resizable(False, False)
        self.root.configure(bg=BG)
        self.pdf_paths = []
        self._build_ui()

    def _build_ui(self):
        # --- Título ---
        lbl_title = tk.Label(
            self.root, text="Consolidador de Carteiras",
            font=FONT_TITLE, fg=PRIMARY, bg=BG,
        )
        lbl_title.pack(pady=(16, 8))

        # --- Separador ---
        tk.Frame(self.root, height=1, bg="#D9E2F3").pack(fill=tk.X, padx=20)

        # --- Frame de PDFs ---
        frm_pdf = tk.Frame(self.root, bg=BG)
        frm_pdf.pack(fill=tk.X, padx=20, pady=(12, 0))

        tk.Label(
            frm_pdf, text="Relatórios PDF:", font=FONT_MAIN, bg=BG, fg="#333",
        ).pack(anchor=tk.W)

        frm_list = tk.Frame(frm_pdf, bg=BG)
        frm_list.pack(fill=tk.X, pady=(4, 0))

        scrollbar = tk.Scrollbar(frm_list, orient=tk.VERTICAL)
        self.listbox = tk.Listbox(
            frm_list, height=6, font=FONT_MAIN,
            selectmode=tk.SINGLE, yscrollcommand=scrollbar.set,
            relief=tk.SOLID, borderwidth=1, highlightthickness=0,
        )
        scrollbar.config(command=self.listbox.yview)
        self.listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.listbox.bind("<Delete>", lambda _: self._remove_selected())

        # --- Botões Adicionar / Remover / Limpar ---
        frm_btns = tk.Frame(self.root, bg=BG)
        frm_btns.pack(fill=tk.X, padx=20, pady=(6, 0))

        btn_add = tk.Button(
            frm_btns, text="Adicionar PDFs", font=FONT_MAIN,
            command=self._add_files, relief=tk.GROOVE, padx=10,
        )
        btn_add.pack(side=tk.LEFT)

        btn_rem = tk.Button(
            frm_btns, text="Remover", font=FONT_MAIN,
            command=self._remove_selected, relief=tk.GROOVE, padx=10,
        )
        btn_rem.pack(side=tk.LEFT, padx=(8, 0))

        btn_clear = tk.Button(
            frm_btns, text="Limpar tudo", font=FONT_MAIN,
            command=self._clear_all, relief=tk.GROOVE, padx=10,
        )
        btn_clear.pack(side=tk.LEFT, padx=(8, 0))

        # --- Campo mês de referência ---
        frm_ref = tk.Frame(self.root, bg=BG)
        frm_ref.pack(fill=tk.X, padx=20, pady=(12, 0))

        tk.Label(
            frm_ref, text="Mês de referência (opcional):",
            font=FONT_MAIN, bg=BG, fg="#333",
        ).pack(side=tk.LEFT)

        self.entry_ref = tk.Entry(
            frm_ref, font=FONT_MAIN, width=14,
            relief=tk.SOLID, borderwidth=1,
        )
        self.entry_ref.pack(side=tk.LEFT, padx=(8, 0))
        self.entry_ref.insert(0, "Ex: 02/2026")
        self.entry_ref.config(fg="#999")
        self.entry_ref.bind("<FocusIn>", self._on_ref_focus_in)
        self.entry_ref.bind("<FocusOut>", self._on_ref_focus_out)

        # --- Separador ---
        tk.Frame(self.root, height=1, bg="#D9E2F3").pack(fill=tk.X, padx=20, pady=(12, 0))

        # --- Área de log ---
        frm_log = tk.Frame(self.root, bg=BG)
        frm_log.pack(fill=tk.BOTH, expand=True, padx=20, pady=(8, 0))

        tk.Label(
            frm_log, text="Log de processamento:", font=FONT_MAIN, bg=BG, fg="#333",
        ).pack(anchor=tk.W)

        self.log_area = scrolledtext.ScrolledText(
            frm_log, height=12, font=FONT_LOG,
            state=tk.DISABLED, relief=tk.SOLID, borderwidth=1,
            bg="#FAFBFD", wrap=tk.WORD,
        )
        self.log_area.pack(fill=tk.BOTH, expand=True, pady=(4, 0))

        # --- Botão Consolidar ---
        frm_action = tk.Frame(self.root, bg=BG)
        frm_action.pack(fill=tk.X, padx=20, pady=(12, 16))

        self.btn_consolidar = tk.Button(
            frm_action, text="Consolidar e Gerar Excel",
            font=FONT_BTN, bg=PRIMARY, fg="white",
            activebackground="#1F3A6E", activeforeground="white",
            relief=tk.FLAT, padx=20, pady=10,
            command=self._consolidar, cursor="hand2",
        )
        self.btn_consolidar.pack(expand=True)

    # --- Placeholder helpers ---

    def _on_ref_focus_in(self, _event):
        if self.entry_ref.get() == "Ex: 02/2026":
            self.entry_ref.delete(0, tk.END)
            self.entry_ref.config(fg="#000")

    def _on_ref_focus_out(self, _event):
        if not self.entry_ref.get().strip():
            self.entry_ref.insert(0, "Ex: 02/2026")
            self.entry_ref.config(fg="#999")

    # --- File management ---

    def _add_files(self):
        files = filedialog.askopenfilenames(
            title="Selecionar relatórios PDF",
            filetypes=[("Arquivos PDF", "*.pdf"), ("Todos", "*.*")],
        )
        for f in files:
            if f not in self.pdf_paths:
                self.pdf_paths.append(f)
        self._refresh_list()

    def _remove_selected(self):
        sel = self.listbox.curselection()
        if sel:
            self.pdf_paths.pop(sel[0])
            self._refresh_list()

    def _clear_all(self):
        self.pdf_paths.clear()
        self._refresh_list()

    def _refresh_list(self):
        self.listbox.delete(0, tk.END)
        for p in self.pdf_paths:
            self.listbox.insert(tk.END, f"  {os.path.basename(p)}")

    # --- Processing ---

    def _consolidar(self):
        if not self.pdf_paths:
            messagebox.showwarning("Aviso", "Nenhum PDF selecionado.")
            return

        self.btn_consolidar.config(state=tk.DISABLED, text="Processando...")
        self.log_area.config(state=tk.NORMAL)
        self.log_area.delete("1.0", tk.END)
        self.log_area.config(state=tk.DISABLED)

        thread = threading.Thread(target=self._run_engine, daemon=True)
        thread.start()

    def _run_engine(self):
        from core.engine import process_pdfs_with_callback

        ref = self.entry_ref.get().strip()
        if ref == "Ex: 02/2026":
            ref = None
        ref = ref or None

        tmp = os.path.join(tempfile.gettempdir(), "carteira_temp.xlsx")

        try:
            success = process_pdfs_with_callback(
                self.pdf_paths, tmp, ref, log_callback=self._log,
            )
        except Exception as e:
            self._log(f"\nErro inesperado: {e}")
            success = False

        if success:
            self.root.after(0, lambda: self._save_result(tmp))
        else:
            self.root.after(0, self._re_enable_button)

    def _save_result(self, tmp_path):
        dest = filedialog.asksaveasfilename(
            title="Salvar Excel consolidado",
            defaultextension=".xlsx",
            filetypes=[("Excel", "*.xlsx")],
            initialfile="carteira_consolidada.xlsx",
        )
        if dest:
            shutil.move(tmp_path, dest)
            self._log(f"\nSalvo em: {dest}")
            if messagebox.askyesno("Sucesso", "Deseja abrir o arquivo?"):
                self._open_file(dest)
        self._re_enable_button()

    def _re_enable_button(self):
        self.btn_consolidar.config(
            state=tk.NORMAL, text="Consolidar e Gerar Excel",
        )

    def _open_file(self, path):
        try:
            if sys.platform == "win32":
                os.startfile(path)
            elif sys.platform == "darwin":
                subprocess.run(["open", path])
            else:
                subprocess.run(["xdg-open", path])
        except Exception:
            pass

    # --- Logging ---

    def _log(self, msg):
        self.root.after(0, lambda m=msg: self._append_log(m))

    def _append_log(self, msg):
        self.log_area.config(state=tk.NORMAL)
        self.log_area.insert(tk.END, msg + "\n")
        self.log_area.see(tk.END)
        self.log_area.config(state=tk.DISABLED)


def main():
    root = tk.Tk()
    ConsolidadorApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
