import re
from aqt import mw

def normalize_text(s):
    return re.sub(r'\W+', '', s).lower()

def _parse_sentence_to_qa(sentence):
    s = sentence.strip()
    if not s: return None, None

    if re.match(r'^\d+(\.\d+)+\s', s): return None, None
    if re.search(r'(?i)\b(capítulo|figura|tabela|gráfico|quadro|seção|página)\b', s): return None, None
    if re.search(r'(?i)\b(este material|neste livro|neste capítulo|você estudou|você aprenderá|vamos estudar|estudaremos)\b', s): return None, None
    if re.match(r'(?i)^(observe|note que|veja|verificamos|podemos verificar|podemos observar)\b', s): return None, None

    clean_s = re.sub(r'[.!?]+$', '', s)

    match = re.search(r'(?i)^(se\s+.*?(?:chamamos|denominamos|é denominado|são chamados|são denominados)\s+(?:de|por|como))\s+(.+)$', clean_s)
    if match:
        front = match.group(1).strip() + ":"
        back = match.group(2).strip()
        back = back.split(';')[0].strip()
        return front, back

    match = re.search(r'^(.*?)\s*\(([^)]+)\)$', clean_s)
    if match:
        front = match.group(1).strip()
        back = match.group(2).strip()
        if len(back) > 3 and not re.search(r'(?i)(figura|tabela|página|exemplo|veja)', back):
            return front, back

    match = re.search(r'(?i)^(.*? deriva d[oa])\s+(.+)$', clean_s)
    if match:
        return match.group(1).strip() + "?", match.group(2).strip()

    match = re.search(r'(?i)^(.*?)\s+significa\s+(.+)$', clean_s)
    if match:
        subject = match.group(1).strip()
        subject = re.sub(r'(?i)^(o termo|a palavra)\s+[""\']?(.*?)[""\']?', r'\2', subject)
        return f"O que significa {subject}?", match.group(2).strip()

    match = re.search(r'(?i)^(.*? (?:ocorreu em|foi realizada em|foi realizado em))\s+(.+)$', clean_s)
    if match:
        return match.group(1).strip() + "...", match.group(2).strip()

    match = re.search(r'(?i)^(.*? (?:está constituído|constituído|constituída|formado|formada|fazem parte)\s+(?:pelo|pela|pelos|pelas|do|da|dos|das|por))\s+(.+)$', clean_s)
    if match:
        return match.group(1).strip(), match.group(2).strip()

    match = re.search(r'(?i)^(.*? (?:é denominado|é denominadada|é chamado|é chamada|são denominados|são chamados)\s+(?:de|por|como))\s+(.+)$', clean_s)
    if match:
        return match.group(1).strip(), match.group(2).strip()

    match = re.search(r'(?i)^([^,]+?\s+são)\s+(.+)$', clean_s)
    if match:
        return match.group(1).strip(), match.group(2).strip()

    match = re.search(r'(?i)^([^,]{2,50}?)\s+(é a|é o|é um|é uma|são)\s+(.+)$', clean_s)
    if match:
        subject = match.group(1).strip()
        verb = match.group(2).strip()
        rest = match.group(3).strip()
        
        if not re.search(r'(?i)\b(que|como|para|se|quando)\b', subject):
            if verb.lower() == "são":
                return f"O que são {subject}?", rest
            else:
                return f"O que é {subject}?", f"{verb} {rest}"

    if '?' in s:
        parts = s.split('?')
        front = parts[0].strip() + "?"
        back = parts[1].strip() if len(parts) > 1 else ""
        if back and '?' not in back:
            return front, back

    if ':' in s:
        parts = s.split(':', 1)
        front = parts[0].strip() + ":"
        back = parts[1].strip()
        if len(front.split()) > 1 and len(front.split()) < 20 and len(back) > 2:
            if '?' not in back:
                return front, back

    return None, None

