"""Núcleo do ORION: junta voz, cérebro, memória, segundo plano e aprendizagem.
Comunica com a interface (janela ou consola) através de eventos: emitir(tipo, texto, **extra)
tipos: estado, ouvi, disse, acao, sistema, job, aprendi, voz, iniciado, erro, sair"""
import difflib
import os
import queue
import re
import threading
import time
import unicodedata

import ollama

import aprendizagem
import autonomo
import codigo  # noqa: F401  (regista as ferramentas de código)
import config
import gestao
import routing
import tools
from brain import Cerebro
from definicoes import Definicoes
from memory import Memoria
from skills import Skills
from voice import Voz


def norm(s):
    s = unicodedata.normalize("NFD", s.lower())
    return "".join(c for c in s if c and unicodedata.category(c) != "Mn")

def extrair_comando(texto, cfg):
    """Se a frase começar pelo nome do ORION devolve o resto ('' se só disse o nome); senão None."""
    variantes = {norm(v) for v in cfg["wake_variantes"]}
    alvo = norm(cfg["wake_word"])
    for i, m in enumerate(re.finditer(r"\w+", texto)):
        if i > 3:
            break
        t = norm(m.group(0))
        if t in variantes or difflib.SequenceMatcher(None, t, alvo).ratio() >= 0.75:
            return texto[m.end():].lstrip(" ,.!?;:-")
    return None


def verificar_ollama(cfg):
    try:
        instalados = {m.model for m in ollama.list().models}
    except Exception:
        raise RuntimeError("Não consegui ligar ao Ollama. Instala-o (ollama.com) e abre-o "
                           "(ícone junto ao relógio).")
    for chave in ("modelo_llm", "modelo_embeddings"):
        nome = cfg[chave]
        if nome not in instalados and f"{nome}:latest" not in instalados:
            raise RuntimeError(f"Falta o modelo '{nome}'. Corre no terminal:  ollama pull {nome}")


