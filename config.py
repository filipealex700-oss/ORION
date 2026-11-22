import json
import os
import sys

# Quando empacotado em .exe, os dados ficam na pasta do executável (gravável).
BASE = (os.path.dirname(sys.executable) if getattr(sys, "frozen", False)
        else os.path.dirname(os.path.abspath(__file__)))

# Segredos que vêm do ficheiro .env (nunca do config.json)
SEGREDOS = {
    "ORION_LANGFLOW_API_KEY": ("langflow", "api_key"),
    "ORION_HA_TOKEN": ("home_assistant", "token"),
}


def ler_env(caminho=None):
    """Carrega KEY=VALOR do .env para os.environ (sem sobrepor variáveis já definidas)."""
    caminho = caminho or os.path.join(BASE, ".env")
    if not os.path.exists(caminho):
        return
    with open(caminho, encoding="utf-8") as f:
        for linha in f:
            linha = linha.strip()
            if not linha or linha.startswith("#") or "=" not in linha:
                continue
            k, v = linha.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def carregar():
    with open(os.path.join(BASE, "config.json"), encoding="utf-8") as f:
        cfg = json.load(f)
    ler_env()
    for env, (secao, chave) in SEGREDOS.items():
        if os.environ.get(env):
            cfg.setdefault(secao, {})[chave] = os.environ[env]
    return cfg


def estado_segredos(cfg):
    """Para o painel: que segredos existem (nunca devolve o valor)."""
    out = []
    for env, (secao, chave) in SEGREDOS.items():
        valor = (cfg.get(secao) or {}).get(chave, "")
        presente = bool(valor) and not str(valor).startswith("COLA_AQUI")
        out.append({"nome": env, "secao": secao, "presente": presente,
                    "origem": ".env" if os.environ.get(env) else ("config.json" if presente else "-")})
    return out
