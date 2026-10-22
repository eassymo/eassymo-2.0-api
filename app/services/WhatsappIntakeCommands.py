import unicodedata

START_BURST_COMMANDS = frozenset({"PEDIDO", "NUEVO", "BORRADOR"})
FLUSH_COMMANDS = frozenset({"LISTO", "ENVIAR"})
CANCEL_COMMANDS = frozenset({"CANCELAR"})


def normalize_command(body: str) -> str:
    text = (body or "").strip().upper()
    decomposed = unicodedata.normalize("NFD", text)
    return "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")


def classify_body(body: str) -> str:
    cmd = normalize_command(body)
    if cmd in START_BURST_COMMANDS:
        return "start"
    if cmd in FLUSH_COMMANDS:
        return "flush"
    if cmd in CANCEL_COMMANDS:
        return "cancel"
    return "content"
