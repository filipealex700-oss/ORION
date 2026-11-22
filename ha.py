"""Integração opcional com o Home Assistant (luzes, tomadas, cenas)."""
import requests


def _chamar(cfg, dominio, servico, dados):
    h = cfg["home_assistant"]
    if not h.get("ativo"):
        raise RuntimeError("O Home Assistant não está ativo no config.json.")
    r = requests.post(
        f"{h['url'].rstrip('/')}/api/services/{dominio}/{servico}",
        headers={"Authorization": f"Bearer {h['token']}"},
        json=dados, timeout=5)
    r.raise_for_status()


def controlar(cfg, dispositivo, acao, brilho=None):
    ents = cfg["home_assistant"]["entidades"]
    ent = ents.get(dispositivo.lower().strip())
    if not ent and "." in dispositivo:
        ent = dispositivo
    if not ent:
        return f"Dispositivo desconhecido: {dispositivo}. Conhecidos: {', '.join(ents) if ents else 'nenhum'}"
    servico = {"ligar": "turn_on", "desligar": "turn_off", "alternar": "toggle"}.get(acao)
    if not servico:
        return "Ação inválida. Use ligar, desligar ou alternar."
    dominio = ent.split(".")[0]
    dados = {"entity_id": ent}
    if brilho is not None and dominio == "light" and servico == "turn_on":
        dados["brightness_pct"] = max(1, min(100, int(brilho)))
    _chamar(cfg, dominio, servico, dados)
    return f"{dispositivo}: {acao} concluído."


def cena(cfg, nome):
    cenas = cfg["home_assistant"]["cenas"]
    ent = cenas.get(nome.lower().strip())
    if not ent:
        return f"Cena desconhecida: {nome}. Conhecidas: {', '.join(cenas.keys()) if cenas else 'nenhuma'}"
    _chamar(cfg, "scene", "turn_on", {"entity_id": ent})
    return f"Cena {nome} ativada."
