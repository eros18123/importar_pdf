# -*- coding: utf-8 -*-
from aqt import mw

def get_or_create_basic_model():
    model_name = "Básico (PDF Import)"
    model = mw.col.models.by_name(model_name)
    if model: return model

    mm = mw.col.models
    model = mm.new(model_name)
    for field_name in ["Frente", "Verso"]:
        mm.add_field(model, mm.new_field(field_name))
        
    model['css'] = ".card { font-family: Arial, sans-serif; font-size: 20px; text-align: center; color: black; background-color: white; padding: 20px; }"
    template = mm.new_template("Card 1")
    template['qfmt'] = "{{Frente}}"
    template['afmt'] = "{{FrontSide}}\n\n<hr id=answer>\n\n{{Verso}}"
    mm.add_template(model, template)
    mm.add(model)
    return model

def get_or_create_cloze_model():
    model_name = "Omissão de Palavras (PDF Import)"
    model = mw.col.models.by_name(model_name)
    if model: return model

    mm = mw.col.models
    model = mm.new(model_name)
    model['type'] = 1 
    mm.add_field(model, mm.new_field("Texto"))
        
    model['css'] = ".card { font-family: Arial, sans-serif; font-size: 20px; text-align: center; color: black; background-color: white; padding: 20px; } .cloze { font-weight: bold; color: #2980b9; }"
    template = mm.new_template("Cloze")
    template['qfmt'] = "{{cloze:Texto}}"
    template['afmt'] = "{{cloze:Texto}}"
    mm.add_template(model, template)
    mm.add(model)
    return model

def get_or_create_image_occlusion_model():
    model_name = "Image Occlusion (PDF Import)"
    mm = mw.col.models
    model = mm.by_name(model_name)

    if model:
        field_names = [f["name"] for f in model["flds"]]
        if "ImagemResposta" not in field_names:
            mm.remove(model["id"])
            model = None

    if model: return model

    model = mm.new(model_name)
    for fn in ["Imagem", "ImagemResposta", "Gabarito"]:
        mm.add_field(model, mm.new_field(fn))

    model['css'] = ".card { font-family: Arial, sans-serif; text-align: center; background: #f9f9f9; } .card img { max-width: 95%; border: 1px solid #ccc; border-radius: 6px; } .answer-label { font-size: 14px; color: #27ae60; font-weight: bold; margin-top: 8px; }"
    tpl = mm.new_template("Card 1")
    tpl['qfmt'] = '<div>{{Imagem}}</div>'
    tpl['afmt'] = '<div>{{ImagemResposta}}</div><div class="answer-label">{{Gabarito}}</div>'
    mm.add_template(model, tpl)
    mm.add(model)
    return model

def get_or_create_mcq_model():
    model_name = "Múltipla Escolha (PDF Import)"
    model = mw.col.models.by_name(model_name)
    if model: return model

    mm = mw.col.models
    model = mm.new(model_name)
    
    # Campos que a função process_mcq usa:
    for field_name in ["Titulo", "Enunciado", "A", "B", "C", "D", "E", "Gabarito"]:
        mm.add_field(model, mm.new_field(field_name))
        
    model['css'] = """
    .card { font-family: Arial, sans-serif; font-size: 16px; text-align: left; padding: 20px; background-color: #f9f9f9; } 
    .enunciado { font-weight: bold; margin-bottom: 20px; font-size: 18px; color: #2c3e50; } 
    .opt { background: #fff; padding: 12px; margin: 8px 0; border: 1px solid #ddd; border-radius: 5px; box-shadow: 0 1px 3px rgba(0,0,0,0.05); } 
    .correct { background: #d4edda; border: 1px solid #c3e6cb; color: #155724; padding: 15px; border-radius: 5px; margin-top: 15px; }
    """
    
    template = mm.new_template("Questão")
    
    # QFMT: Pergunta com Javascript para embaralhar as alternativas na hora de estudar!
    template['qfmt'] = """<div style="font-size: 12px; color: #7f8c8d; margin-bottom: 10px;">{{Titulo}}</div>
<div class="enunciado">{{Enunciado}}</div>
<div id="options">
  {{#A}}<div class="opt">{{A}}</div>{{/A}}
  {{#B}}<div class="opt">{{B}}</div>{{/B}}
  {{#C}}<div class="opt">{{C}}</div>{{/C}}
  {{#D}}<div class="opt">{{D}}</div>{{/D}}
  {{#E}}<div class="opt">{{E}}</div>{{/E}}
</div>

<script>
  // Código para embaralhar aleatoriamente as alternativas toda vez que a carta é exibida
  var parent = document.getElementById('options');
  var divs = parent.children;
  var frag = document.createDocumentFragment();
  while (divs.length) {
      frag.appendChild(divs[Math.floor(Math.random() * divs.length)]);
  }
  parent.appendChild(frag);
</script>"""
    
    # AFMT: Resposta
    template['afmt'] = """<div style="font-size: 12px; color: #7f8c8d;">{{Titulo}}</div>
<div class="enunciado">{{Enunciado}}</div>
<div class="correct">
  <b>Resposta Correta:</b><br><br>
  {{A}}
</div>
{{#Gabarito}}
<div style="margin-top: 15px; font-size: 14px; color: #555; background: #fff; padding: 15px; border: 1px solid #eee; border-radius: 5px;">
  <b>Justificativa / Gabarito Original:</b><br>
  {{Gabarito}}
</div>
{{/Gabarito}}"""
    
    mm.add_template(model, template)
    mm.add(model)
    return model

