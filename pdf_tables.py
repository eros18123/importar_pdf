import re
import time
from aqt import mw

def _is_content_table(extracted):
    if not extracted:
        return False
    header_idx = -1
    for i, row in enumerate(extracted):
        non_null = [c for c in row if c and str(c).strip()]
        if len(non_null) >= 2:
            header_idx = i
            break
    if header_idx == -1:
        return False
    first = extracted[header_idx][0] if extracted[header_idx][0] else ""
    if "Solução" in str(first):
        return False
    return True

def _find_all_tables(plumber_page):
    results = []
    covered = set()

    standard_objs = plumber_page.find_tables()
    standard_exts = plumber_page.extract_tables()
    
    for t_obj, t_ext in zip(standard_objs, standard_exts):
        if _is_content_table(t_ext):
            results.append((t_obj, t_ext))
            bx0, by0, bx1, by1 = t_obj.bbox
            covered.add((round(bx0), round(by0), round(bx1), round(by1)))

    h_lines = []
    v_lines = []
    
    for obj in plumber_page.rects + plumber_page.lines + plumber_page.curves:
        x0, y0, x1, y1 = obj.get('x0'), obj.get('top'), obj.get('x1'), obj.get('bottom')
        if x0 is None or y0 is None or x1 is None or y1 is None:
            continue
        w = x1 - x0
        h = y1 - y0
        if h < 3 and w > 10:
            h_lines.append((x0, y0, x1, y1))
        elif w < 3 and h > 5:
            v_lines.append((x0, y0, x1, y1))
        elif obj.get('fill') or obj.get('object_type') == 'rect':
            if w > 10 and h > 5:
                h_lines.append((x0, y0, x1, y0))
                h_lines.append((x0, y1, x1, y1))
                v_lines.append((x0, y0, x0, y1))
                v_lines.append((x1, y0, x1, y1))

    if not h_lines:
        return results

    h_ys = sorted(set(round(line[1], 1) for line in h_lines))
    groups = []
    current_group = [h_ys[0]]
    for y in h_ys[1:]:
        if y - current_group[-1] < 80:
            current_group.append(y)
        else:
            groups.append(current_group)
            current_group = [y]
    groups.append(current_group)

    for group_ys in groups:
        if len(group_ys) < 2:
            continue
        y_top = group_ys[0]
        y_bot = group_ys[-1]
        group_v_lines = [v for v in v_lines if v[1] <= y_bot + 5 and v[3] >= y_top - 5]
        if not group_v_lines:
            continue
        group_v_xs = sorted(set(round(v[0], 1) for v in group_v_lines))
        if len(group_v_xs) < 2:
            continue
        x_left = group_v_xs[0]
        x_right = group_v_xs[-1]
        margin = 5
        try:
            crop_bbox = (
                max(0, x_left - margin),
                max(0, y_top - margin),
                min(plumber_page.width, x_right + margin),
                min(plumber_page.height, y_bot + margin)
            )
            sub_page = plumber_page.within_bbox(crop_bbox)
            settings = {
                "vertical_strategy": "explicit",
                "horizontal_strategy": "explicit",
                "explicit_vertical_lines": group_v_xs,
                "explicit_horizontal_lines": group_ys,
                "intersection_y_tolerance": 5,
                "intersection_x_tolerance": 5
            }
            fallback_objs = sub_page.find_tables(settings)
            fallback_exts = sub_page.extract_tables(settings)
            for ft, fe in zip(fallback_objs, fallback_exts):
                bx0, by0, bx1, by1 = ft.bbox
                overlap = False
                cx, cy = (bx0 + bx1) / 2, (by0 + by1) / 2
                for cx0, cy0, cx1, cy1 in covered:
                    if cx0 <= cx <= cx1 and cy0 <= cy <= cy1:
                        overlap = True
                        break
                if not overlap and _is_content_table(fe):
                    results.append((ft, fe))
                    covered.add((round(bx0), round(by0), round(bx1), round(by1)))
        except Exception:
            pass

    return results

