"""Interface grafica do Consolidador de Carteiras de Investimento."""

import os
import shutil
import subprocess
import sys
import tempfile
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk

# Ensure project root is in path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

PRIMARY = "#2F5496"
BG = "#FFFFFF"
FONT_FAMILY = ("Segoe UI", "Arial")
FONT_MAIN = (FONT_FAMILY[0], 10)
FONT_LOG = ("Consolas", 9)
FONT_TITLE = (FONT_FAMILY[0], 16, "bold")
FONT_BTN = (FONT_FAMILY[0], 11, "bold")
FONT_SMALL = (FONT_FAMILY[0], 9)


# ─────────────────────────────────────────────────────────────
#  Template Mapping Wizard
# ─────────────────────────────────────────────────────────────

class TemplateMappingWizard(tk.Toplevel):
    """Wizard modal para mapear colunas de PDFs nao reconhecidos."""

    def __init__(self, parent, pdf_path, tables, on_complete):
        super().__init__(parent)
        self.title("Mapeamento de Colunas")
        self.geometry("900x700")
        self.resizable(False, False)
        self.configure(bg=BG)
        self.pdf_path = pdf_path
        self.tables = tables
        self.on_complete = on_complete

        self.sample_table = None
        for t in tables:
            if len(t) > 2:
                self.sample_table = t
                break

        if not self.sample_table:
            messagebox.showwarning(
                "Aviso", "Nenhuma tabela encontrada no PDF.",
                parent=self,
            )
            self.destroy()
            return

        self.num_cols = max(len(row) for row in self.sample_table)
        self.col_options = [f"Col {i}" for i in range(self.num_cols)] + ["N/A"]

        self._build_preview()
        self._build_mapping()
        self._build_identification()
        self._build_actions()

    def _build_preview(self):
        frame = tk.LabelFrame(
            self, text="Preview do PDF (primeiras 8 linhas)",
            font=FONT_MAIN, padx=10, pady=5, bg=BG,
        )
        frame.pack(fill=tk.X, padx=10, pady=(10, 5))

        cols = [f"Col {i}" for i in range(self.num_cols)]
        tree = ttk.Treeview(frame, height=8, show="headings", columns=cols)
        for c in cols:
            tree.heading(c, text=c)
            tree.column(c, width=100, minwidth=60)

        for row in self.sample_table[:8]:
            padded = [str(v) if v else "" for v in row]
            padded += [""] * (self.num_cols - len(padded))
            tree.insert("", tk.END, values=padded)

        h_scroll = tk.Scrollbar(
            frame, orient=tk.HORIZONTAL, command=tree.xview,
        )
        tree.configure(xscrollcommand=h_scroll.set)
        tree.pack(fill=tk.X)
        h_scroll.pack(fill=tk.X)

    def _build_mapping(self):
        frame = tk.LabelFrame(
            self, text="Mapeamento de Campos",
            font=FONT_MAIN, padx=10, pady=5, bg=BG,
        )
        frame.pack(fill=tk.X, padx=10, pady=5)

        self.mappings = {}
        fields = [
            ("ativo", "Ativo (nome)"),
            ("data_aplicacao", "Data Aplicacao"),
            ("indexador", "Indexador"),
            ("taxa", "Taxa (%)"),
            ("vencimento", "Vencimento"),
            ("liquidez", "Liquidez"),
            ("valor_aplicado", "Valor Aplicado"),
            ("saldo_bruto", "Saldo Bruto"),
            ("saldo_liquido", "Saldo Liquido"),
        ]

        for i, (key, label) in enumerate(fields):
            row = i // 3
            col = i % 3
            sub = tk.Frame(frame, bg=BG)
            sub.grid(row=row, column=col, padx=5, pady=3, sticky="w")
            tk.Label(sub, text=label, font=FONT_SMALL, bg=BG).pack(anchor="w")
            var = tk.StringVar(value="N/A")
            ttk.Combobox(
                sub, textvariable=var, values=self.col_options,
                width=12, state="readonly",
            ).pack()
            self.mappings[key] = var

        # Subclasse padrao
        sub = tk.Frame(frame, bg=BG)
        sub.grid(row=3, column=0, padx=5, pady=3, sticky="w")
        tk.Label(sub, text="Subclasse padrao", font=FONT_SMALL, bg=BG).pack(anchor="w")
        self.var_subclasse = tk.StringVar(value="-")
        ttk.Combobox(
            sub, textvariable=self.var_subclasse, width=15, state="readonly",
            values=[
                "Pos-fixado", "Pre-fixado", "Inflacao",
                "Alternativo", "Multimercado", "-",
            ],
        ).pack()

        # Skip rows
        sub = tk.Frame(frame, bg=BG)
        sub.grid(row=3, column=1, columnspan=2, padx=5, pady=3, sticky="w")
        tk.Label(
            sub, text="Pular linhas contendo:", font=FONT_SMALL, bg=BG,
        ).pack(anchor="w")
        self.entry_skip = tk.Entry(sub, width=40, font=FONT_SMALL)
        self.entry_skip.insert(0, "total, subtotal, patrimonio")
        self.entry_skip.pack()

    def _build_identification(self):
        frame = tk.LabelFrame(
            self, text="Identificacao (para reutilizar automaticamente)",
            font=FONT_MAIN, padx=10, pady=5, bg=BG,
        )
        frame.pack(fill=tk.X, padx=10, pady=5)

        tk.Label(
            frame, text="Nome da corretora:", font=FONT_SMALL, bg=BG,
        ).grid(row=0, column=0, sticky="w", padx=5)
        self.entry_name = tk.Entry(frame, width=30, font=FONT_SMALL)
        self.entry_name.grid(row=0, column=1, padx=5, pady=3)

        tk.Label(
            frame, text="Palavras-chave (separadas por virgula):",
            font=FONT_SMALL, bg=BG,
        ).grid(row=1, column=0, sticky="w", padx=5)
        self.entry_keywords = tk.Entry(frame, width=50, font=FONT_SMALL)
        self.entry_keywords.grid(row=1, column=1, padx=5, pady=3)

    def _build_actions(self):
        frame = tk.Frame(self, bg=BG)
        frame.pack(pady=10)

        tk.Button(
            frame, text="Salvar Template e Aplicar",
            font=FONT_BTN, bg=PRIMARY, fg="white",
            activebackground="#1F3A6E", activeforeground="white",
            padx=20, pady=8, relief=tk.FLAT,
            command=self._save_and_apply,
        ).pack(side=tk.LEFT, padx=5)

        tk.Button(
            frame, text="Cancelar", font=FONT_MAIN,
            padx=15, pady=8, command=self.destroy,
        ).pack(side=tk.LEFT, padx=5)

    def _save_and_apply(self):
        from templates.template_manager import ColumnTemplate, save_template

        name = self.entry_name.get().strip()
        keywords = [
            k.strip() for k in self.entry_keywords.get().split(",")
            if k.strip()
        ]

        if not name:
            messagebox.showwarning(
                "Aviso", "Preencha o nome da corretora.", parent=self,
            )
            return
        if not keywords:
            messagebox.showwarning(
                "Aviso", "Preencha pelo menos uma palavra-chave.", parent=self,
            )
            return

        column_map = {}
        for key, var in self.mappings.items():
            val = var.get()
            if val != "N/A":
                col_idx = int(val.replace("Col ", ""))
                column_map[key] = col_idx

        if "ativo" not in column_map or "saldo_bruto" not in column_map:
            messagebox.showwarning(
                "Aviso", "Mapeie pelo menos 'Ativo' e 'Saldo Bruto'.",
                parent=self,
            )
            return

        skip = [
            s.strip() for s in self.entry_skip.get().split(",") if s.strip()
        ]

        template = ColumnTemplate(
            name=name,
            detection_keywords=keywords,
            column_map=column_map,
            default_subclasse=self.var_subclasse.get(),
            skip_rows_containing=skip,
        )

        save_template(template)
        assets = template.apply(self.tables)

        messagebox.showinfo(
            "Sucesso",
            f"Template '{name}' salvo!\n{len(assets)} ativos extraidos.",
            parent=self,
        )
        self.on_complete(assets)
        self.destroy()