def get_premium_model():
    model_name = "Premium IA (Sefaz Style)"
    model = mw.col.models.by_name(model_name)
    if model: return model

    mm = mw.col.models
    model = mm.new(model_name)
    
    for f in ["Frente", "Verso", "Concurso", "Cargo", "Objetivo", "Img", "Audio"]:
        mm.add_field(model, mm.new_field(f))
        
    model['css'] = ".card { font-family: Arial; text-align: center; background: #333; }"
    
    template = mm.new_template("Card 1")
    
    html_base = """
    <div style="font-family:Arial,sans-serif;max-width:700px;margin:0 auto;padding:4px;border-radius:14px;background:linear-gradient(135deg,#f9a825,#ffd54f,#f57f17,#ffd54f,#f9a825);">
    <div style="border-radius:11px;overflow:hidden;background:#e8eaf6;">
      <div style="display:flex;align-items:center;padding:14px 18px;background:#f8f9fc;gap:16px;">
        <div style="width:85px;height:85px;border-radius:14px;background:#fff;display:flex;align-items:center;justify-content:center;overflow:hidden;flex-shrink:0;box-shadow:0 2px 8px rgba(0,0,0,0.05);">
          {{Img}}
        </div>
        <div style="flex:1; display:flex; flex-direction:column; justify-content:center;">
          <div style="display:flex; justify-content:space-between; align-items:flex-start; width:100%;">
            <div style="display:flex; flex-direction:column;">
              <div style="font-size:32px; font-weight:900; color:#283593; text-transform:uppercase; line-height:1; font-family:'Arial Black', Impact, sans-serif;">{{Concurso}}</div>
              <div style="font-size:16px; font-weight:800; color:#283593; text-transform:uppercase; margin-top:6px;">{{Cargo}}</div>
            </div>
            <div style="background:#eef1f6; border-radius:16px; padding:6px 14px; border-left:4px solid #283593; font-size:12px; font-weight:700; color:#283593; white-space:nowrap; margin-top:2px;">
              Objetivo: <span style="color:#b71c1c; font-weight:900;">{{Objetivo}}</span>
            </div>
          </div>
          <div style="width:100%; height:3px; background:#283593; margin-top:10px; border-radius:2px;"></div>
        </div>
      </div>
      <div style="background:#f0f2f8; border-left:4px solid #dca743; border-radius:8px; margin:14px 18px 0px 18px; padding:10px 14px; font-size:12px; color:#1a237e; font-weight:700; line-height:1.5; text-align:left; box-sizing:border-box;">
        <div>{{Deck}}</div>
        {{#Tags}}<div style="margin-top:2px;">{{Tags}}</div>{{/Tags}}
      </div>
      <div style="padding:14px 18px 16px;display:flex;flex-direction:column;align-items:center;background:#e8eaf6;">
        <div style="background:#1a237e;color:#fff;font-size:11px;font-weight:700;letter-spacing:0.12em;text-transform:uppercase;padding:5px 22px;border-radius:20px;margin-bottom:12px;">PERGUNTA</div>
        <div style="background:#1a237e;border-radius:12px;padding:18px 22px;text-align:center;width:100%;box-sizing:border-box;">
          <p style="color:#fff;font-size:15px;font-weight:700;line-height:1.5;margin:0;">{{Frente}}</p>
        </div>
      </div>
      <div style="background:#e8eaf6;padding:0 40px;">
        <div style="height:3px;background:linear-gradient(to right,#1565c0 0%,#43a047 33%,#ffa000 66%,#e53935 100%);border-radius:2px;"></div>
      </div>
      <div style="padding:14px 18px 18px;display:flex;flex-direction:column;align-items:center;background:#e8eaf6;">
        <div style="background:#111;color:#fff;font-size:11px;font-weight:700;letter-spacing:0.12em;text-transform:uppercase;padding:5px 22px;border-radius:20px;margin-bottom:12px;">RESPOSTA</div>
        <div style="background:#111;border-radius:12px;padding:16px 22px;text-align:center;width:100%;box-sizing:border-box;">
          <p style="color:#e53935;font-size:20px;font-weight:700;margin:0;">{RESPOSTA_PLACEHOLDER}</p>
        </div>
      </div>
      {{Audio}}
    </div>
    </div>
    """
    
    template['qfmt'] = html_base.replace("{RESPOSTA_PLACEHOLDER}", "???")
    template['afmt'] = html_base.replace("{RESPOSTA_PLACEHOLDER}", "{{Verso}}")
    
    mm.add_template(model, template)
    mm.add(model)
    return model