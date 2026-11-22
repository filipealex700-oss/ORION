"""Aprendizagem contínua, local e transparente. Corre nos tempos livres (sem estares a usar o ORION).
O que aprende: factos e preferências das conversas, hábitos de uso, correções do reconhecimento de voz
e o teu feedback (guardado em treino/feedback.jsonl, que serve de base a um treino futuro do modelo).
Não altera os pesos do modelo de linguagem."""
import json
import os
import re
import statistics
import time
from datetime import datetime
from pathlib import Path

import ollama

from config import BASE
from routing import reavaliar
from tools import CTX, ferramenta

SISTEMA_FACTOS = (
    "Lês uma conversa entre o utilizador (U) e uma assistente (A). Extrai APENAS factos duradouros e "
    "preferências que o utilizador (U) disse explicitamente sobre si, os seus hábitos, objetivos ou gostos. "
    "Também extrai correções de reconhecimento de voz: se o utilizador corrigir o que a assistente percebeu "
    "(ex.: 'não disse X, disse Y'), regista o par (errado, certo). "
    "Ignora pedidos pontuais, perguntas e tarefas. NUNCA incluas dados sensíveis (palavras-passe, números de "
    "cartões ou contas, documentos de identificação, saúde). Máximo 5 frases curtas no formato "
    '"O utilizador ...". Responde só JSON: {"factos": ["..."], "correcoes": [{"errado": "...", "certo": "..."}]}. '
    'Se não houver nada, {"factos": [], "correcoes": []}.')

HABITUAIS = ("abrir_programa", "ativar_modo", "resumo_do_dia")


def _descr(ferr, args):
    a = json.loads(args or "{}")
    if ferr == "abrir_programa":
        return f"abrir {a.get('nome', '')}".strip()
    if ferr == "ativar_modo":
        return f"ativar o modo {a.get('nome', '')}".strip()
    return "pedir o resumo do dia"


class Aprendizagem:
    def __init__(self, cfg, memoria, emitir):
        self.cfg, self.mem, self.emitir = cfg, memoria, emitir

    def ciclo(self):
        """Chamado quando o ORION está em repouso. Limita-se a si próprio no tempo."""
        intervalo = self.cfg.get("aprendizagem_intervalo_min", 30) * 60
        if time.time() - float(self.mem.meta_get("aprendizagem_ultimo", 0)) < intervalo:
            return
        self.mem.meta_set("aprendizagem_ultimo", time.time())
        try:
            n = self.consolidar()
            h = self.detetar_habitos()
            r = reavaliar(self.mem)
            if r:
                self.emitir("aprendi", r)
            if n or h:
                self.emitir("aprendi", f"{n} facto(s) novo(s) na memória, {h} hábito(s) detetado(s).")
        except Exception as e:
            self.emitir("sistema", f"[aprendizagem] erro: {e}")

    def consolidar(self):
        ultimo = int(self.mem.meta_get("consolidado_ate", 0))
        rows = self.mem.db.execute("SELECT id, papel, texto FROM mensagens WHERE id>? ORDER BY id LIMIT 60",
                                   (ultimo,)).fetchall()
        if len(rows) < 6:
            return 0
        conversa = "\n".join(f"{'U' if p == 'user' else 'A'}: {t}" for _, p, t in rows)
        r = ollama.chat(model=self.cfg["modelo_llm"], format="json", options={"temperature": 0},
                        messages=[{"role": "system", "content": SISTEMA_FACTOS},
                                  {"role": "user", "content": conversa}])
        try:
            dados = json.loads(r["message"]["content"])
            factos = dados.get("factos", [])[:5]
            correcoes = dados.get("correcoes", [])[:5]
        except Exception:
            factos, correcoes = [], []
        novos = 0
        for f in factos:
            if isinstance(f, str) and len(f) > 10 and self.mem.guardar(f).startswith("Guardado"):
                novos += 1
                self.emitir("aprendi", f"Aprendi: {f}")
        for c in correcoes:
            if isinstance(c, dict) and c.get("errado") and c.get("certo"):
                try:
                    self.mem.db.execute(
                        "INSERT OR REPLACE INTO correcoes(errado, certo) VALUES(?,?)",
                        (str(c["errado"]).strip().lower(), str(c["certo"]).strip()))
                    self.mem.db.execute(
                        "INSERT OR IGNORE INTO vocabulario(palavra) VALUES(?)",
                        (str(c["certo"]).strip().lower(),))
                    self.mem.db.commit()
                    novos += 1
                    self.emitir("aprendi", f"Correção de voz: '{c['errado']}' -> '{c['certo']}'")
                except Exception:
                    pass
        self.mem.meta_set("consolidado_ate", rows[-1][0])
        return novos

    def detetar_habitos(self):
        marcas = ",".join("?" * len(HABITUAIS))
        rows = self.mem.db.execute(f"SELECT ferramenta, args, ts FROM uso WHERE ferramenta IN ({marcas}) "
                                   "AND ts>?", (*HABITUAIS, time.time() - 60 * 86400)).fetchall()
        grupos = {}
        for ferr, args, ts in rows:
            grupos.setdefault((ferr, args), []).append(datetime.fromtimestamp(ts))
        novos = 0
        for (ferr, args), lista in grupos.items():
            dias = {d.date() for d in lista}
            horas = [d.hour + d.minute / 60 for d in lista]
            if len(dias) < 3 or len(lista) < 4:
                continue
            med = statistics.median(horas)
            if any(abs(h - med) > 1.0 for h in horas):
                continue
            if self.mem.db.execute("SELECT 1 FROM sugestoes WHERE ferramenta=? AND args=?",
                                   (ferr, args)).fetchone():
                continue
            hora = f"{int(med):02d}:{int((med % 1) * 60):02d}"
            self.mem.db.execute("INSERT INTO sugestoes(descr, ferramenta, args, hora) VALUES(?,?,?,?)",
                                (_descr(ferr, args), ferr, args, hora))
            self.mem.db.commit()
            novos += 1
        return novos

    def sugestao_nova(self):
        r = self.mem.db.execute("SELECT id, descr, hora FROM sugestoes WHERE estado='nova' LIMIT 1").fetchone()
        if not r:
            return None
        self.mem.db.execute("UPDATE sugestoes SET estado='apresentada' WHERE id=?", (r[0],))
        self.mem.db.commit()
        return (r[0], f"Reparei que costuma {r[1]} por volta das {r[2]}. Quer que lhe lembre todos os dias "
                      f"a essa hora? (sugestão {r[0]})")