class Orion:
    def __init__(self, cfg, emitir, modo_texto=False):
        self.cfg, self.modo_texto = cfg, modo_texto
        self._emitir = emitir
        self.ativo = False
        self.fila = queue.Queue()
        self.parar_mic = threading.Event()
        self.ativo_ate = 0.0
        self.ultimo_uso = time.time()
        self.a_processar = False
        self.baixa = 0

    def emitir(self, tipo, texto="", **extra):
        try:
            self._emitir(tipo, texto, **extra)
        except Exception:
            pass

    # ------------------------------------------------------------ arranque
    def iniciar(self):
        cfg = self.cfg
        self.emitir("estado", "a carregar")
        verificar_ollama(cfg)
        instalados = {m.model for m in ollama.list().models}
        tem = lambda nome: nome in instalados or f"{nome}:latest" in instalados
        mc, mr = cfg.get("modelo_codigo"), cfg.get("modelo_rapido")
        if mc and not tem(mc):
            self.emitir("sistema", f"Falta o modelo de código '{mc}'. Para programar: ollama pull {mc}")
        # Rota rápida não precisa de modelo próprio: sem modelo_rapido usa o principal
        # com prompt curto (sem ferramentas) — mesmo modelo já carregado, sem troca de VRAM.
        rapido_ok = cfg.get("roteamento", True) and (not mr or tem(mr))
        if mr and not tem(mr):
            self.emitir("sistema", f"Rota rápida usa o modelo principal: falta '{mr}'.")
        self.defs = Definicoes(cfg)
        self.memoria = Memoria(os.path.join(config.BASE, "orion_memoria.db"), cfg["modelo_embeddings"])
        tools.CTX.update(cfg=cfg, memoria=self.memoria, defs=self.defs, ultima={})
        tools.carregar_plugins()
        self.voz = Voz(cfg, self.defs, self.memoria, self.emitir, modo_texto=self.modo_texto)
        tools.CTX["voz"] = self.voz
        try:
            skills = Skills(os.path.join(config.BASE, "skills"), self.memoria, cfg.get("skills_min_score", 0.55))
            if skills.itens:
                self.emitir("sistema", f"{len(skills.itens)} skill(s) carregada(s).")
        except Exception as e:
            skills = None
            self.emitir("sistema", f"Skills indisponíveis: {e}")
        self.router = routing.Router(cfg, self.memoria, rapido_ok)
        self.cerebro = Cerebro(cfg, self.memoria, tools.FERRAMENTAS, self._executar, self.defs, skills=skills)
        self.autonomo = autonomo.Autonomo(
            cfg, self.emitir,
            ocupado=lambda: self.a_processar or time.time() - self.ultimo_uso < 20,
            falar=self.voz.falar, criar_cerebro=self._cerebro_job, ocioso=self._ocioso)
        self.aprend = aprendizagem.Aprendizagem(cfg, self.memoria, self.emitir)
        import seguranca
        self.seg = seguranca.obter(cfg)
        tools.CTX.update(autonomo=self.autonomo, aprendizagem=self.aprend, seguranca=self.seg)
        self.seg.ao_alerta(lambda g, m: self.emitir("sistema", f"Alerta de segurança [{g}]: {m}"))
        self.seg.iniciar()
        self.ativo = True
        threading.Thread(target=self._loop, daemon=True, name="processamento").start()
        if not self.modo_texto:
            threading.Thread(target=self._mic, daemon=True, name="microfone").start()
        self.autonomo.iniciar()
        self.emitir("iniciado")

    def parar(self):
        self.ativo = False
        self.parar_mic.set()
        if hasattr(self, "seg"):
            self.seg.parar()
        if hasattr(self, "autonomo"):
            self.autonomo.parar()
        if hasattr(self, "voz"):
            self.voz.parar()

    def enviar_texto(self, texto):
        if texto.strip():
            self.fila.put({"texto": texto.strip(), "conf": 1.0, "origem": "teclado"})

    # ------------------------------------------------------------ ferramentas
    def _executar(self, nome, args):
        r = tools.executar(nome, args)
        try:
            self.memoria.registar_uso(nome, args)
        except Exception:
            pass
        self.emitir("acao", f"{nome}({args}) -> {r}")
        return r

    def _cerebro_job(self):
        ferr = {k: v for k, v in tools.FERRAMENTAS.items() if k in autonomo.PERMITIDAS}

        def exec_(nome, args):
            if nome not in autonomo.PERMITIDAS:
                return "Ferramenta não permitida em trabalhos automáticos."
            return tools.executar(nome, args)

        c = Cerebro(self.cfg, self.memoria, ferr, exec_, self.defs,
                    extra="Está a executar um trabalho agendado SEM o utilizador presente. Faça o trabalho "
                          "com as ferramentas permitidas e responda com um relatório de 2 a 4 frases.")
        c.hist = []
        return c

    def _ocioso(self):
        if not self.a_processar and time.time() - self.ultimo_uso > 120:
            self.aprend.ciclo()

    # ------------------------------------------------------------ threads
    def _mic(self):
        while self.ativo:
            try:
                r = self.voz.ouvir(self.parar_mic)
            except Exception as e:
                self.emitir("sistema", f"Erro no reconhecimento: {e}")
                time.sleep(1)
                continue
            if r:
                r["origem"] = "voz"
                self.fila.put(r)
            elif not self.a_processar:
                self.emitir("estado", "pronto")

    def _loop(self):
        self._saudacao()
        while self.ativo:
            try:
                it = self.fila.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                self._tratar(it)
            except Exception as e:
                self.emitir("sistema", f"Erro interno: {e}")
                self.a_processar = False
                self.emitir("estado", "pronto")

    def _janela(self):
        self.ativo_ate = time.time() + self.cfg["janela_conversa_seg"]

    def _saudacao(self):
        fem = self.defs["genero"] == "feminino"
        pend = list(tools.PENDENTES.glob("*.py")) if tools.PENDENTES.exists() else []
        msg = f"Sistemas online. {'Pronta' if fem else 'Pronto'} para ajudar, {self.cfg['tratamento']}."
        if pend:
            msg += f" Tenho {len(pend)} ferramenta(s) à espera de aprovação."
        resumo = gestao.briefing_arranque()
        if resumo:
            msg += f" {resumo}"
        rel = self.autonomo.relatorio_pendente()
        if rel:
            msg += f" {rel}"
        self.emitir("estado", "a falar")
        self.voz.falar(msg)
        self.emitir("estado", "pronto")

    # ------------------------------------------------------------ tratamento de uma frase
    def _tratar(self, it):
        texto, conf, origem = it["texto"], it.get("conf", 1.0), it["origem"]
        ativa = origem == "teclado" or time.time() < self.ativo_ate
        comando = extrair_comando(texto, self.cfg)
        self.emitir("ouvi", texto, conf=conf, origem=origem, ignorado=(comando is None and not ativa))
        if comando is None:
            if not ativa:
                self.emitir("estado", "pronto")
                return
            comando = texto
        self.ultimo_uso = time.time()
        if comando == "":
            self.emitir("estado", "a falar")
            self.voz.falar("Sim?")
            self._janela()
            self.emitir("estado", "pronto")
            return
        n = norm(comando)
        if any(norm(f) in n for f in self.cfg["frases_sair"]):
            self.voz.falar("Até breve. A desligar.")
            self.emitir("sair")
            self.parar()
            return
        # percebeu mal? pede para repetir (no máximo 2 vezes seguidas)
        if (origem == "voz" and conf < self.cfg.get("confianca_minima", 0.45)
                and self.baixa < 2 and len(comando.split()) >= 2):
            self.baixa += 1
            self.emitir("estado", "a falar")
            self.voz.falar("Não percebi bem. Pode repetir, por favor?")
            self._janela()
            self.emitir("estado", "pronto")
            return
        self.baixa = 0
        # confirmação de ações sensíveis
        if tools.PENDENTE["fn"]:
            if re.search(r"\b(sim|confirmo|avanca|pode|executa|faz)\b", n):
                self.emitir("estado", "a pensar")
                res = tools.resolver_confirmacao(True)
                self.emitir("estado", "a falar")
                self.voz.falar("A executar. " + res[:400])
                self._janela()
                self.emitir("estado", "pronto")
                return
            if re.search(r"\b(nao|cancela|cancelar|deixa)\b", n):
                self.voz.falar(tools.resolver_confirmacao(False))
                self._janela()
                self.emitir("estado", "pronto")
                return
            tools.resolver_confirmacao(False)  # mudou de assunto: cancela
        self.a_processar = True
        try:
            self.emitir("estado", "a pensar")
            tools.CTX["pedido_atual"] = comando
            decisao = self.router.escolher(comando, self.cerebro.hist)
            rota = decisao["rota"]
            modelo = decisao["modelo"]
            com_f = decisao["ferramentas"]
            extra_rota = decisao.get("extra", "")
            resposta = self.cerebro.responder(comando, modelo=modelo, com_ferramentas=com_f,
                                              extra_rota=extra_rota, somente=decisao.get("somente"))
            meta = self.cerebro.ultimo
            lat = meta.get("latencia", 0.0)
            mod_usado = meta.get("modelo", modelo)
            self.emitir("acao", f"[rota {rota} · {mod_usado} · {lat:.1f}s"
                                + (f" · skill {meta['skill']}" if meta.get("skill") else "") + "]")
            tid = self.memoria.registar_traco(comando, rota, mod_usado, meta.get("ferramentas", []), lat)
            self.memoria.registar("user", comando)
            self.memoria.registar("assistant", resposta)
            tools.CTX["ultima"] = {"pergunta": comando, "resposta": resposta, "trace_id": tid}
            self.emitir("estado", "a falar")
            self.voz.falar(resposta)
            self._anuncios()
        finally:
            self.a_processar = False
            self.ultimo_uso = time.time()
            self._janela()
            self.emitir("estado", "pronto")

    def _anuncios(self):
        """Depois de responder: conta o que fez em segundo plano e sugere hábitos aprendidos."""
        for texto in (self.autonomo.relatorio_pendente(),):
            if texto:
                self.cerebro.hist.append({"role": "assistant", "content": texto})
                self.voz.falar(texto)
        s = self.aprend.sugestao_nova()
        if s:
            self.cerebro.hist.append({"role": "assistant", "content": s[1]})
            self.voz.falar(s[1])
