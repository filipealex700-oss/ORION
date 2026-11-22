"""IA Juiz (Master Plan HIPON.V3): Gerador -> Crítico -> Juiz.
- Gerador: o modelo de código escreve/corrige o ficheiro.
- Crítico: um modelo DIFERENTE (o principal) revê o código e devolve problemas em JSON.
- Juiz: árbitro determinístico (sem gastar VRAM com um 3.º modelo): junta verificações estáticas
  (sintaxe, padrões perigosos) com a crítica e decide aprovado / corrigido / rejeitado.
Cada revisão fica guardada em orion_juiz.db para o painel."""
import ast
import json
import os
import re
import time

import ollama

from config import BASE
from dbutil import DBSeguro

PERIGOSOS_PY = {
    "os.system": "executa comandos da shell", "os.remove": "apaga ficheiros", "os.unlink": "apaga ficheiros",
    "os.rmdir": "apaga pastas", "shutil.rmtree": "apaga pastas inteiras", "subprocess": "lança processos",
    "eval": "executa texto como código", "exec": "executa texto como código", "ctypes": "acesso nativo ao Windows",
    "winreg": "altera o registo do Windows", "socket": "abre ligações de rede", "requests.post": "envia dados para a rede",
    "pickle.loads": "desserialização insegura", "__import__": "importação dinâmica",
}
PERIGOSOS_TXT = [(r"rm\s+-rf", "apaga recursivamente"), (r"format\s+[a-z]:", "formata um disco"),
                 (r"del\s+/[sq]", "apaga recursivamente"), (r"reg\s+delete", "apaga chaves do registo")]

SISTEMA_CRITICO = (
    "És um revisor de código sénior e rigoroso (o Crítico). Recebes um pedido e o código produzido. "
    "Procura erros de lógica, bugs, falhas de segurança, exceções não tratadas em entradas do utilizador "
    "e partes do pedido que não foram cumpridas. Não reescrevas o código. Responde APENAS com JSON: "
    '{"pontuacao": 0-10, "problemas": [{"gravidade": "alta|media|baixa", "descricao": "..."}], '
    '"resumo": "uma frase"}')


def _db():
    db = DBSeguro(os.path.join(BASE, "orion_juiz.db"))
    db.executescript("""CREATE TABLE IF NOT EXISTS revisoes(
        id INTEGER PRIMARY KEY, ts REAL, ficheiro TEXT, pedido TEXT, rondas INTEGER, veredicto TEXT,
        pontuacao REAL, problemas TEXT, resumo TEXT, modelo_critico TEXT)""")
    return db


def verificacoes_estaticas(codigo, sufixo):
    """-> lista de problemas detetados sem modelo (sintaxe e padrões perigosos)."""
    probs = []
    sufixo = sufixo.lower()
    if sufixo == ".py":
        try:
            arvore = ast.parse(codigo)
        except SyntaxError as e:
            return [{"gravidade": "alta", "origem": "estatica", "descricao": f"Erro de sintaxe na linha {e.lineno}: {e.msg}"}]
        vistos = set()
        for n in ast.walk(arvore):
            nome = None
            if isinstance(n, (ast.Import, ast.ImportFrom)):
                mods = [a.name for a in n.names] if isinstance(n, ast.Import) else [n.module or ""]
                for m in mods:
                    if m.split(".")[0] in PERIGOSOS_PY:
                        nome = m.split(".")[0]
            elif isinstance(n, ast.Call):
                f = n.func
                if isinstance(f, ast.Name):
                    nome = f.id if f.id in PERIGOSOS_PY else None
                elif isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name):
                    k = f"{f.value.id}.{f.attr}"
                    nome = k if k in PERIGOSOS_PY else None
            if nome and nome not in vistos:
                vistos.add(nome)
                probs.append({"gravidade": "media", "origem": "estatica",
                              "descricao": f"Usa {nome} ({PERIGOSOS_PY[nome]}): confirma que é intencional."})
    elif sufixo == ".json":
        try:
            json.loads(codigo)
        except ValueError as e:
            probs.append({"gravidade": "alta", "origem": "estatica", "descricao": f"JSON inválido: {e}"})
    for padrao, descr in PERIGOSOS_TXT:
        if re.search(padrao, codigo, re.I):
            probs.append({"gravidade": "media", "origem": "estatica", "descricao": f"Comando perigoso ({descr})."})
    if not codigo.strip():
        probs.append({"gravidade": "alta", "origem": "estatica", "descricao": "O ficheiro está vazio."})
    return probs