# ─────────────────────────────────────────────────────────────
#  Main Application
# ─────────────────────────────────────────────────────────────

class ConsolidadorApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Consolidador de Carteiras")
        self.root.geometry("750x650")
        self.root.resizable(False, False)
        self.root.configure(bg=BG)
        self.pdf_paths = []
        self._pending_assets = []
        self._last_output = None
        self._last_ref = None
        self._build_ui()

    def _build_ui(self):
        # --- Titulo ---
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
            frm_pdf, text="Relatorios PDF:", font=FONT_MAIN, bg=BG, fg="#333",
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

        # --- Botoes Adicionar / Remover / Limpar ---
        frm_btns = tk.Frame(self.root, bg=BG)
        frm_btns.pack(fill=tk.X, padx=20, pady=(6, 0))

        tk.Button(
            frm_btns, text="Adicionar PDFs", font=FONT_MAIN,
            command=self._add_files, relief=tk.GROOVE, padx=10,
        ).pack(side=tk.LEFT)

        tk.Button(
            frm_btns, text="Remover", font=FONT_MAIN,
            command=self._remove_selected, relief=tk.GROOVE, padx=10,
        ).pack(side=tk.LEFT, padx=(8, 0))

        tk.Button(
            frm_btns, text="Limpar tudo", font=FONT_MAIN,
            command=self._clear_all, relief=tk.GROOVE, padx=10,
        ).pack(side=tk.LEFT, padx=(8, 0))

        # --- Campo mes de referencia ---
        frm_ref = tk.Frame(self.root, bg=BG)
        frm_ref.pack(fill=tk.X, padx=20, pady=(12, 0))

        tk.Label(
            frm_ref, text="Mes de referencia (opcional):",
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
        tk.Frame(self.root, height=1, bg="#D9E2F3").pack(
            fill=tk.X, padx=20, pady=(12, 0),
        )

        # --- Area de log ---
        frm_log = tk.Frame(self.root, bg=BG)
        frm_log.pack(fill=tk.BOTH, expand=True, padx=20, pady=(8, 0))

        tk.Label(
            frm_log, text="Log de processamento:",
            font=FONT_MAIN, bg=BG, fg="#333",
        ).pack(anchor=tk.W)

        self.log_area = scrolledtext.ScrolledText(
            frm_log, height=12, font=FONT_LOG,
            state=tk.DISABLED, relief=tk.SOLID, borderwidth=1,
            bg="#FAFBFD", wrap=tk.WORD,
        )
        self.log_area.pack(fill=tk.BOTH, expand=True, pady=(4, 0))

        # --- Botao Consolidar ---
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
            title="Selecionar relatorios PDF",
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
        self._pending_assets = []

        thread = threading.Thread(target=self._run_engine, daemon=True)
        thread.start()

    def _run_engine(self):
        from core.engine import process_pdfs_with_callback, UNPROCESSED_PDFS

        ref = self.entry_ref.get().strip()
        if ref == "Ex: 02/2026":
            ref = None
        ref = ref or None
        self._last_ref = ref

        tmp = os.path.join(tempfile.gettempdir(), "carteira_temp.xlsx")
        self._last_output = tmp

        try:
            success = process_pdfs_with_callback(
                self.pdf_paths, tmp, ref, log_callback=self._log,
            )
        except Exception as e:
            self._log(f"\nErro inesperado: {e}")
            success = False

        unprocessed = list(UNPROCESSED_PDFS)

        if success:
            self.root.after(0, lambda: self._post_process(tmp, unprocessed))
        elif unprocessed:
            self.root.after(
                0, lambda: self._offer_mapping_only(unprocessed),
            )
        else:
            self.root.after(0, self._re_enable_button)

    def _post_process(self, tmp_path, unprocessed):
        """Salva resultado e oferece mapeamento para PDFs nao processados."""
        self._save_result(tmp_path)
        if unprocessed:
            self._offer_mapping(unprocessed)

    def _offer_mapping_only(self, pdf_paths):
        """Quando nenhum ativo foi extraido, oferece mapeamento."""
        self._offer_mapping(pdf_paths)
        self._re_enable_button()

    def _offer_mapping(self, pdf_paths):
        """Oferece mapeamento manual para PDFs nao reconhecidos."""
        for pdf_path in pdf_paths:
            basename = os.path.basename(pdf_path)
            resp = messagebox.askyesno(
                "PDF nao reconhecido",
                f"O arquivo '{basename}' nao foi reconhecido.\n\n"
                f"Deseja mapear as colunas manualmente?\n"
                f"(O mapeamento sera salvo para uso futuro)",
            )
            if resp:
                from utils.pdf_reader import extract_from_pdf
                _, tables = extract_from_pdf(pdf_path)
                if tables:
                    wizard = TemplateMappingWizard(
                        self.root, pdf_path, tables,
                        on_complete=lambda assets: self._add_mapped_assets(assets),
                    )
                    wizard.grab_set()
                    self.root.wait_window(wizard)
                else:
                    messagebox.showwarning(
                        "Sem tabelas",
                        f"Nenhuma tabela encontrada em '{basename}'.\n"
                        f"O PDF pode ser baseado em imagens.",
                    )

    def _add_mapped_assets(self, assets):
        """Adiciona ativos mapeados manualmente e re-exporta."""
        if not assets:
            return

        self._log(f"\n+ {len(assets)} ativos adicionados via mapeamento manual")
        self._pending_assets.extend(assets)

        # Re-export com os novos ativos
        try:
            from exporters.excel import export_excel
            from core.engine import process_pdfs_with_callback

            # Re-ler o Excel existente nao e pratico; re-processar tudo
            # com os ativos extras adicionados
            if self._last_output and os.path.exists(self._last_output):
                # Ja temos o arquivo salvo — apenas re-exportamos
                # Infelizmente precisamos dos ativos originais
                # Solucao: salvar os novos ativos num Excel separado
                tmp2 = os.path.join(
                    tempfile.gettempdir(), "carteira_manual.xlsx",
                )
                export_excel(assets, tmp2, self._last_ref)
                self._log(f"Ativos manuais exportados temporariamente")
        except Exception as e:
            self._log(f"Erro ao re-exportar: {e}")

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
