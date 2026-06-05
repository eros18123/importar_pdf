# -*- coding: utf-8 -*-
import os
import json
import subprocess
import sys
import time
import threading
from aqt import mw
from aqt.qt import *
from aqt.utils import showInfo, showWarning, tooltip
from aqt import gui_hooks

from .pdf_anatomy import process_anatomy
from .pdf_tables import process_tables
from .pdf_cloze import process_cloze
from .pdf_mcq_text import process_mcq, process_text
from .image_paste import on_editor_paste

from .audio_gen import generate_audio_tag
from .models import (
    get_or_create_basic_model, 
    get_or_create_cloze_model, 
    get_or_create_image_occlusion_model, 
    get_premium_model,
    get_or_create_mcq_model
)
from .web_ai import WebBrowserWidget, os_paste, HAS_WEBENGINE

ADDON_PATH  = os.path.dirname(__file__)
PROFILE_DIR = os.path.join(ADDON_PATH, 'web_profile')
CONFIG_FILE = os.path.join(ADDON_PATH, 'ultimate_config.json')

if not os.path.exists(PROFILE_DIR): os.makedirs(PROFILE_DIR)

DEFAULT_PROMPT = "Aja como um professor especialista. Leia o texto/imagem e crie flashcards. Retorne ESTRITAMENTE em formato JSON: [{\"pergunta\":\"...\", \"resposta\":\"...\"}]"

def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            pass
            
    return {
        "pdf_path": "",
        "pdf_deck": "",
        "pdf_model": "",
        "pdf_mode": 0,
        "pdf_audio": True,
        "pdf_page_start": 1,
        "pdf_page_end": 9999,
        "ai_deck": "",
        "ai_audio": True,
        "prompts": [{"name": "Padrão (JSON)", "text": DEFAULT_PROMPT}],
        "current_prompt_idx": 0
    }

def save_config(data):
    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
    except Exception as e:
        pass

def _auto_install(packages):
    msg = QMessageBox()
    msg.setWindowTitle("Instalação de Dependências")
    msg.setText(f"O add-on precisa instalar as seguintes dependências:\n{', '.join(packages)}\n\nIsso pode demorar um pouco. Deseja continuar?")
    msg.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
    if msg.exec() == QMessageBox.StandardButton.Yes:
        progress = QProgressDialog("Baixando e instalando dependências...", "Cancelar", 0, 0)
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.show()
        QApplication.processEvents()
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", "--upgrade"] + packages)
            progress.close()
            showInfo("Dependências instaladas com sucesso! Por favor, reinicie o Anki para aplicá-las.")
            return True
        except subprocess.CalledProcessError as e:
            progress.close()
            showWarning(f"Erro ao instalar dependências: {e}")
            return False
    return False

def ensure_deps(check_audio=False):
    missing = []
    try: import fitz
    except ImportError: missing.append("PyMuPDF")
    try: import pdfplumber
    except ImportError: missing.append("pdfplumber")
    try: from PIL import Image
    except ImportError: missing.append("Pillow")
        
    if check_audio:
        try: import gtts
        except ImportError: missing.append("gTTS")
    
    if missing:
        return _auto_install(missing)
    return True

def ensure_cv_deps():
    missing = []
    try: import cv2
    except ImportError: missing.append("opencv-python")
    try: import numpy
    except ImportError: missing.append("numpy")
    try: import pytesseract
    except ImportError: missing.append("pytesseract")
        
    if missing:
        return _auto_install(missing)
    return True

