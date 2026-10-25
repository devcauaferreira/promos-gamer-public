"""Classificação conservadora das sete categorias de hardware monitoradas."""
import re
import unicodedata

CATEGORIES = {
    "processador": "Processadores",
    "placa_mae": "Placas-mãe",
    "memoria_ram": "Memória RAM",
    "ssd": "SSDs",
    "fonte": "Fontes de alimentação",
    "placa_video": "Placas de vídeo",
    "kit_upgrade": "Kits upgrade",
}


def normalized(text):
    return "".join(c for c in unicodedata.normalize("NFKD", text.lower()) if not unicodedata.combining(c))


def category_for(title):
    text = normalized(title).replace("-", " ")
    # Evita computadores completos e acessórios, preservando peças "para computador".
    if re.search(r"^(pc gamer|computador|notebook|mini pc)\b", text) or re.search(r"\b(adaptador|case para|cabo|suporte|adesivo|carregador|impressora)\b", text):
        return None
    if re.search(r"\bkit\s+(?:de\s+)?upgrade\b", text) or (
            re.search(r"\bkit\b", text)
            and re.search(r"\b(placa mae|motherboard)\b", text)
            and re.search(r"\b(processador|ryzen|core\s+i[3579])\b", text)):
        return "kit_upgrade"
    if re.search(r"\b(placa (?:de )?video|graphics card|geforce\s+(?:rtx|gtx)|radeon\s+rx\s*\d{3,4})\b", text):
        return "placa_video"
    if re.search(r"\b(placa mae|motherboard)\b", text):
        return "placa_mae"
    if re.search(r"\b(processador|cpu amd|cpu intel)\b", text):
        return "processador"
    if re.search(r"\b(memoria|memorias|ram)\b", text) and re.search(r"\b(ddr\s*[345]|ram)\b", text):
        return "memoria_ram"
    if re.search(r"\b(ssd|solid state)\b", text):
        return "ssd"
    if re.search(r"\b(fonte|power supply)\b", text) and re.search(r"\b(atx|sfx|\d{3,4}\s*w|80\s*plus|80plus)\b", text):
        return "fonte"
    return None
