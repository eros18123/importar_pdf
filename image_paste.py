# -*- coding: utf-8 -*-
import os
import re
import subprocess
import sys
import time
import urllib.request
import tempfile
import shutil
from collections import defaultdict
from aqt import mw
from aqt.qt import *
from aqt.utils import showWarning


class TesseractDownloader(QThread):
    progress = pyqtSignal(int, str)
    finished_download = pyqtSignal(bool, str)

    def __init__(self, target_dir):
        super().__init__()
        self.target_dir = target_dir
        self.url = "https://github.com/tesseract-ocr/tesseract/releases/download/5.5.0/tesseract-ocr-w64-setup-5.5.0.20241111.exe"

    def run(self):
        try:
            exe_path = os.path.join(tempfile.gettempdir(), "tesseract_installer.exe")

            def reporthook(blocknum, blocksize, totalsize):
                if totalsize > 0:
                    percent = int(blocknum * blocksize * 100 / totalsize)
                    self.progress.emit(percent, f"Baixando IA (Tesseract)... {percent}%")

            urllib.request.urlretrieve(self.url, exe_path, reporthook)
            self.progress.emit(100, "Instalando... (Aceite a permissão de Administrador)")

            if os.name == 'nt':
                args = f"'/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/DIR=\"{self.target_dir}\"'"
                ps_cmd = f"Start-Process -FilePath '{exe_path}' -ArgumentList {args} -Verb RunAs -Wait"
                subprocess.run(["powershell", "-NoProfile", "-Command", ps_cmd], check=True)
            else:
                cmd = [exe_path, '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', f'/DIR={self.target_dir}']
                subprocess.run(cmd, check=True)

            try:
                os.remove(exe_path)
            except Exception:
                pass

            self.finished_download.emit(True, "Instalado com sucesso!")
        except Exception as e:
            self.finished_download.emit(False, str(e))


def get_tesseract_path():
    if os.name != 'nt':
        return shutil.which('tesseract') or 'tesseract'

    in_path = shutil.which('tesseract')
    if in_path:
        return in_path

    sys_paths = [
        r'C:\Program Files\Tesseract-OCR\tesseract.exe',
        r'C:\Program Files (x86)\Tesseract-OCR\tesseract.exe',
        os.path.join(os.environ.get('LOCALAPPDATA', ''), 'Programs', 'Tesseract-OCR', 'tesseract.exe')
    ]
    for p in sys_paths:
        if os.path.exists(p):
            return p

    addon_tess = os.path.join(os.path.dirname(__file__), "tesseract", "tesseract.exe")
    if os.path.exists(addon_tess):
        return addon_tess

    return None


def download_tesseract_sync(parent_widget):
    dialog = QProgressDialog("Preparando download...", "Cancelar", 0, 100, parent_widget)
    dialog.setWindowTitle("Instalação Automática")
    dialog.setWindowModality(Qt.WindowModality.WindowModal)
    dialog.setAutoClose(True)

    target_dir = os.path.join(os.path.dirname(__file__), "tesseract")
    downloader = TesseractDownloader(target_dir)
    success = [False]

    def on_progress(val, text):
        dialog.setValue(val)
        dialog.setLabelText(text)

    def on_finished(ok, msg):
        success[0] = ok
        if not ok:
            showWarning(f"Erro ao baixar Tesseract: {msg}")
        dialog.accept()

    downloader.progress.connect(on_progress)
    downloader.finished_download.connect(on_finished)
    dialog.canceled.connect(downloader.terminate)
    downloader.start()
    dialog.exec()
    return success[0]


