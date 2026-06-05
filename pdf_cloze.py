import re
from aqt import mw

STOPWORDS = {
    "para", "pelo", "pela", "pelos", "pelas", "numa", "nela", "nele", "neles", "nelas",
    "desse", "dessa", "deste", "desta", "disto", "disso", "daquilo", "daquele", "daquela",
    "entre", "sobre", "perante", "contra", "desde", "após", "como", "porém", "contudo",
    "todavia", "entretanto", "portanto", "logo", "porque", "pois", "embora", "quando",
    "enquanto", "conforme", "segundo", "consoante", "você", "vocês", "eles", "elas",
    "nosso", "nossa", "vosso", "vossa", "este", "esta", "esse", "essa", "aquele", "aquela",
    "qual", "quais", "quanto", "quantos", "quem", "cujo", "cuja", "tudo", "nada", "algo",
    "alguém", "ninguém", "outrem", "cada", "nenhum", "nenhuma", "muito", "pouco", "bastante",
    "menos", "mais", "aqui", "acolá", "abaixo", "acima", "dentro", "fora", "longe", "perto",
    "hoje", "amanhã", "ontem", "cedo", "tarde", "agora", "depois", "antes", "nunca", "jamais",
    "sempre", "quase", "decerto", "assim", "melhor", "pior", "onde", "aonde", "donde",
    "mesmo", "mesma", "mesmos", "mesmas", "qualquer", "quaisquer", "outra", "outro", "outras", "outros",
    "seja", "sejam", "fosse", "fossem", "sendo", "tendo", "estando", "haver", "havia", "houve",
    "pode", "podem", "deve", "devem", "temos", "vamos", "suas", "seus", "teus", "tuas",
    "também", "ainda", "então", "além", "apenas", "somente", "logo", "até", "nem",
    "isso", "isto", "aquilo", "esteja", "estejam", "seja", "sejam", "seus", "suas",
    "qual", "quais", "puxa", "nossa", "credo", "oxalá", "tomara", "quiçá", "aliás",
    "ante", "após", "comigo", "contigo", "consigo", "conosco", "convosco", "aqueles", "aquelas"
}

def process_cloze(worker, doc, deck_id, deck_name, start, end, model):
    mw.col.models.set_current(model)
    field_names = mw.col.models.field_names(model)
    
    cards_added = 0
    text_content = ""
    
    for page_num in range(start, end + 1):
        if worker.is_cancelled: return
        worker._emit_progress(page_num, start, f"Lendo pág. {page_num + 1}")
        
        page = doc[page_num]
        blocks = page.get_text("dict").get("blocks", [])
        blocks.sort(key=lambda b: b["bbox"][1])
        
        for b in blocks:
            if b["type"] == 0:
                block_text = ""
                for line in b.get("lines", []):
                    for span in line.get("spans", []):
                        block_text += span.get("text", "") + " "
                block_text = re.sub(r'\s+', ' ', block_text).strip()
                
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
                
                text_content += block_text + " "

    worker.progress_update.emit(70, "Analisando e dividindo frases...")
    
    text_content = re.sub(r'-\s+', '', text_content)
    text_content = re.sub(r'\b(\d+)\.\s+', r'\1_DOT_ ', text_content)
    
    raw_sentences = re.split(r'(?<=[.!?])\s+', text_content)

    worker.progress_update.emit(90, "Gerando cards no Anki...")
    
    for s in raw_sentences:
        s = s.replace('_DOT_ ', '. ').strip()
        if len(s) < 15 or len(s) > 400: continue
        
        if re.search(r'(?i)\b(capítulo|figura|tabela|gráfico|quadro|seção|página)\b', s): continue
        if re.search(r'(?i)\b(este material|neste livro|neste capítulo|você estudou|você aprenderá|vamos estudar|estudaremos)\b', s): continue
        if re.match(r'(?i)^(observe|note que|veja|verificamos|podemos verificar|podemos observar)\b', s): continue

        words = re.findall(r'\b[a-zA-Zà-ÿÀ-Ÿ]+\b', s)
        if len(words) < 3: continue

        if len(words) <= 5: max_c = 1
        elif len(words) <= 7: max_c = 1
        elif len(words) <= 10: max_c = 2
        else: max_c = max(3, len(words) // 5)

        candidates = []
        for w in words:
            w_lower = w.lower()
            if len(w) >= 4 and w_lower not in STOPWORDS and not w_lower.endswith("mente"):
                candidates.append(w)

        if not candidates: continue

        candidates = list(set(candidates))
        candidates.sort(key=len, reverse=True)
        selected = candidates[:max_c]

        clozed_s = s
        for word in selected:
            clozed_s = re.sub(rf'\b({word})\b', r'{{c1::\1}}', clozed_s, flags=re.IGNORECASE)

        if '{{c1::' in clozed_s:
            note = mw.col.new_note(model)
            note[field_names[0]] = clozed_s
            mw.col.add_note(note, deck_id)
            cards_added += 1

    page_range_info = f" (págs. {start + 1}–{end + 1})" if (start > 0 or end < len(doc) - 1) else ""
    if worker.is_cancelled:
        worker.finished_import.emit(False, "Importação cancelada pelo usuário.")
    else:
        worker.progress_update.emit(100, "Concluído!")
        worker.finished_import.emit(True, f"Importação concluída{page_range_info}!\n{cards_added} cards foram adicionados ao baralho '{deck_name}'.")