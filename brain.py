"""Cérebro: LLM local (Ollama) + persona JARVIS (feminina ou masculina) + ferramentas + skills."""
import datetime
import json
import re
import time

import numpy as np
import ollama

from routing import CORE as FERRAMENTAS_CORE

DIAS = ["segunda-feira", "terça-feira", "quarta-feira", "quinta-feira",
        "sexta-feira", "sábado", "domingo"]

REGRAS = """REGRAS:
- Use no máximo uma ferramenta por passo. Depois de receber o resultado, responda com "acao": null.
- Nunca diga que fez algo sem ter chamado a ferramenta correspondente.
- Se o utilizador disser uma preferência ou facto pessoal duradouro, use guardar_memoria.
- Datas nas ferramentas vão sempre no formato AAAA-MM-DD; converta "amanhã", "sexta" etc. com base na data atual.
- Pedidos de programação: use criar_codigo ou editar_codigo e NUNCA leia código em voz alta; diga só o que fez.
- executar_codigo só corre depois de o utilizador confirmar; peça-lhe a confirmação numa frase.
- Trabalho que deva correr sem o utilizador presente ou a horas certas: use agendar_job (ou agendar_lembrete para avisos).
- Se o utilizador disser que percebeu mal o que ele disse ("não disse X, disse Y"), use corrigir_reconhecimento.
- Se o utilizador elogiar ou criticar a sua última resposta, use avaliar_resposta.
- Se pedir para mudar de voz (homem/mulher), use mudar_genero; se pedir para falar mais devagar ou depressa, ajustar_fala.
- Investimentos: dê apenas dados e cálculos da carteira. Nunca recomende comprar ou vender; se pedirem opinião,
  diga que não é consultor financeiro e indique fatores a ponderar. Os preços são os que o utilizador registou.
- Não invente ferramentas.
- ANTES de responder a perguntas sobre projetos, tarefas, ideias ou informações que possam estar no Obsidian,
  use obsidian_ler para verificar notas relevantes. Se a informação for útil, use obsidian_escrever ou obsidian_adicionar
  para guardar no Obsidian.
- Se o utilizador pedir para ler um ficheiro ou ver o conteúdo de um ficheiro, use ler_ficheiro com o caminho completo.
- Se o utilizador pedir para listar ficheiros numa pasta, use listar_pasta com o caminho da pasta.
- Após receber uma avaliação negativa (1-2), use treinar_reconhecimento para melhorar automaticamente.
- Para perguntas sobre informação atualizada da internet (preços, notícias, dados recentes, estatísticas),
  use pesquisar_web_resultados para abrir o navegador, ou langflow_aprender para pesquisa mais profunda.
- Para perguntas de cultura geral, actualidade ou sempre que não tiver a informação, use pesquisar_respostas:
  vai à procura da resposta real como um assistente completo (estilo Gemini). Se precisar de mais detalhe,
  use ler_pagina_web com um dos URLs encontrados.
- PESQUISE SEMPRE que a pergunta envolver informação que muda com o tempo, mesmo que pense que sabe:
  "atual", "agora", "este ano", "recentemente", "quem ganhou", resultados desportivos, eleições,
  preços, cotações, notícias, dados de 2024 em diante ou qualquer facto posterior aos seus treinos.
  O seu conhecimento pode estar desatualizado — a pesquisa é a fonte da verdade.
- Nunca invente factos, preços ou notícias. Se a pesquisa não trouxer resposta clara, diga honestamente
  o que encontrou ou que não conseguiu confirmar.
- Se o utilizador pedir para aprender algo novo ou aprofundar um tópico, use langflow_aprender.
- Se não perceber o pedido do utilizador, tente interpretar o contexto e dê a melhor resposta possível.
  Se ainda assim não souber, diga "Não entendi bem, pode repetir?" em vez de inventar."""


# Perguntas que precisam SEMPRE de dados atuais/pesquisa (detetor determinístico:
# os LLMs locais ignoram a regra quando o histórico mostra respostas diretas).
PRECISA_PESQUISA = re.compile(
    r"\b(pre[cç]o|pre[cç]os|cotac|not[ií]cia|not[ií]cias|atual|atuais|agora|recent|"
    r"quem ganhou|quem vence|resultado|resultados|elei[cç]|presidente|bitcoin|"
    r"cripto|ethereum|a[cç][oõ]es|bolsa|meteorologia|clima|tempo para|"
    r"lan[cç]amento|estreia|temporada|campe[aã]o|mundial|eurovis[aã]o)\b", re.I)