# ======================= FERRAMENTAS =======================
@ferramenta("responder_sugestao", "Aceita ou recusa uma sugestão de hábito que a assistente apresentou.",
            {"id": "número da sugestão", "aceitar": "sim | nao"})
def responder_sugestao(id, aceitar):
    mem = CTX["memoria"]
    r = mem.db.execute("SELECT descr, hora FROM sugestoes WHERE id=?", (int(id),)).fetchone()
    if not r:
        return "Sugestão não encontrada."
    if str(aceitar).lower().startswith("s"):
        CTX["autonomo"].agendar(f"habito {id}", f"Costuma {r[0]} por esta hora. Quer que o faça?", r[1],
                                modo="lembrete")
        mem.db.execute("UPDATE sugestoes SET estado='aceite' WHERE id=?", (int(id),))
        mem.db.commit()
        return f"Combinado: lembro-lhe todos os dias às {r[1]}."
    mem.db.execute("UPDATE sugestoes SET estado='recusada' WHERE id=?", (int(id),))
    mem.db.commit()
    return "Está bem, não volto a sugerir isso."


@ferramenta("corrigir_reconhecimento",
            "Ensina o que o utilizador realmente disse quando a assistente percebeu mal uma palavra.",
            {"errado": "como foi percebido", "certo": "o que o utilizador disse"})
def corrigir_reconhecimento(errado, certo):
    mem = CTX.get("memoria")
    if not mem:
        return "Memória não disponível."
    errado = errado.strip().lower()
    certo = certo.strip()
    if not errado or not certo:
        return "Forneça tanto o texto errado como o correto."
    mem.db.execute("INSERT OR REPLACE INTO correcoes(errado, certo) VALUES(?,?)",
                   (errado, certo))
    mem.db.execute("INSERT OR IGNORE INTO vocabulario(palavra) VALUES(?)", (certo.lower(),))
    palavras = re.findall(r"\b\w+\b", certo)
    for p in palavras:
        if len(p) > 2:
            mem.db.execute("INSERT OR IGNORE INTO vocabulario(palavra) VALUES(?)", (p.lower(),))
    mem.db.commit()
    return f"Aprendido: quando perceber '{errado}', passa a ser '{certo}'."


@ferramenta("ensinar_palavra", "Acrescenta uma palavra ou nome ao vocabulário para ser percebida melhor.",
            {"palavra": "nome, marca ou termo"})
def ensinar_palavra(palavra):
    mem = CTX.get("memoria")
    if not mem:
        return "Memória não disponível."
    palavra = palavra.strip()
    if not palavra:
        return "Palavra vazia."
    mem.db.execute("INSERT OR IGNORE INTO vocabulario(palavra) VALUES(?)", (palavra.lower(),))
    mem.db.commit()
    return f"'{palavra}' adicionada ao vocabulário."


@ferramenta("avaliar_resposta", "Regista se o utilizador gostou da última resposta, para aprender com isso.",
            {"avaliacao": "boa | ma (ou 1 a 5)", "comentario": "opcional: o que devia ter respondido"})
def avaliar_resposta(avaliacao, comentario=""):
    mem = CTX.get("memoria")
    if not mem:
        return "Memória não disponível."
    ult = CTX.get("ultima") or {}
    pergunta = ult.get("pergunta", "")
    resposta = ult.get("resposta", "")
    if not pergunta or not resposta:
        hist = mem.historico_recente(4)
        for msg in hist:
            if msg["role"] == "user" and not pergunta:
                pergunta = msg["content"]
            elif msg["role"] == "assistant" and not resposta:
                resposta = msg["content"]
    if not pergunta or not resposta:
        return "Não tenho nenhuma resposta anterior para avaliar."

    av_str = str(avaliacao).lower().strip()
    if av_str.isdigit():
        nota = int(av_str)
        boa = 1 if nota >= 3 else 0
    else:
        boa = 1 if av_str.startswith("b") or "bom" in av_str or "excelente" in av_str else 0

    mem.db.execute("INSERT INTO feedback(ts, pergunta, resposta, avaliacao, comentario) VALUES(?,?,?,?,?)",
                   (time.time(), pergunta, resposta, boa, comentario))
    if ult.get("trace_id"):
        mem.db.execute("UPDATE tracos SET avaliacao=? WHERE id=?", (boa, ult["trace_id"]))
    mem.db.commit()
    pasta = Path(BASE) / "treino"
    pasta.mkdir(exist_ok=True)
    with open(pasta / "feedback.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps({"messages": [{"role": "user", "content": pergunta},
                                         {"role": "assistant", "content": resposta}],
                            "avaliacao": boa, "comentario": comentario}, ensure_ascii=False) + "\n")
    if not boa and comentario:
        mem.guardar(f"Preferência do utilizador sobre as respostas: {comentario}")
    return f"Avaliação registada ({'boa' if boa else 'má'}). Obrigado pelo feedback!"
