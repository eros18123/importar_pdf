# -*- coding: utf-8 -*-
import re
import time
from aqt import mw
import os


def _build_line_mask(img_cv, text_boxes):
    """
    Usa o filtro BlackHat para extrair APENAS linhas finas, 
    ignorando texturas grossas (como o desenho da orelha) e 
    detectando até mesmo linhas cinza claro.
    """
    import cv2
    import numpy as np

    gray = cv2.cvtColor(img_cv, cv2.COLOR_BGR2GRAY)
    
    # O BlackHat extrai estruturas escuras e finas de um fundo mais claro
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (11, 11))
    blackhat = cv2.morphologyEx(gray, cv2.MORPH_BLACKHAT, kernel)
    
    # Transforma as linhas encontradas em branco puro
    _, line_mask = cv2.threshold(blackhat, 25, 255, cv2.THRESH_BINARY)

    # Apaga as caixas de texto com margem grande para que as letras não sejam lidas como linhas
    for box in text_boxes:
        pad = 12
        x0 = max(0, box['x0'] - pad)
        y0 = max(0, box['y0'] - pad)
        x1 = min(img_cv.shape[1], box['x1'] + pad)
        y1 = min(img_cv.shape[0], box['y1'] + pad)
        cv2.rectangle(line_mask, (x0, y0), (x1, y1), 0, -1)

    return line_mask

def _has_line_near_label(label, line_mask, search_margin=35):
    """
    Verifica se existe um segmento de reta real apontando para o texto.
    """
    import cv2
    import numpy as np

    x0 = max(0, label['x0'] - search_margin)
    y0 = max(0, label['y0'] - search_margin)
    x1 = min(line_mask.shape[1], label['x1'] + search_margin)
    y1 = min(line_mask.shape[0], label['y1'] + search_margin)
    
    region = line_mask[y0:y1, x0:x1]
    
    # Procura por retas de pelo menos 12 pixels de comprimento
    lines = cv2.HoughLinesP(
        region, 
        rho=1, 
        theta=np.pi/180, 
        threshold=12, 
        minLineLength=12, 
        maxLineGap=5
    )
    return lines is not None and len(lines) > 0

def _detect_all_labels(img_cv, tess_path):
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

            # CONFIANÇA ALTA: Mata as alucinações nas texturas da imagem
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
                'x0': x, 'y0': y,
                'x1': x + w, 'y1': y + h
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

        # Mesma linha
        if y_dist < 15 and x_dist < 40:
            return True
        # Linhas adjacentes (junta parágrafos)
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
                        'text': ntext.strip(),
                        'x0': min(l1['x0'], l2['x0']),
                        'y0': min(l1['y0'], l2['y0']),
                        'x1': max(l1['x1'], l2['x1']),
                        'y1': max(l1['y1'], l2['y1'])
                    }
                    labels.pop(j)
                    merged = True
                    break
            if merged:
                break

    # FILTRO DE PARÁGRAFOS: Se tiver mais de 6 palavras, é texto normal, NÃO é rótulo de anatomia.
    labels = [
        lbl for lbl in labels
        if (lbl['y1'] - lbl['y0']) < 120 and (lbl['x1'] - lbl['x0']) < 400 and len(lbl['text'].split()) <= 6
    ]

    line_mask = _build_line_mask(img_cv, all_raw_boxes)

    valid_labels = [
        lbl for lbl in labels
        if _has_line_near_label(lbl, line_mask)
    ]

    return valid_labels


def process_anatomy(worker, doc, deck_id, deck_name, start, end, model):
    import fitz
    from PIL import Image, ImageDraw
    import io as _io
    import numpy as np
    import cv2
    import pytesseract
    from .image_paste import get_tesseract_path

    tess_path = get_tesseract_path()
    if tess_path and os.name == 'nt':
        pytesseract.pytesseract.tesseract_cmd = tess_path

    safe_deck_name = re.sub(r'[^A-Za-z0-9_]', '', deck_name.replace(' ', '_'))
    cards_added = 0
    SCALE = 2.5

    for page_num in range(start, end + 1):
        if worker.is_cancelled:
            break
        worker._emit_progress(page_num, start, f"Lendo Imagem com IA — pág. {page_num + 1}")

        page = doc[page_num]

        mat = fitz.Matrix(SCALE, SCALE)
        pix = page.get_pixmap(matrix=mat)

        if pix.n == 4:
            img_np = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.h, pix.w, 4)
            img_cv = cv2.cvtColor(img_np, cv2.COLOR_RGBA2BGR)
        else:
            img_np = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.h, pix.w, 3)
            img_cv = cv2.cvtColor(img_np, cv2.COLOR_RGB2BGR)

        valid_labels = _detect_all_labels(img_cv, tess_path)

        if len(valid_labels) < 2:
            continue

        base_img_pil = Image.fromarray(cv2.cvtColor(img_cv, cv2.COLOR_BGR2RGB))
        total_labels = len(valid_labels)

        for target_idx, target_label in enumerate(valid_labels):
            if worker.is_cancelled:
                break
            
            worker._emit_progress(page_num, start, f"Pág {page_num + 1}: Criando oclusão {target_idx + 1} de {total_labels}...")

            timestamp = int(time.time() * 1000)
            slug = f"anat_{safe_deck_name}_p{page_num+1}_l{target_idx}_{timestamp}"

            PAD = 4

            img_q = base_img_pil.copy()
            draw_q = ImageDraw.Draw(img_q)
            for i, lbl in enumerate(valid_labels):
                rx0, ry0 = lbl['x0'] - PAD, lbl['y0'] - PAD
                rx1, ry1 = lbl['x1'] + PAD, lbl['y1'] + PAD
                color = (231, 76, 60) if i == target_idx else (70, 130, 180)
                draw_q.rectangle([rx0, ry0, rx1, ry1], fill=color)

            buf_q = _io.BytesIO()
            img_q.save(buf_q, format="PNG")
            fn_q = slug + "_q.png"
            mw.col.media.write_data(fn_q, buf_q.getvalue())

            img_a = base_img_pil.copy()
            draw_a = ImageDraw.Draw(img_a)
            for i, lbl in enumerate(valid_labels):
                rx0, ry0 = lbl['x0'] - PAD, lbl['y0'] - PAD
                rx1, ry1 = lbl['x1'] + PAD, lbl['y1'] + PAD
                if i == target_idx:
                    draw_a.rectangle([rx0, ry0, rx1, ry1], outline=(39, 174, 96), width=3)
                else:
                    draw_a.rectangle([rx0, ry0, rx1, ry1], fill=(70, 130, 180))

            buf_a = _io.BytesIO()
            img_a.save(buf_a, format="PNG")
            fn_a = slug + "_a.png"
            mw.col.media.write_data(fn_a, buf_a.getvalue())

            note = mw.col.new_note(model)
            note["Imagem"] = f'<img src="{fn_q}">'
            note["ImagemResposta"] = f'<img src="{fn_a}">'
            note["Gabarito"] = target_label['text']
            mw.col.add_note(note, deck_id)
            cards_added += 1

    if worker.is_cancelled:
        worker.finished_import.emit(False, "Importação cancelada.")
    else:
        worker.progress_update.emit(100, "Concluído!")
        worker.finished_import.emit(
            True,
            f"Importação concluída!\n{cards_added} cards de Anatomia adicionados ao baralho '{deck_name}'."
        )