def criticar(cfg, pedido, codigo, ficheiro):
    modelo = cfg.get("juiz", {}).get("modelo_critico") or cfg["modelo_llm"]
    try:
        r = ollama.chat(model=modelo, format="json", keep_alive="2m",
                        options={"temperature": 0.1, "num_ctx": 8192},
                        messages=[{"role": "system", "content": SISTEMA_CRITICO},
                                  {"role": "user", "content": f"Ficheiro: {ficheiro}\nPedido: {pedido}\n\n"
                                                              f"CÓDIGO:\n```\n{codigo[:12000]}\n```"}])
        d = json.loads(r["message"]["content"])
        probs = [{"gravidade": str(p.get("gravidade", "baixa")).lower(), "origem": "critico",
                  "descricao": str(p.get("descricao", ""))[:400]}
                 for p in d.get("problemas", []) if isinstance(p, dict) and p.get("descricao")]
        return float(d.get("pontuacao", 5)), probs, str(d.get("resumo", ""))[:300], modelo
    except Exception as e:
        return None, [], f"Crítico indisponível ({e}); só verificações estáticas.", modelo


def julgar(estaticos, pontuacao, criticos, minimo):
    """Juiz determinístico. -> (aprovado, motivo)"""
    if any(p["gravidade"] == "alta" for p in estaticos):
        return False, "falha estática grave"
    if any(p["gravidade"] == "alta" for p in criticos):
        return False, "o crítico encontrou problemas graves"
    if pontuacao is not None and pontuacao < minimo:
        return False, f"pontuação {pontuacao:.0f}/10 abaixo de {minimo}"
    return True, "aprovado"


def rever(cfg, ficheiro, pedido, codigo, sufixo, corrigir=None):
    """Ciclo completo. `corrigir(codigo, problemas)` devolve nova versão (Gerador); None = só rever.
    -> (codigo_final, registo)"""
    jc = cfg.get("juiz", {})
    rondas_max = int(jc.get("rondas", 2)) if corrigir else 0
    minimo = float(jc.get("pontuacao_minima", 7))
    corrigido, ronda = False, 0
    while True:
        est = verificacoes_estaticas(codigo, sufixo)
        sintaxe_ok = not any(p["gravidade"] == "alta" for p in est)
        pont, crit, resumo, modelo = criticar(cfg, pedido, codigo, ficheiro) if sintaxe_ok else (None, [], "", "")
        ok, motivo = julgar(est, pont, crit, minimo)
        if ok or ronda >= rondas_max:
            break
        ronda += 1
        codigo = corrigir(codigo, est + crit)
        corrigido = True
    veredicto = ("corrigido" if corrigido else "aprovado") if ok else "rejeitado"
    if ok and pont is None:
        veredicto = "parcial"  # o crítico não respondeu: só passou nas verificações estáticas
    registo = {"ficheiro": ficheiro, "pedido": pedido, "rondas": ronda, "veredicto": veredicto,
               "pontuacao": pont, "problemas": est + crit, "resumo": resumo or motivo,
               "motivo": motivo, "sintaxe_ok": not any(p["gravidade"] == "alta" for p in est)}
    db = _db()
    db.execute("INSERT INTO revisoes(ts, ficheiro, pedido, rondas, veredicto, pontuacao, problemas, resumo, modelo_critico) "
               "VALUES(?,?,?,?,?,?,?,?,?)",
               (time.time(), ficheiro, pedido[:500], ronda, veredicto, pont,
                json.dumps(registo["problemas"], ensure_ascii=False), registo["resumo"], modelo))
    db.commit()
    return codigo, registo


def historico(n=50):
    rows = _db().execute("SELECT id, ts, ficheiro, pedido, rondas, veredicto, pontuacao, problemas, resumo, "
                         "modelo_critico FROM revisoes ORDER BY id DESC LIMIT ?", (n,)).fetchall()
    return [{"id": i, "ts": ts, "ficheiro": f, "pedido": p, "rondas": r, "veredicto": v, "pontuacao": s,
             "problemas": json.loads(pr or "[]"), "resumo": rs, "modelo_critico": m}
            for i, ts, f, p, r, v, s, pr, rs, m in rows]


def frase(registo):
    v = registo["veredicto"]
    n = len(registo["problemas"])
    base = {"aprovado": "A IA Juiz aprovou à primeira",
            "corrigido": f"A IA Juiz corrigiu-o em {registo['rondas']} ronda(s)",
            "rejeitado": "A IA Juiz não ficou satisfeita",
            "parcial": "Passou nas verificações automáticas, mas o crítico não estava disponível"}[v]
    return base + (f" ({n} observação(ões) por rever no painel)." if n else ".")