def _build_line_mask(img_cv, text_boxes):
    import cv2
    import numpy as np

    gray = cv2.cvtColor(img_cv, cv2.COLOR_BGR2GRAY)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (11, 11))
    blackhat = cv2.morphologyEx(gray, cv2.MORPH_BLACKHAT, kernel)
    _, line_mask = cv2.threshold(blackhat, 25, 255, cv2.THRESH_BINARY)

    for box in text_boxes:
        pad = 12
        x0 = max(0, box['x0'] - pad)
        y0 = max(0, box['y0'] - pad)
        x1 = min(img_cv.shape[1], box['x1'] + pad)
        y1 = min(img_cv.shape[0], box['y1'] + pad)
        cv2.rectangle(line_mask, (x0, y0), (x1, y1), 0, -1)

    return line_mask

def _has_line_near_label(label, line_mask, search_margin=35):
    import cv2
    import numpy as np

    x0 = max(0, label['x0'] - search_margin)
    y0 = max(0, label['y0'] - search_margin)
    x1 = min(line_mask.shape[1], label['x1'] + search_margin)
    y1 = min(line_mask.shape[0], label['y1'] + search_margin)
    
    region = line_mask[y0:y1, x0:x1]
    
    lines = cv2.HoughLinesP(
        region, 
        rho=1, 
        theta=np.pi/180, 
        threshold=12, 
        minLineLength=12, 
        maxLineGap=5
    )
    return lines is not None and len(lines) > 0