class Cerebro:
    def __init__(self, cfg, memoria, ferramentas, executar, defs, extra="", skills=None):
        self.cfg, self.mem, self.defs = cfg, memoria, defs
        self.ferramentas, self.executar, self.extra, self.skills = ferramentas, executar, extra, skills
        self.hist = memoria.historico_recente(4)  # Reduzido de 8 para 4
        self.max_hist = 3  # Reduzido de 6 para 3
        self.ultimo = {}
        self._tool_embs = None

    def _sistema(self, memorias, com_ferramentas=True, skill=None, extra_rota="", somente=None):
        c = self.cfg
        fem = self.defs.get("genero", "feminino") == "feminino"
        o = "a" if fem else "o"
        agora = datetime.datetime.now()
        mem_txt = "\n".join(f"- {m}" for m in memorias[:2]) or "(nenhuma)"

        # Otimização extrema: prompt ultra-curto
        topo = f"Você é {o} {c['nome']}. Trate o utilizador por \"{c['tratamento']}\"."
        topo += (f" Data: {DIAS[agora.weekday()]}, {agora:%d/%m/%Y}. Hora: {agora:%H:%M}."
                 " Responda em 1-2 frases em português de Portugal.")
        topo += f" {self.extra} {extra_rota}"

        if not com_ferramentas:
            return topo + f"\nMemórias: {mem_txt}\nResponda com JSON: {{\"fala\": \"...\", \"acao\": null}}"

        itens = self.ferramentas.items() if somente is None else \
            ((n, f) for n, f in self.ferramentas.items() if n in somente)
        lista = []
        for nome, f in itens:
            lista.append(f"- {nome}: {f['descricao']}")

        return f"""{topo}
Memórias: {mem_txt}

Ferramentas:
{chr(10).join(lista[:8])}

Responda com JSON: {{"fala": "...", "acao": {{"nome": "...", "args": {{...}}}}}}
Use ferramentas apenas se necessário."""

    @staticmethod
    def _parse(bruto):
        try:
            return json.loads(bruto)
        except Exception:
            m = re.search(r"\{.*\}", bruto, re.S)
            if m:
                try:
                    return json.loads(m.group(0))
                except Exception:
                    pass
        return {"fala": bruto.strip(), "acao": None}

    def _ferramentas_relevantes(self, texto, k=16):
        """Seleção dinâmica: embeddings do pedido -> só as k ferramentas mais relevantes
        (+ as core). Prompt muito mais pequeno = resposta mais rápida.
        Usa cache Rust de embeddings para performance extrema."""
        try:
            if self._tool_embs is None:
                # Calcular embeddings das ferramentas uma única vez (com cache Rust)
                self._tool_embs = {n: self.mem._emb(f"{n}. {f['descricao']}")
                                   for n, f in self.ferramentas.items()}
            q = self.mem._emb(texto)  # Cache Rust acelera isto dramaticamente
            scores = sorted(((float(np.dot(q, e)), n) for n, e in self._tool_embs.items()),
                            reverse=True)
            return {n for _, n in scores[:k]} | FERRAMENTAS_CORE
        except Exception:
            return None  # sem embeddings: mostra todas (fallback seguro)

    def responder(self, texto, modelo=None, com_ferramentas=True, extra_rota="", somente=None):
        modelo = modelo or self.cfg["modelo_llm"]
        t0, usadas = time.time(), []

        # Otimização extrema: sem memória para perguntas curtas
        if len(texto.split()) < 4:
            memorias = []
        else:
            memorias = self.mem.buscar(texto)

        skill = None
        if com_ferramentas and self.skills:
            try:
                skill = self.skills.buscar(texto)
            except Exception:
                skill = None

        # Otimização extrema: sem seleção de ferramentas para perguntas simples
        if com_ferramentas and somente is None:
            if len(texto.split()) < 6:
                somente = FERRAMENTAS_CORE
            else:
                somente = self._ferramentas_relevantes(texto, k=4)

        entrada = texto
        if com_ferramentas and PRECISA_PESQUISA.search(texto):
            if re.search(r"bitcoin|ethereum|criptomoeda|cripto|altcoin|dogecoin|solana|binance", texto, re.I):
                ferramenta_dados = "preco_cripto"
            else:
                ferramenta_dados = "pesquisar_respostas"
            entrada += (f"\n[INSTRUÇÃO INTERNA: esta pergunta precisa de dados atuais ou de"
                        f" conhecimento que pode estar desatualizado — chame {ferramenta_dados}"
                        " antes de responder.]")

        msgs = ([{"role": "system", "content": self._sistema(memorias, com_ferramentas, skill, extra_rota, somente)}]
                + self.hist[-2:]  # Apenas 2 mensagens de histórico
                + [{"role": "user", "content": entrada}])

        fala = ""
        # 2 iterações: a 2ª usa o resultado da ferramenta na resposta final
        for _ in range(2):
            try:
                ctx = 512 if not com_ferramentas else self.cfg.get("contexto", 256)
                r = ollama.chat(model=modelo, messages=msgs, format="json",
                                options={"temperature": 0.0, "num_ctx": ctx, "num_predict": 160},
                                keep_alive=self.cfg.get("keep_alive", "30m"))
                bruto = r["message"]["content"]
            except Exception as e:
                fala = f"Ocorreu um erro ao comunicar com o modelo '{modelo}': {e}"
                self.hist += [{"role": "user", "content": texto}, {"role": "assistant", "content": fala}]
                self.ultimo = {"modelo": modelo, "ferramentas": usadas, "latencia": time.time() - t0,
                               "skill": skill[0] if skill else None}
                return fala
            dados = self._parse(bruto)
            fala = dados.get("fala") or fala
            acao = dados.get("acao")
            if not com_ferramentas:
                break
            if not isinstance(acao, dict) or not acao.get("nome"):
                break
            nome, args = acao["nome"], acao.get("args") or {}
            usadas.append(nome)
            resultado = self.executar(nome, args)
            msgs.append({"role": "assistant", "content": bruto})
            msgs.append({"role": "user", "content":
                         f"[RESULTADO DA FERRAMENTA {nome}] {resultado}\n"
                         "Responda agora ao utilizador com acao null."})
        fala = fala or ("Feito." if com_ferramentas else "Peço desculpa, não consegui responder. Pode repetir?")
        if fala.lower() in ["não entendi", "nao entendi", "não compreendi", "nao compreendi"]:
            fala = "Peço desculpa, não consegui perceber bem. Pode repetir ou explicar de outra forma?"
        self.hist += [{"role": "user", "content": texto}, {"role": "assistant", "content": fala}]
        self.ultimo = {"modelo": modelo, "ferramentas": usadas, "latencia": time.time() - t0,
                       "skill": skill[0] if skill else None}
        return fala