def process_tables(worker, doc, deck_id, deck_name, start, end, model, pdf_path):
    import fitz
    try:
        import pdfplumber
    except ImportError:
        worker.finished_import.emit(False, "Biblioteca 'pdfplumber' não encontrada.")
        return

    from PIL import Image, ImageDraw
    import io as _io

    safe_deck_name = re.sub(r'[^A-Za-z0-9_]', '', deck_name.replace(' ', '_'))
    cards_added = 0
    SCALE = 2.0

    with pdfplumber.open(pdf_path) as plumber_pdf:
        for page_num in range(start, end + 1):
            if worker.is_cancelled:
                break
            worker._emit_progress(page_num, start, f"Tabelas — pág. {page_num + 1}")

            fitz_page   = doc[page_num]
            plumber_page = plumber_pdf.pages[page_num]

            all_tables = _find_all_tables(plumber_page)

            for t_idx, (t_obj, t_ext) in enumerate(all_tables):
                if not _is_content_table(t_ext):
                    continue

                best_row_cells = []
                for row in t_obj.rows:
                    cells = row.cells if hasattr(row, 'cells') else row
                    valid_cells = [c for c in cells if c is not None]
                    if len(valid_cells) > len(best_row_cells):
                        best_row_cells = valid_cells
                        
                real_cols = [(c[0], c[2]) for c in best_row_cells if (c[2] - c[0]) >= 15]
                if len(real_cols) < 2:
                    continue

                row_ys = []
                for row in t_obj.rows:
                    cells = row.cells if hasattr(row, 'cells') else row
                    valid_cells = [c for c in cells if c is not None]
                    if valid_cells:
                        y_top = min(c[1] for c in valid_cells)
                        y_bot = max(c[3] for c in valid_cells)
                        row_ys.append((y_top, y_bot))
                    else:
                        row_ys.append(None)

                if len(row_ys) < 1:
                    continue

                header_idx = 0
                for i, row_data in enumerate(t_ext):
                    non_null = [c for c in row_data if c and str(c).strip()]
                    if len(non_null) >= 2:
                        header_idx = i
                        break

                is_header = False
                if header_idx < len(t_ext):
                    cells_data = [str(c).strip() for c in t_ext[header_idx] if c and str(c).strip()]
                    if cells_data:
                        has_numbers = any(re.search(r'\d', c) for c in cells_data)
                        is_long = any(len(c) > 60 for c in cells_data)
                        if not has_numbers and not is_long:
                            is_header = True
                            
                if t_obj.bbox[1] < 100:
                    is_header = False

                start_row_idx = header_idx + 1 if is_header else header_idx

                tx0, ty0, tx1, ty1 = t_obj.bbox
                final_x0, final_y0, final_x1, final_y1 = tx0, ty0, tx1, ty1

                for b in fitz_page.get_text("dict").get("blocks", []):
                    if b.get("type") == 0:
                        bx0, by0, bx1, by1 = b.get("bbox")
                        texto = "".join([s.get("text", "") for l in b.get("lines", []) for s in l.get("spans", [])]).strip()
                        
                        if by1 <= ty0 + 5 and (ty0 - by1) < 40:
                            if texto.startswith("Tabela"):
                                final_y0 = min(final_y0, by0)
                                final_x0 = min(final_x0, bx0)
                                final_x1 = max(final_x1, bx1)
                        
                        if by0 >= ty1 - 5 and (by0 - ty1) < 40:
                            if texto.startswith("Fonte"):
                                final_y1 = max(final_y1, by1)
                                final_x0 = min(final_x0, bx0)
                                final_x1 = max(final_x1, bx1)

                PADDING = 8
                pw = fitz_page.rect.width
                ph = fitz_page.rect.height
                
                bx0 = max(0, final_x0 - PADDING)
                by0 = max(0, final_y0 - PADDING)
                bx1 = min(pw, final_x1 + PADDING)
                by1 = min(ph, final_y1 + PADDING)

                clip = fitz.Rect(bx0, by0, bx1, by1)
                mat  = fitz.Matrix(SCALE, SCALE)
                pix  = fitz_page.get_pixmap(matrix=mat, clip=clip)
                base_img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)

                def cell_text_for_col(row_idx, col_x0, col_x1):
                    if row_idx >= len(t_obj.rows) or row_idx >= len(t_ext):
                        return ""
                    row = t_obj.rows[row_idx]
                    cells = row.cells if hasattr(row, 'cells') else row
                    row_data = t_ext[row_idx]
                    texts = []
                    for cell_bbox, cell_text in zip(cells, row_data):
                        if cell_bbox is None or not cell_text:
                            continue
                        cx = (cell_bbox[0] + cell_bbox[2]) / 2
                        if col_x0 - 1 <= cx <= col_x1 + 1:
                            texts.append(str(cell_text).strip())
                    return " ".join(texts) if texts else ""

                def pdf_to_px_x(x): return int((x - bx0) * SCALE)
                def pdf_to_px_y(y): return int((y - by0) * SCALE)

                cols_to_occlude = real_cols[1:]

                for col_idx, (col_x0, col_x1) in enumerate(cols_to_occlude):
                    for row_idx in range(start_row_idx, len(row_ys)):
                        if worker.is_cancelled:
                            break

                        if row_ys[row_idx] is None:
                            continue

                        row_top, row_bot = row_ys[row_idx]
                        answer_text = cell_text_for_col(row_idx, col_x0, col_x1)

                        px0 = max(0, pdf_to_px_x(col_x0))
                        px1 = min(base_img.width,  pdf_to_px_x(col_x1))
                        py0 = max(0, pdf_to_px_y(row_top))
                        py1 = min(base_img.height, pdf_to_px_y(row_bot))

                        if px1 <= px0 or py1 <= py0:
                            continue

                        timestamp = int(time.time() * 1000)
                        slug = f"tbl_{safe_deck_name}_p{page_num+1}_t{t_idx+1}_c{col_idx+1}_r{row_idx}_{timestamp}"

                        img_q = base_img.copy()
                        draw_q = ImageDraw.Draw(img_q)
                        draw_q.rectangle([px0, py0, px1, py1], fill=(70, 130, 180))
                        buf_q = _io.BytesIO()
                        img_q.save(buf_q, format="PNG")
                        fn_q = slug + "_q.png"
                        mw.col.media.write_data(fn_q, buf_q.getvalue())

                        img_a = base_img.copy()
                        draw_a = ImageDraw.Draw(img_a)
                        draw_a.rectangle([px0, py0, px1, py1], outline=(39, 174, 96), width=3)
                        buf_a = _io.BytesIO()
                        img_a.save(buf_a, format="PNG")
                        fn_a = slug + "_a.png"
                        mw.col.media.write_data(fn_a, buf_a.getvalue())

                        note = mw.col.new_note(model)
                        note["Imagem"]        = f'<img src="{fn_q}">'
                        note["ImagemResposta"] = f'<img src="{fn_a}">'
                        note["Gabarito"]       = answer_text
                        mw.col.add_note(note, deck_id)
                        cards_added += 1

    total_doc_pages = len(doc)
    page_range_info = f" (págs. {start+1}–{end+1})" if (start > 0 or end < total_doc_pages - 1) else ""
    if worker.is_cancelled:
        worker.finished_import.emit(False, "Importação cancelada.")
    else:
        worker.progress_update.emit(100, "Concluído!")
        worker.finished_import.emit(True,
            f"Importação concluída{page_range_info}!\n"
            f"{cards_added} cards de Image Occlusion adicionados ao baralho '{deck_name}'.")