def _detect_labels(img_cv, tess_path):
    import cv2
    import numpy as np
    import pytesseract

    if tess_path and os.name == 'nt':
        pytesseract.pytesseract.tesseract_cmd = tess_path

    img_h, img_w = img_cv.shape[:2]
    
    scale = 2.0
    img_up = cv2.resize(img_cv, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    gray = cv2.cvtColor(img_up, cv2.COLOR_BGR2GRAY)
    
    blurred = cv2.GaussianBlur(gray, (3, 3), 0)
    _, thresh = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    VOWELS = re.compile(r'[AEIOUaeiouÀ-Úà-ú]')

    raw_words = []
    for psm in ('11', '12'):
        cfg = f'--oem 3 --psm {psm}'
        d = pytesseract.image_to_data(
            thresh,
            output_type=pytesseract.Output.DICT,
            config=cfg,
            lang='por+eng'
        )
        for i in range(len(d['text'])):
            conf = int(d['conf'][i])
            text = d['text'][i].strip()

            if conf < 45 or not text:
                continue

            letters = re.sub(r'[^A-Za-zÀ-ÿ]', '', text)
            if len(letters) < 3 or not VOWELS.search(letters):
                continue

            x = int(d['left'][i] / scale)
            y = int(d['top'][i] / scale)
            w = int(d['width'][i] / scale)
            h = int(d['height'][i] / scale)

            if h < 10 or h > 60 or w < 15:
                continue

            raw_words.append({
                'text': text,
                'x0': x, 'y0': y, 'x1': x + w, 'y1': y + h
            })

    if not raw_words:
        return []

    seen = set()
    deduped = []
    for w in raw_words:
        matched = False
        for s in seen:
            if abs(w['x0'] - s[0]) < 10 and abs(w['y0'] - s[1]) < 10 and w['text'].lower() == s[2]:
                matched = True
                break
        if not matched:
            seen.add((w['x0'], w['y0'], w['text'].lower()))
            deduped.append(w)
            
    raw_words = deduped
    all_raw_boxes = raw_words[:]

    def boxes_are_close(b1, b2):
        x_overlap = min(b1['x1'], b2['x1']) - max(b1['x0'], b2['x0'])
        y_overlap = min(b1['y1'], b2['y1']) - max(b1['y0'], b2['y0'])
        
        x_dist = -x_overlap if x_overlap < 0 else 0
        y_dist = -y_overlap if y_overlap < 0 else 0

        if y_dist < 15 and x_dist < 40:
            return True
        if y_dist < 30 and x_overlap > -20:
            return True
        return False

    labels = raw_words[:]
    merged = True
    while merged:
        merged = False
        for i in range(len(labels)):
            for j in range(i + 1, len(labels)):
                if boxes_are_close(labels[i], labels[j]):
                    l1, l2 = labels[i], labels[j]
                    
                    if l1['y0'] + 10 < l2['y0']:
                        ntext = l1['text'] + ' ' + l2['text']
                    elif l2['y0'] + 10 < l1['y0']:
                        ntext = l2['text'] + ' ' + l1['text']
                    elif l1['x0'] <= l2['x0']:
                        ntext = l1['text'] + ' ' + l2['text']
                    else:
                        ntext = l2['text'] + ' ' + l1['text']

                    labels[i] = {
                        'x0': min(l1['x0'], l2['x0']),
                        'y0': min(l1['y0'], l2['y0']),
                        'x1': max(l1['x1'], l2['x1']),
                        'y1': max(l1['y1'], l2['y1']),
                        'text': ntext,
                    }
                    labels.pop(j)
                    merged = True
                    break
            if merged:
                break

    labels = [
        lbl for lbl in labels
        if (lbl['y1'] - lbl['y0']) < 120 and (lbl['x1'] - lbl['x0']) < 400 and len(lbl['text'].split()) <= 6
    ]

    line_mask = _build_line_mask(img_cv, all_raw_boxes)

    labels_with_lines = []
    for label in labels:
        if _has_line_near_label(label, line_mask):
            labels_with_lines.append(label)

    return labels_with_lines


class ImagePasteWorker(QThread):
    finished_paste = pyqtSignal(bool, int, str)
    progress = pyqtSignal(int, str)

    def __init__(self, img_data, deck_id, tess_path):
        super().__init__()
        self.img_data = img_data
        self.deck_id = deck_id
        self.tess_path = tess_path

    def run(self):
        try:
            import cv2
            import numpy as np
            from PIL import Image, ImageDraw
            import io as _io
            from .models import get_or_create_image_occlusion_model

            self.progress.emit(10, "Lendo imagem com IA...")

            nparr = np.frombuffer(self.img_data, np.uint8)
            img_cv = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            if img_cv is None:
                self.finished_paste.emit(False, 0, "Falha ao decodificar a imagem.")
                return

            labels_found = _detect_labels(img_cv, self.tess_path)

            if not labels_found:
                self.finished_paste.emit(
                    False, 0,
                    "Nenhum rótulo com seta/linha encontrado na imagem."
                )
                return

            pad = 6
            base_img = Image.fromarray(cv2.cvtColor(img_cv, cv2.COLOR_BGR2RGB))
            model = get_or_create_image_occlusion_model()
            cards_added = 0
            timestamp = int(time.time() * 1000)
            total_labels = len(labels_found)

            for target_idx, label in enumerate(labels_found):
                pct = int(10 + (target_idx / total_labels) * 90)
                self.progress.emit(pct, f"Criando oclusão {target_idx + 1} de {total_labels}...")

                rect = (
                    max(0, label['x0'] - pad),
                    max(0, label['y0'] - pad),
                    label['x1'] + pad,
                    label['y1'] + pad,
                )
                rects_all = [
                    (
                        max(0, lb['x0'] - pad),
                        max(0, lb['y0'] - pad),
                        lb['x1'] + pad,
                        lb['y1'] + pad,
                    )
                    for lb in labels_found
                ]

                slug = f"paste_occl_{timestamp}_l{target_idx}"

                img_q = base_img.copy()
                draw_q = ImageDraw.Draw(img_q)
                for i, r in enumerate(rects_all):
                    if i == target_idx:
                        draw_q.rectangle(r, fill=(231, 76, 60))
                    else:
                        draw_q.rectangle(r, fill=(70, 130, 180))
                buf_q = _io.BytesIO()
                img_q.save(buf_q, format="PNG")
                fn_q = slug + "_q.png"
                mw.col.media.write_data(fn_q, buf_q.getvalue())

                img_a = base_img.copy()
                draw_a = ImageDraw.Draw(img_a)
                for i, r in enumerate(rects_all):
                    if i == target_idx:
                        draw_a.rectangle(r, outline=(39, 174, 96), width=3)
                    else:
                        draw_a.rectangle(r, fill=(70, 130, 180))
                buf_a = _io.BytesIO()
                img_a.save(buf_a, format="PNG")
                fn_a = slug + "_a.png"
                mw.col.media.write_data(fn_a, buf_a.getvalue())

                note = mw.col.new_note(model)
                note["Imagem"] = f'<img src="{fn_q}">'
                note["ImagemResposta"] = f'<img src="{fn_a}">'
                note["Gabarito"] = label['text']
                mw.col.add_note(note, self.deck_id)
                cards_added += 1

            self.progress.emit(100, "Concluído!")
            self.finished_paste.emit(True, cards_added, "Cards gerados com sucesso!")

        except Exception as e:
            self.finished_paste.emit(False, 0, f"Erro no processamento da imagem: {str(e)}")


def _is_image_occlusion_note_type(editor):
    try:
        if editor.note and editor.note.note_type():
            return editor.note.note_type()['name'] == "Image Occlusion (PDF Import)"
    except Exception:
        pass
    try:
        current_model = mw.col.models.current()
        if current_model:
            return current_model['name'] == "Image Occlusion (PDF Import)"
    except Exception:
        pass
    return False


def _start_image_processing(img_bytes, deck_id, editor, tess_path):
    progress = QProgressDialog("Iniciando IA...", None, 0, 100, editor.widget)
    progress.setWindowTitle("Processando Imagem")
    progress.setWindowModality(Qt.WindowModality.WindowModal)
    progress.setAutoClose(True)
    progress.show()

    worker = ImagePasteWorker(img_bytes, deck_id, tess_path)

    def on_progress(val, text):
        progress.setValue(val)
        progress.setLabelText(text)

    def on_finished(success, count, msg):
        progress.close()
        if success and count > 0:
            mw.reset()
        else:
            showWarning(
                f"Não foi possível criar cards automaticamente.\n"
                f"Motivo: {msg}\n\n"
                f"A imagem não foi colada."
            )

    worker.progress.connect(on_progress)
    worker.finished_paste.connect(on_finished)
    editor._image_worker = worker
    worker.start()


def on_editor_paste(mime, editor_web_view, internal, extended, drop_event):
    if not mime.hasImage():
        return mime

    editor = editor_web_view.editor

    if not _is_image_occlusion_note_type(editor):
        return mime

    from .__init__ import ensure_cv_deps
    if not ensure_cv_deps():
        return mime

    tess_path = get_tesseract_path()
    if not tess_path and os.name == 'nt':
        msg_dl = QMessageBox(editor.widget)
        msg_dl.setWindowTitle("Motor de IA Ausente")
        msg_dl.setText(
            "O motor de leitura de imagens (Tesseract) não foi encontrado.\n"
            "Deseja baixar e instalar automaticamente agora? (~40MB)"
        )
        msg_dl.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if msg_dl.exec() == QMessageBox.StandardButton.Yes:
            if download_tesseract_sync(editor.widget):
                tess_path = get_tesseract_path()
            else:
                return mime
        else:
            return mime
    elif not tess_path:
        showWarning("Por favor, instale o Tesseract OCR no seu sistema.")
        return mime

    qimage = mime.imageData()
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.ReadWrite)
    qimage.save(buffer, "PNG")
    img_bytes = buffer.data().data()

    deck_id = None
    if editor.card:
        deck_id = editor.card.did
    else:
        try:
            deck_id = editor.parentWindow.deck_chooser.selected_deck_id
        except AttributeError:
            try:
                deck_id = editor.parentWindow.deckChooser.selectedId()
            except AttributeError:
                pass

    if not deck_id:
        try:
            deck_id = mw.col.decks.get_current_id()
        except AttributeError:
            deck_id = mw.col.decks.current()['id']

    editor.saveNow(lambda: _start_image_processing(img_bytes, deck_id, editor, tess_path))

    empty_mime = QMimeData()
    return empty_mime