class PdfImportWorker(QThread):
    progress_update = pyqtSignal(int, str)
    finished_import = pyqtSignal(bool, str)

    def __init__(self, pdf_path, import_mode="auto", deck_name="", model_name="", start_page=0, end_page=0):
        super().__init__()
        self.pdf_path = pdf_path
        self.import_mode = import_mode
        self.deck_name = deck_name
        self.model_name = model_name
        self.start_page = start_page
        self.end_page = end_page
        self.is_cancelled = False

    def _emit_progress(self, current, total, msg):
        val = int((current / (total if total > 0 else 1)) * 100) if total > 0 else 0
        self.progress_update.emit(val, msg)

    def run(self):
        try:
            import fitz
            doc = fitz.open(self.pdf_path)
            
            if not self.deck_name:
                self.deck_name = mw.col.decks.current()['name']
            
            deck_id = mw.col.decks.id(self.deck_name)
            
            model = mw.col.models.by_name(self.model_name)
            if not model:
                self.finished_import.emit(False, f"Erro: Tipo de nota '{self.model_name}' não encontrado.")
                doc.close()
                return

            real_end = len(doc) - 1
            if self.end_page > real_end:
                self.end_page = real_end
            if self.start_page < 0:
                self.start_page = 0
            
            if self.import_mode == "tables":
                process_tables(self, doc, deck_id, self.deck_name, self.start_page, self.end_page, model, self.pdf_path)
            elif self.import_mode == "anatomy":
                process_anatomy(self, doc, deck_id, self.deck_name, self.start_page, self.end_page, model)
            elif self.import_mode == "cloze":
                process_cloze(self, doc, deck_id, self.deck_name, self.start_page, self.end_page, model)
            elif self.import_mode == "mcq":
                process_mcq(self, doc, deck_id, self.deck_name, self.start_page, self.end_page, model)
            else:
                process_text(self, doc, deck_id, self.deck_name, self.start_page, self.end_page, model)
                
            doc.close()
        except Exception as e:
            self.finished_import.emit(False, str(e))

class UltimateSuiteDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent, Qt.WindowType.Window)
        self.setWindowTitle("🚀 Anki Ultimate Suite (PDF + IA + Áudio)")
        self.resize(1150, 750)
        
        self.config = load_config()
        
        layout = QVBoxLayout(self)
        self.main_tabs = QTabWidget()
        layout.addWidget(self.main_tabs)
        
        self.setup_pdf_tab()
        self.setup_ai_tab()
        self.worker = None
        
        self.load_state() 
        
    def setup_pdf_tab(self):
        w = QWidget()
        l = QVBoxLayout(w)
        
        l.addWidget(QLabel("<b>1. Selecione o PDF:</b>"))
        h1 = QHBoxLayout()
        self.pdf_path_input = QLineEdit()
        self.pdf_path_input.setReadOnly(True)
        btn_pdf = QPushButton("Procurar PDF")
        btn_pdf.clicked.connect(self.browse_pdf)
        h1.addWidget(self.pdf_path_input)
        h1.addWidget(btn_pdf)
        l.addLayout(h1)
        
        h_pages = QHBoxLayout()
        h_pages.addWidget(QLabel("<b>Páginas:</b> De"))
        self.spin_start = QSpinBox()
        self.spin_start.setRange(1, 99999)
        self.spin_end = QSpinBox()
        self.spin_end.setRange(1, 99999)
        self.lbl_total = QLabel("(0 páginas)")
        self.lbl_total.setStyleSheet("color: #555;")
        
        h_pages.addWidget(self.spin_start)
        h_pages.addWidget(QLabel("até"))
        h_pages.addWidget(self.spin_end)
        h_pages.addWidget(self.lbl_total)
        h_pages.addStretch()
        l.addLayout(h_pages)
        
        l.addWidget(QLabel("<b>2. Deck de Destino:</b>"))
        self.pdf_deck_combo = QComboBox()
        decks = sorted(mw.col.decks.all_names())
        self.pdf_deck_combo.addItems(decks)
        
        self.pdf_deck_combo.setEditable(True)
        self.pdf_deck_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        completer_pdf = self.pdf_deck_combo.completer()
        completer_pdf.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        completer_pdf.setFilterMode(Qt.MatchFlag.MatchContains)
        l.addWidget(self.pdf_deck_combo)
        
        mode_group_box = QGroupBox("3. Modo de Importação:")
        grid_mode = QGridLayout()
        
        self.mode_group = QButtonGroup(self)
        self.rb_auto = QRadioButton("Texto -> Cards Básicos")
        self.rb_cloze = QRadioButton("Texto -> Cloze")
        self.rb_tables = QRadioButton("Tabelas -> Image Occlusion")
        self.rb_anatomy = QRadioButton("Anatomia -> Image Occlusion")
        self.rb_mcq = QRadioButton("Questões -> Múltipla Escolha")
        
        grid_mode.addWidget(self.rb_auto, 0, 0)
        grid_mode.addWidget(self.rb_cloze, 0, 1)
        grid_mode.addWidget(self.rb_tables, 1, 0)
        grid_mode.addWidget(self.rb_anatomy, 1, 1)
        grid_mode.addWidget(self.rb_mcq, 2, 0)
        
        self.mode_group.addButton(self.rb_auto, 0)
        self.mode_group.addButton(self.rb_cloze, 1)
        self.mode_group.addButton(self.rb_tables, 2)
        self.mode_group.addButton(self.rb_anatomy, 3)
        self.mode_group.addButton(self.rb_mcq, 4)
        
        self.mode_group.idClicked.connect(self.on_mode_changed)
        
        mode_group_box.setLayout(grid_mode)
        l.addWidget(mode_group_box)
        
        l.addWidget(QLabel("<b>4. Tipo de Nota (Modelo):</b>"))
        self.pdf_model_combo = QComboBox()
        models = sorted([m['name'] for m in mw.col.models.all()])
        self.pdf_model_combo.addItems(models)
        self.pdf_model_combo.setEditable(True)
        self.pdf_model_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        completer_model = self.pdf_model_combo.completer()
        completer_model.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        completer_model.setFilterMode(Qt.MatchFlag.MatchContains)
        l.addWidget(self.pdf_model_combo)
        
        self.chk_audio_pdf = QCheckBox("Gerar Áudio (gTTS) para as respostas")
        l.addWidget(self.chk_audio_pdf)
        
        self.progress = QProgressBar()
        self.progress.setValue(0)
        l.addWidget(self.progress)
        
        self.lbl_status = QLabel("Pronto.")
        l.addWidget(self.lbl_status)
        
        self.btn_run_pdf = QPushButton("▶ Processar PDF")
        self.btn_run_pdf.setStyleSheet("background:#2563eb; color:white; font-weight:bold; padding:10px;")
        self.btn_run_pdf.clicked.connect(self.run_pdf)
        l.addWidget(self.btn_run_pdf)
        l.addStretch()
        
        self.main_tabs.addTab(w, "📄 Importador de PDF")

    def setup_ai_tab(self):
        w = QWidget()
        l = QVBoxLayout(w)
        
        split = QSplitter(Qt.Orientation.Horizontal)
        
        left = QWidget()
        ll = QVBoxLayout(left)
        
        ll.addWidget(QLabel("<b>1. Deck de Destino:</b>"))
        self.deck_combo = QComboBox()
        decks = sorted(mw.col.decks.all_names())
        self.deck_combo.addItems(decks)
        
        self.deck_combo.setEditable(True)
        self.deck_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        completer = self.deck_combo.completer()
        completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        ll.addWidget(self.deck_combo)
        
        self.chk_audio_ia = QCheckBox("Gerar Áudio (gTTS) para as respostas")
        ll.addWidget(self.chk_audio_ia)
        
        ll.addWidget(QLabel("<b>2. Prompt da IA:</b>"))
        h_prompt = QHBoxLayout()
        self.prompt_combo = QComboBox()
        self.prompt_combo.currentIndexChanged.connect(self.on_prompt_changed)
        h_prompt.addWidget(self.prompt_combo, stretch=1)
        
        btn_new_prompt = QPushButton("Novo")
        btn_new_prompt.clicked.connect(self.new_prompt)
        btn_save_prompt = QPushButton("Salvar")
        btn_save_prompt.clicked.connect(self.save_prompt)
        btn_del_prompt = QPushButton("Excluir")
        btn_del_prompt.clicked.connect(self.delete_prompt)
        
        h_prompt.addWidget(btn_new_prompt)
        h_prompt.addWidget(btn_save_prompt)
        h_prompt.addWidget(btn_del_prompt)
        ll.addLayout(h_prompt)
        
        self.prompt_text = QTextEdit()
        self.prompt_text.setMaximumHeight(100)
        ll.addWidget(self.prompt_text)
        
        ll.addWidget(QLabel("<b>3. Automação Web (Grátis):</b>"))
        btn_chatgpt = QPushButton("🌐 Abrir ChatGPT e Colar")
        btn_chatgpt.clicked.connect(self.open_chatgpt)
        ll.addWidget(btn_chatgpt)
        
        btn_pull = QPushButton("📥 Puxar JSON da IA")
        btn_pull.clicked.connect(self.pull_json)
        ll.addWidget(btn_pull)
        
        self.json_input = QTextEdit()
        self.json_input.setPlaceholderText("O JSON extraído aparecerá aqui...")
        ll.addWidget(self.json_input)
        
        btn_create = QPushButton("✨ Criar Cards Premium")
        btn_create.setStyleSheet("background:#16a34a; color:white; font-weight:bold; padding:10px;")
        btn_create.clicked.connect(self.create_premium_cards)
        ll.addWidget(btn_create)
        
        split.addWidget(left)
        
        if HAS_WEBENGINE:
            self.browser = WebBrowserWidget(PROFILE_DIR)
            split.addWidget(self.browser)
        else:
            split.addWidget(QLabel("Instale PyQt6-WebEngine para usar o navegador interno."))
            
        split.setSizes([450, 700])
        l.addWidget(split)
        self.main_tabs.addTab(w, "🤖 IA Web & Cards Premium")

    def load_pdf_info(self, path, silent=False):
        if not path or not os.path.exists(path): return
        try:
            import fitz
            doc = fitz.open(path)
            total = len(doc)
            self.lbl_total.setText(f"(Total: {total} páginas)")
            self.spin_start.setMaximum(total)
            self.spin_end.setMaximum(total)
            
            if not silent:
                self.spin_start.setValue(1)
                self.spin_end.setValue(total)
            doc.close()
        except Exception:
            self.lbl_total.setText("(Erro ao ler PDF)")

    def on_mode_changed(self, mode_id):
        model = None
        if mode_id == 0:
            model = get_or_create_basic_model()
        elif mode_id == 1:
            model = get_or_create_cloze_model()
        elif mode_id in (2, 3):
            model = get_or_create_image_occlusion_model()
        elif mode_id == 4:
            model = get_or_create_mcq_model()
            
        if model:
            current_models = sorted([m['name'] for m in mw.col.models.all()])
            self.pdf_model_combo.blockSignals(True)
            self.pdf_model_combo.clear()
            self.pdf_model_combo.addItems(current_models)
            self.pdf_model_combo.setCurrentText(model['name'])
            self.pdf_model_combo.blockSignals(False)

    def load_state(self):
        pdf_path = self.config.get("pdf_path", "")
        self.pdf_path_input.setText(pdf_path)
        
        try:
            import fitz
            self.load_pdf_info(pdf_path, silent=True)
            self.spin_start.setValue(self.config.get("pdf_page_start", 1))
            self.spin_end.setValue(self.config.get("pdf_page_end", 9999))
        except ImportError:
            pass
        
        pdf_deck = self.config.get("pdf_deck", "")
        if pdf_deck:
            self.pdf_deck_combo.setCurrentText(pdf_deck)
            
        ai_deck = self.config.get("ai_deck", "")
        if ai_deck:
            self.deck_combo.setCurrentText(ai_deck)
            
        mode_idx = self.config.get("pdf_mode", 0)
        btn = self.mode_group.button(mode_idx)
        if btn:
            btn.setChecked(True)
            self.on_mode_changed(mode_idx)
            
        pdf_model = self.config.get("pdf_model", "")
        if pdf_model:
            self.pdf_model_combo.setCurrentText(pdf_model)
            
        self.chk_audio_pdf.setChecked(self.config.get("pdf_audio", True))
        self.chk_audio_ia.setChecked(self.config.get("ai_audio", True))
        
        self.refresh_prompt_combo()
        idx = self.config.get("current_prompt_idx", 0)
        if 0 <= idx < self.prompt_combo.count():
            self.prompt_combo.setCurrentIndex(idx)

    def save_state(self):
        self.config["pdf_path"] = self.pdf_path_input.text()
        self.config["pdf_deck"] = self.pdf_deck_combo.currentText()
        self.config["pdf_model"] = self.pdf_model_combo.currentText()
        self.config["pdf_mode"] = self.mode_group.checkedId()
        self.config["pdf_audio"] = self.chk_audio_pdf.isChecked()
        self.config["pdf_page_start"] = self.spin_start.value()
        self.config["pdf_page_end"] = self.spin_end.value()
        self.config["ai_deck"] = self.deck_combo.currentText()
        self.config["ai_audio"] = self.chk_audio_ia.isChecked()
        self.config["current_prompt_idx"] = self.prompt_combo.currentIndex()
        save_config(self.config)

    def closeEvent(self, event):
        self.save_state() 
        super().closeEvent(event)

    def refresh_prompt_combo(self):
        self.prompt_combo.blockSignals(True)
        self.prompt_combo.clear()
        for p in self.config["prompts"]:
            self.prompt_combo.addItem(p["name"])
        self.prompt_combo.blockSignals(False)

    def on_prompt_changed(self, idx):
        if 0 <= idx < len(self.config["prompts"]):
            self.prompt_text.setPlainText(self.config["prompts"][idx]["text"])

    def new_prompt(self):
        name, ok = QInputDialog.getText(self, "Novo Prompt", "Nome do Prompt:")
        if ok and name.strip():
            new_p = {"name": name.strip(), "text": self.prompt_text.toPlainText()}
            self.config["prompts"].append(new_p)
            self.refresh_prompt_combo()
            self.prompt_combo.setCurrentIndex(len(self.config["prompts"]) - 1)
            self.save_state()

    def save_prompt(self):
        idx = self.prompt_combo.currentIndex()
        if idx >= 0:
            self.config["prompts"][idx]["text"] = self.prompt_text.toPlainText()
            self.save_state()
            tooltip("Prompt salvo com sucesso!")

    def delete_prompt(self):
        if len(self.config["prompts"]) <= 1:
            showWarning("Você precisa ter pelo menos um prompt salvo.")
            return
        idx = self.prompt_combo.currentIndex()
        if idx >= 0:
            del self.config["prompts"][idx]
            self.refresh_prompt_combo()
            self.prompt_combo.setCurrentIndex(0)
            self.on_prompt_changed(0)
            self.save_state()

    def browse_pdf(self):
        path, _ = QFileDialog.getOpenFileName(self, "Selecionar PDF", "", "PDF (*.pdf)")
        if path:
            self.pdf_path_input.setText(path)
            if ensure_deps():
                self.load_pdf_info(path, silent=False)

    def run_pdf(self):
        self.save_state()

        pdf_path = self.pdf_path_input.text()
        if not pdf_path or not os.path.exists(pdf_path):
            showWarning("Selecione um PDF válido.")
            return
            
        check_audio = self.chk_audio_pdf.isChecked()
        if not ensure_deps(check_audio=check_audio): return

        mode_id = self.mode_group.checkedId()
        
        # EXIGÊNCIA DO TESSERACT OCR PARA O MODO DE ANATOMIA
        if mode_id == 3:
            if not ensure_cv_deps(): return
            from .image_paste import get_tesseract_path, download_tesseract_sync
            if not get_tesseract_path() and os.name == 'nt':
                msg_dl = QMessageBox(self)
                msg_dl.setWindowTitle("Motor de IA Ausente")
                msg_dl.setText("O modo de Anatomia avançado usa a IA do Tesseract OCR para ler imagens chapadas.\n\nDeseja baixar e instalar automaticamente agora? (~40MB)")
                msg_dl.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
                if msg_dl.exec() == QMessageBox.StandardButton.Yes:
                    if not download_tesseract_sync(self):
                        return
                else:
                    return
            elif not get_tesseract_path():
                showWarning("Por favor, instale o Tesseract OCR no seu sistema para poder extrair nomes das imagens.")
                return

        selected_model = self.pdf_model_combo.currentText()
        model = mw.col.models.by_name(selected_model)
        if not model:
            showWarning(f"O Tipo de Nota '{selected_model}' não foi encontrado no seu Anki.")
            return
            
        field_names = [f['name'] for f in model['flds']]
        
        if mode_id in (2, 3): 
            req = ["Imagem", "ImagemResposta", "Gabarito"]
            if not all(r in field_names for r in req):
                showWarning(f"O modelo '{selected_model}' não possui os campos corretos.\n\nPara o modo de Imagens/Anatomia, o tipo de nota precisa ter os campos:\n{', '.join(req)}\n\nPor favor, mude a caixa 'Tipo de Nota' para 'Image Occlusion (PDF Import)'.")
                return
        elif mode_id == 4: 
            req = ["Titulo", "Enunciado", "A", "B", "C", "D", "E", "Gabarito"]
            if not all(r in field_names for r in req):
                showWarning(f"O modelo '{selected_model}' não possui os campos corretos.\n\nPara Múltipla Escolha, o tipo de nota precisa ter os campos:\n{', '.join(req)}\n\nPor favor, mude a caixa 'Tipo de Nota' para 'Múltipla Escolha (PDF Import)'.")
                return
        elif mode_id == 1: 
            if not any("Texto" in f for f in field_names) and len(field_names) < 1:
                showWarning("O modelo para Cloze precisa ter pelo menos um campo principal (como 'Texto').")
                return

        modes = {0: "auto", 1: "cloze", 2: "tables", 3: "anatomy", 4: "mcq"}
        mode = modes.get(mode_id, "auto")
        
        selected_deck = self.pdf_deck_combo.currentText()
        
        start_p = self.spin_start.value() - 1
        end_p = self.spin_end.value() - 1

        self.btn_run_pdf.setEnabled(False)
        self.progress.setValue(0)
        
        self.worker = PdfImportWorker(
            pdf_path, 
            import_mode=mode, 
            deck_name=selected_deck, 
            model_name=selected_model,
            start_page=start_p,
            end_page=end_p
        )
        self.worker.progress_update.connect(self.update_progress)
        self.worker.finished_import.connect(self.on_pdf_finished)
        self.worker.start()

    def update_progress(self, val, text):
        self.progress.setValue(val)
        self.lbl_status.setText(text)

    def on_pdf_finished(self, success, msg):
        self.btn_run_pdf.setEnabled(True)
        mw.reset()
        if success: showInfo(msg)
        else: showWarning(msg)

    def open_chatgpt(self):
        if not HAS_WEBENGINE: return
        prompt = self.prompt_text.toPlainText().strip()
        QApplication.clipboard().setText(prompt)
        
        browser_view = self.browser.tabs.currentWidget()
        browser_view.setUrl(QUrl("https://chatgpt.com"))
        
        def on_load(ok):
            if not ok: return
            QTimer.singleShot(2500, self.inject_paste)
            
        browser_view.loadFinished.connect(on_load)

    def inject_paste(self):
        browser_view = self.browser.tabs.currentWidget()
        js = """
        (function() {
            var el = document.querySelector('#prompt-textarea') || document.querySelector('div[contenteditable="true"]');
            if (el) { el.click(); el.focus(); return 'ok'; }
            return 'fail';
        })()
        """
        def after_focus(res):
            if res == 'ok':
                self.raise_()
                self.activateWindow()
                browser_view.setFocus()
                threading.Thread(target=os_paste, daemon=True).start()
        browser_view.page().runJavaScript(js, after_focus)

    def pull_json(self):
        browser_view = self.browser.tabs.currentWidget()
        js = """
        (function() {
            var blocks = document.querySelectorAll('pre code, code');
            for (var i = blocks.length - 1; i >= 0; i--) {
                var t = blocks[i].innerText.trim();
                if (t.startsWith('[') && t.includes('"pergunta"')) return t;
            }
            return null;
        })()
        """
        def handle_res(text):
            if text: self.json_input.setPlainText(text)
            else: showWarning("JSON não encontrado na tela.")
        browser_view.page().runJavaScript(js, handle_res)

    def create_premium_cards(self):
        check_audio = self.chk_audio_ia.isChecked()
        if check_audio:
            if not ensure_deps(check_audio=True): return

        json_text = self.json_input.toPlainText().strip()
        try:
            qa_list = json.loads(json_text)
            model = get_premium_model()
            deck_id = mw.col.decks.id(self.deck_combo.currentText())
            
            count = 0
            for item in qa_list:
                note = mw.col.new_note(model)
                note["Frente"] = item.get("pergunta", "")
                resposta = item.get("resposta", "")
                note["Verso"] = resposta
                
                note["Concurso"] = "SEFAZ BA"
                note["Cargo"] = "AGENTE DE TRIBUTOS"
                note["Objetivo"] = "25.000 líquido / mês"
                
                if self.chk_audio_ia.isChecked():
                    QApplication.processEvents()
                    note["Audio"] = generate_audio_tag(resposta)
                
                mw.col.add_note(note, deck_id)
                count += 1
                
            mw.reset()
            showInfo(f"✅ {count} Cards Premium criados com sucesso!")
            self.json_input.clear()
            
        except Exception as e:
            showWarning(f"Erro ao ler JSON: {e}")

_suite_instance = None
def open_suite():
    global _suite_instance
    if _suite_instance is None or not _suite_instance.isVisible():
        _suite_instance = UltimateSuiteDialog(mw)
    _suite_instance.show()
    _suite_instance.raise_()

action = QAction("🚀 Anki Ultimate Suite (PDF + IA + Áudio)", mw)
action.triggered.connect(open_suite)
mw.form.menuTools.addAction(action)

gui_hooks.editor_will_process_mime.append(on_editor_paste)