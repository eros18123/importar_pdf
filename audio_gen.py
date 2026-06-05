# -*- coding: utf-8 -*-
import re
import uuid
import io as _io
from aqt import mw

def generate_audio_tag(text):
    """
    Limpa o texto (regras PT-BR) e gera um arquivo MP3 usando gTTS.
    Retorna a tag [sound:...] para o Anki.
    """
    try:
        from gtts import gTTS
        
        # Limpeza de texto PT-BR
        clean_text = text.replace('-\n', '').replace('\n', ' ').replace('- ', '')
        clean_text = re.sub(r'([a-zA-Z])-(me|te|se|nos|vos|lo|la|los|las|lhe|lhes)\b', r'\1 \2', clean_text, flags=re.IGNORECASE)
        clean_text = clean_text.replace('-', '')
        clean_text = re.sub(r'<[^>]+>', '', clean_text) # Remove HTML tags
        
        if len(clean_text.strip()) < 2: 
            return ""

        tts = gTTS(text=clean_text, lang='pt')
        filename = f"audio_ia_{uuid.uuid4().hex[:8]}.mp3"
        
        # Salva direto na pasta de mídia do Anki
        buf = _io.BytesIO()
        tts.write_to_fp(buf)
        mw.col.media.write_data(filename, buf.getvalue())
        
        return f"[sound:{filename}]"
    except Exception as e:
        print(f"Erro no gTTS: {e}")
        return ""