def process_mcq(worker, doc, deck_id, deck_name, start, end, model):
    mw.col.models.set_current(model)
    
    safe_deck_name = re.sub(r'[^A-Za-z0-9_]', '', deck_name.replace(' ', '_'))
    cards_added = 0
    
    questions = []
    current_q = {k: "" for k in ["enunciado", "a", "b", "c", "d", "e", "gabarito"]}
    state = "enunciado"
    
    for page_num in range(start, end + 1):
        if worker.is_cancelled: return
        worker._emit_progress(page_num, start, f"Processando questões — pág. {page_num + 1}")
        
        page = doc[page_num]
        raw_blocks = page.get_text("dict").get("blocks", [])
        page_width = page.rect.width

        mid = page_width / 2
        col_left  = sorted([b for b in raw_blocks if b["bbox"][0] < mid],  key=lambda b: b["bbox"][1])
        col_right = sorted([b for b in raw_blocks if b["bbox"][0] >= mid], key=lambda b: b["bbox"][1])

        def has_question_content(blocks):
            for b in blocks:
                if b["type"] != 0: continue
                t = " ".join(span.get("text", "") for line in b.get("lines", []) for span in line.get("spans", []))
                if re.search(r"(?i)(gabarito|a\)|b\)|c\))", t):
                    return True
            return False

        if col_left and col_right and has_question_content(col_left) and has_question_content(col_right):
            blocks_ordered = col_left + col_right
        else:
            blocks_ordered = sorted(raw_blocks, key=lambda b: b["bbox"][1])

        for i, b in enumerate(blocks_ordered):
            if b["type"] == 1:
                if state == 'gabarito':
                    if current_q["enunciado"].strip() and current_q["gabarito"].strip():
                        questions.append(current_q)
                    current_q = {k: "" for k in ["enunciado", "a", "b", "c", "d", "e", "gabarito"]}
                    state = "enunciado"
                    
                img_ext = b.get("ext", "png")
                img_filename = f"import_{safe_deck_name}_p{page_num}_{i}.{img_ext}"
                mw.col.media.write_data(img_filename, b.get("image"))
                current_q[state] += f'<br><img src="{img_filename}"><br>'
                continue
                
            if b["type"] == 0:
                text = ""
                for line in b.get("lines", []):
                    line_text = ""
                    for span in line.get("spans", []):
                        line_text += span.get("text", "") + " "
                    text += line_text.strip() + " "

                text = re.sub(r'[ \t]+', ' ', text).strip()
                
                if not text: continue
                
                if state == 'gabarito':
                    if not re.match(r'(?i)^GABARITO:', text) and (text[0].isupper() or text[0].isdigit()):
                        if current_q["enunciado"].strip() and current_q["gabarito"].strip():
                            questions.append(current_q)
                        current_q = {k: "" for k in ["enunciado", "a", "b", "c", "d", "e", "gabarito"]}
                        state = "enunciado"
                        
                parts = re.split(r'(?i)(?:\s|^)(a\)|b\)|c\)|d\)|e\)|GABARITO:)(?=\s|$)', " " + text)
                
                if parts[0].strip():
                    current_q[state] += parts[0].strip() + " "
                    
                idx = 1
                while idx < len(parts):
                    marker = parts[idx].upper().strip()
                    content = parts[idx + 1].strip() if idx + 1 < len(parts) else ""
                    
                    if marker == 'A)' and state == 'enunciado': state = 'a'
                    elif marker == 'B)' and state == 'a': state = 'b'
                    elif marker == 'C)' and state == 'b': state = 'c'
                    elif marker == 'D)' and state == 'c': state = 'd'
                    elif marker == 'E)' and state == 'd': state = 'e'
                    elif marker == 'GABARITO:': state = 'gabarito'
                    else:
                        content = marker + " " + content
                        
                    if content:
                        current_q[state] += content + " "
                    idx += 2

    if current_q["enunciado"].strip() and current_q["gabarito"].strip():
        questions.append(current_q)
        
    for q in questions:
        enunciado_text = q["enunciado"].strip()
        titulo_match = re.match(
            r'^((?:.*?>\s*.*?)*(?:\|\s*)?ID:\s*\d+)\s+(.+)$',
            enunciado_text,
            re.DOTALL | re.IGNORECASE
        )
        if titulo_match:
            q["titulo"] = titulo_match.group(1).strip()
            q["enunciado"] = titulo_match.group(2).strip()
        else:
            q["titulo"] = ""
            q["enunciado"] = enunciado_text

        parsed_opts = [q["a"].strip(), q["b"].strip(), q["c"].strip(), q["d"].strip(), q["e"].strip()]
        parsed_opts = [opt for opt in parsed_opts if opt]
        
        gab_text = q["gabarito"].strip()
        correct_opt = ""
        other_opts = []
        
        norm_gab = normalize_text(gab_text)
        for opt in parsed_opts:
            norm_opt = normalize_text(opt)
            if norm_opt and len(norm_opt) > 5 and (norm_opt in norm_gab or norm_gab in norm_opt):
                correct_opt = opt
                break
        
        if correct_opt:
            other_opts = [opt for opt in parsed_opts if opt != correct_opt]
        else:
            if parsed_opts:
                correct_opt = parsed_opts[0]
                other_opts = parsed_opts[1:]

        q["a"] = correct_opt
        q["b"] = other_opts[0] if len(other_opts) > 0 else ""
        q["c"] = other_opts[1] if len(other_opts) > 1 else ""
        q["d"] = other_opts[2] if len(other_opts) > 2 else ""
        q["e"] = other_opts[3] if len(other_opts) > 3 else ""

        for k in ["titulo", "enunciado", "a", "b", "c", "d", "e", "gabarito"]:
            if k in q:
                q[k] = re.sub(r' +', ' ', q[k]).strip()
            
        note = mw.col.new_note(model)
        note["Titulo"] = q.get("titulo", "")
        note["Enunciado"] = q["enunciado"]
        note["A"] = q["a"]
        note["B"] = q["b"]
        note["C"] = q["c"]
        note["D"] = q["d"]
        note["E"] = q["e"]
        note["Gabarito"] = q["gabarito"]
        mw.col.add_note(note, deck_id)
        cards_added += 1

    page_range_info = f" (págs. {start + 1}–{end + 1})" if (start > 0 or end < len(doc) - 1) else ""
    if worker.is_cancelled:
        worker.finished_import.emit(False, "Importação cancelada pelo usuário.")
    else:
        worker.progress_update.emit(100, "Concluído!")
        worker.finished_import.emit(True, f"Importação concluída{page_range_info}!\n{cards_added} questões foram adicionadas ao baralho '{deck_name}'.")

def process_text(worker, doc, deck_id, deck_name, start, end, model):
    mw.col.models.set_current(model)
    field_names = mw.col.models.field_names(model)
    
    safe_deck_name = re.sub(r'[^A-Za-z0-9_]', '', deck_name.replace(' ', '_'))
    cards_added = 0
    elements = []
    
    for page_num in range(start, end + 1):
        if worker.is_cancelled: return
        worker._emit_progress(page_num, start, f"Lendo pág. {page_num + 1}")
        
        page = doc[page_num]
        blocks = page.get_text("dict").get("blocks", [])
        blocks.sort(key=lambda b: b["bbox"][1])
        
        for b in blocks:
            if b["type"] == 1:
                elements.append({'type': 'image', 'image': b.get("image"), 'ext': b.get("ext", "png"), 'page': page_num})
            elif b["type"] == 0:
                text = ""
                for line in b.get("lines", []):
                    for span in line.get("spans", []):
                        text += span.get("text", "") + " "
                text = re.sub(r'\s+', ' ', text).strip()
                if text:
                    elements.append({'type': 'text', 'text': text, 'used': False, 'page': page_num})

    worker.progress_update.emit(50, "Processando imagens e legendas...")
    for i, el in enumerate(elements):
        if el['type'] == 'image':
            back_texts = []
            for j in range(i - 1, max(-1, i - 3), -1):
                if elements[j]['type'] == 'text' and not elements[j]['used'] and elements[j]['page'] == el['page']:
                    if len(elements[j]['text']) < 200:
                        back_texts.insert(0, elements[j]['text'])
                        elements[j]['used'] = True
                    else: break
                else: break
                    
            for j in range(i + 1, min(len(elements), i + 2)):
                if elements[j]['type'] == 'text' and not elements[j]['used'] and elements[j]['page'] == el['page']:
                    if len(elements[j]['text']) < 200:
                        back_texts.append(elements[j]['text'])
                        elements[j]['used'] = True
                    else: break
                else: break
            
            valid_back_texts = []
            for t in back_texts:
                if re.match(r'^\d+$', t.strip()): continue
                if re.match(r'(?i)^capítulo\s*\d+$', t.strip()): continue
                if re.search(r'\.{3,}', t.strip()): continue
                valid_back_texts.append(t)
            
            if not valid_back_texts:
                continue
                    
            back_html = "<br>".join(valid_back_texts)
            img_filename = f"import_{safe_deck_name}_p{el['page']}_{i}.{el['ext']}"
            mw.col.media.write_data(img_filename, el['image'])
            front_html = f'<img src="{img_filename}">'
            
            note = mw.col.new_note(model)
            note[field_names[0]] = front_html
            note[field_names[1]] = back_html
            mw.col.add_note(note, deck_id)
            cards_added += 1

    worker.progress_update.emit(70, "Analisando e dividindo frases...")
    
    all_text_blocks = [el['text'] for el in elements if el['type'] == 'text' and not el['used']]
    
    filtered_blocks = []
    for block_text in all_text_blocks:
        if not block_text: continue
        if re.match(r'^\d+$', block_text): continue
        if re.match(r'(?i)^capítulo\s*\d+$', block_text): continue
        if re.match(r'(?i)^figura\s*\d+', block_text): continue
        if re.match(r'(?i)^\d+\s+anatomia humana$', block_text): continue
        if re.match(r'(?i)^anatomia humana\s*\d+$', block_text): continue
        if re.match(r'(?i)^sumário$', block_text): continue
        if re.match(r'(?i)^referências bibliográficas$', block_text): continue
        if re.match(r'^\d+(\.\d+)+\s*$', block_text): continue
        if re.search(r'\.{3,}', block_text): continue
        filtered_blocks.append(block_text)

    joined_text = " ".join(filtered_blocks)
    joined_text = re.sub(r'-\s+', '', joined_text)
    joined_text = re.sub(r'\b(\d+)\.\s+', r'\1_DOT_ ', joined_text)
    
    raw_sentences = re.split(r'(?<=[.!?])\s+', joined_text)

    sentences = []
    for s in raw_sentences:
        s = s.replace('_DOT_ ', '. ').strip()
        if len(s) > 10:
            sentences.append(s)

    worker.progress_update.emit(90, "Gerando cards no Anki...")
    
    for s in sentences:
        front, back = _parse_sentence_to_qa(s)
        
        if front and back:
            if len(front) > 250 or len(back) > 300: continue
            if len(re.findall(r'[a-zA-Zà-ÿÀ-Ÿ]', front)) < 3: continue
            if len(re.findall(r'[a-zA-Zà-ÿÀ-Ÿ]', back)) < 3: continue
            if '?' in back: continue

            note = mw.col.new_note(model)
            note[field_names[0]] = front
            note[field_names[1]] = back
            mw.col.add_note(note, deck_id)
            cards_added += 1

    page_range_info = f" (págs. {start + 1}–{end + 1})" if (start > 0 or end < len(doc) - 1) else ""
    if worker.is_cancelled:
        worker.finished_import.emit(False, "Importação cancelada pelo usuário.")
    else:
        worker.progress_update.emit(100, "Concluído!")
        worker.finished_import.emit(True, f"Importação concluída{page_range_info}!\n{cards_added} cards foram adicionados ao baralho '{deck_name}'.")