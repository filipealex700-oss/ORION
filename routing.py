"""Router multi-modelo (ORION-Support, principal, ORION-Coder, ORION-Sec, ORION-Fin) + VRAM Saver + métricas.
Cada pedido é classificado por palavras-chave numa rota especializada; cada rota tem modelo, ferramentas e
instruções próprias (configuráveis em config.json > "rotas"). Com pouca VRAM (ex.: 6 GB), o modelo anterior
é descarregado da placa antes de carregar outro, para não haver troca lenta para a RAM."""
import os
import pickle
import re
import unicodedata

import numpy as np
import ollama

from config import BASE
from tools import CTX, ferramenta

ACAO = {"abre", "abrir", "fecha", "fechar", "cria", "criar", "edita", "editar", "corrige", "organiza",
        "limpa", "agenda", "lembra", "guarda", "guardar", "esquece", "muda", "liga", "desliga", "executa",
        "pesquisa", "modo", "tarefa", "tarefas", "candidatura", "resumo", "trabalho", "job", "volume",
        "lembrete", "ficheiro", "pasta", "voz", "velocidade", "devagar", "musica", "pausa", "toca",
        "depressa", "avalia", "disse", "aprende", "ensina", "hora", "horas", "data", "computador",
        "sistema", "estado", "cancela", "lista", "mostra", "regista", "atualiza", "adiciona", "conclui",
        "obsidian", "nota", "notas", "langflow", "luz", "luzes", "cena"}
CURTAS = {"sim", "nao", "pode", "claro", "ok", "confirmo", "avanca", "faz", "talvez"}
PALAVRAS = {
    "codigo": {"codigo", "script", "programa", "programar", "funcao", "bug", "erro", "python", "javascript",
               "html", "arduino", "esp32", "compila", "refatora", "teste", "testes", "classe", "api", "git", "commit"},
    "seguranca": {"seguranca", "ransomware", "virus", "malware", "ataque", "intrusao", "alerta", "alertas",
                  "backup", "copia", "watchdog", "auditoria", "segredo", "segredos", "palavra-passe", "password",
                  "firewall", "rede", "protegido", "protegidas", "sandbox", "integridade"},
    "financas": {"carteira", "acoes", "compra", "comprei", "vende", "vendi", "preco", "precos", "etf",
                 "cripto", "bitcoin", "orcamento", "custos", "custo", "fatura", "faturas", "stripe", "paypal",
                 "receita", "lucro", "investimento", "investimentos", "dividendos", "arr", "saas"},
}
CORE = {"guardar_memoria", "esquecer_memoria", "hora_data", "avaliar_resposta",
        "corrigir_reconhecimento", "ensinar_palavra", "treinar_reconhecimento",
        "responder_sugestao", "mudar_genero", "ajustar_fala"}
ROTAS = {
    "rapido": {"nome": "ORION-Support", "descricao": "Conversa simples: prompt curto, sem ferramentas.",
               "chave_modelo": "modelo_rapido", "ferramentas": False, "extra": "",
               "somente": None},
    "principal": {"nome": "ORION Principal", "descricao": "Ações no PC, casa, memória e Obsidian.",
                  "chave_modelo": "modelo_llm", "ferramentas": True, "extra": "",
                  "somente": None},
    "codigo": {"nome": "ORION-Coder", "descricao": "Programação com IA Juiz (gerador, crítico, juiz).",
               "chave_modelo": "modelo_llm", "ferramentas": True,
               "somente": CORE | {"criar_codigo", "editar_codigo", "rever_codigo", "ler_codigo",
                                  "listar_projetos", "executar_codigo", "ler_ficheiro", "listar_pasta",
                                  "obsidian_ler", "obsidian_escrever", "obsidian_adicionar"},
               "extra": "MODO ORION-CODER: o pedido é de programação. Use criar_codigo, editar_codigo, "
                        "rever_codigo ou ler_codigo. Cada ficheiro passa pela IA Juiz; diga o veredicto numa frase."},
    "seguranca": {"nome": "ORION-Sec", "descricao": "Estado do watchdog, alertas, auditoria e backups.",
                  "chave_modelo": "modelo_llm", "ferramentas": True,
                  "somente": CORE | {"estado_seguranca", "verificar_integridade", "criar_backup",
                                     "estado_sistema", "ler_ficheiro", "listar_pasta"},
                  "extra": "MODO ORION-SEC: o pedido é de segurança. Use estado_seguranca, verificar_integridade "
                           "ou criar_backup. Seja factual, não invente ameaças, e nunca revele segredos."},
    "financas": {"nome": "ORION-Fin", "descricao": "Carteira e custos, só dados e simulação.",
                 "chave_modelo": "modelo_llm", "ferramentas": True,
                 "somente": CORE | {"ver_carteira", "registar_operacao", "atualizar_preco",
                                    "preco_cripto", "pesquisar_respostas", "listar_candidaturas",
                                    "adicionar_candidatura", "atualizar_candidatura"},
                 "extra": "MODO ORION-FIN (simulação): use ver_carteira e as ferramentas de carteira. Dê só dados "
                          "e cálculos. Nunca recomende comprar ou vender e nunca movimente dinheiro real."},
}


class DecisaoRota(dict):
    """Permite aceder como dict r['rota'] ou desempacotar como (rota, modelo, ferramentas)."""
    def __iter__(self):
        yield self["rota"]
        yield self["modelo"]
        yield self["ferramentas"]


def _norm(s):
    s = unicodedata.normalize("NFD", s.lower())
    return "".join(c for c in s if c and unicodedata.category(c) != "Mn")


def rotas_config(cfg):
    """Rotas com o modelo efetivo (config.json > rotas > <id> > modelo sobrepõe)."""
    out = {}
    for rid, r in ROTAS.items():
        extra_cfg = (cfg.get("rotas") or {}).get(rid, {})
        modelo = extra_cfg.get("modelo") or cfg.get(r["chave_modelo"]) or cfg["modelo_llm"]
        out[rid] = {**r, "id": rid, "modelo": modelo, "extra": extra_cfg.get("extra", r["extra"])}
    return out


def classificar(cfg, texto, hist=None, rapido_ok=True):
    """-> DecisaoRota(rota, modelo, ferramentas, extra, motivo)"""
    rotas = rotas_config(cfg)
    toks = re.findall(r"[\w-]+", _norm(texto))
    conj = set(toks)
    pont = {rid: len(conj & pal) for rid, pal in PALAVRAS.items()}
    melhor = max(pont, key=pont.get)

    def sair(rid, motivo):
        r = rotas[rid]
        return DecisaoRota({"rota": rid, "nome": r["nome"], "modelo": r["modelo"], "ferramentas": r["ferramentas"],
                            "somente": r.get("somente"), "extra": r["extra"], "motivo": motivo})

    if pont[melhor] > 0:
        pal = ", ".join(sorted(conj & PALAVRAS[melhor]))
        return sair(melhor, f"palavras de {rotas[melhor]['nome']}: {pal}")
    if not rapido_ok or not cfg.get("roteamento", True):
        return sair("principal", "rota rápida indisponível")
    if len(toks) > 20:  # Aumentado de 14 para 20
        return sair("principal", "frase longa")
    if any(t in ACAO or t.isdigit() for t in toks):
        return sair("principal", "pedido de ação")
    # Respostas curtas agora usam rota rápida
    if toks and conj <= CURTAS:
        return sair("rapido", "resposta curta")
    if hist and hist[-1]["role"] == "assistant" and hist[-1]["content"].rstrip().endswith("?"):
        return sair("rapido", "respondendo a pergunta")
    return sair("rapido", "conversa simples")


# ---------------- router neuronal (sem palavras-chave) ----------------
_NN = None
_NN_TENTADO = False
NN_MODELO = os.path.join(BASE, "modelos", "router_nn.pkl")
NN_LIMIAR = 0.55  # probabilidade mínima para a rede decidir sozinha


def _carregar_nn():
    """Carrega o MLP treinado por treinar_router.py (uma vez)."""
    global _NN, _NN_TENTADO
    if _NN_TENTADO:
        return _NN
    _NN_TENTADO = True
    try:
        if os.path.exists(NN_MODELO):
            with open(NN_MODELO, "rb") as f:
                d = pickle.load(f)
            if d.get("n", 0) >= 40:
                _NN = d
    except Exception:
        _NN = None
    return _NN


def _emb_nn(cfg, texto):
    v = ollama.embed(model=cfg.get("modelo_embeddings", "nomic-embed-text"),
                     input=texto[:500], keep_alive="10m")["embeddings"][0]
    a = np.array(v, dtype=np.float32)
    n = np.linalg.norm(a)
    return (a / n if n else a).reshape(1, -1)


def rota_neural(cfg, texto):
    """-> (rota, probabilidade) ou None se a rede não existir/não tiver confiança."""
    nn = _carregar_nn()
    if not nn:
        return None
    try:
        proba = nn["modelo"].predict_proba(_emb_nn(cfg, texto))[0]
        i = int(np.argmax(proba))
        return nn["classes"][i], float(proba[i])
    except Exception:
        return None


class Router:
    def __init__(self, cfg, memoria, rapido_ok):
        self.cfg, self.mem = cfg, memoria
        self.rapido_ok = rapido_ok and cfg.get("roteamento", True)
        self.modelo_atual = None

    def escolher(self, texto, hist):
        ativa = self.mem.meta_get("rota_rapida_ativa", "1") == "1"
        rotas = rotas_config(self.cfg)
        kw = classificar(self.cfg, texto, hist, self.rapido_ok and ativa)

        # 1) rotas especializadas: as palavras-chave são precisas aqui — ganham à rede
        if kw["rota"] in ("codigo", "seguranca", "financas"):
            self.poupar_vram(kw["modelo"])
            return kw

        # 2) rede neural: percebe a intenção sem palavras-chave (rapido vs principal vs especialista)
        nn = rota_neural(self.cfg, texto)
        if nn:
            rid, conf = nn
            if conf >= NN_LIMIAR:
                if rid == "rapido":
                    # portão de segurança: a rota sem ferramentas nunca pode ficar
                    # com pedidos de ação/frases longas (regra pragmática, não semântica)
                    rid = kw["rota"] if kw["rota"] == "principal" else "rapido"
                if rid == "rapido" and not (self.rapido_ok and ativa):
                    rid = "principal"
                r = rotas[rid]
                self.poupar_vram(r["modelo"])
                return DecisaoRota({"rota": rid, "nome": r["nome"], "modelo": r["modelo"],
                                    "ferramentas": r["ferramentas"], "somente": r.get("somente"),
                                    "extra": r["extra"], "motivo": f"rede neural ({conf:.0%})"})

        # 3) fallback: classificador por palavras-chave + regras
        self.poupar_vram(kw["modelo"])
        return kw

    def poupar_vram(self, modelo):
        """VRAM Saver: com <= 8 GB descarrega o modelo anterior da placa antes de trocar."""
        anterior, self.modelo_atual = self.modelo_atual, modelo
        if not anterior or anterior == modelo or float(self.cfg.get("vram_gb", 6)) > 8:
            return
        try:
            ollama.generate(model=anterior, prompt="", keep_alive=0)
        except Exception:
            pass


def modelos_carregados():
    """-> [{nome, vram_gb, ram_gb}] do `ollama ps`."""
    try:
        out = []
        for m in ollama.ps().models:
            total, vram = (m.size or 0) / 2**30, (m.size_vram or 0) / 2**30
            out.append({"nome": m.model, "vram_gb": round(vram, 2), "ram_gb": round(max(0, total - vram), 2)})
        return out
    except Exception:
        return None


def reavaliar(mem):
    """Aprendizagem do roteamento: desliga a rota rápida se as respostas dela forem mal avaliadas."""
    n, media = mem.db.execute("SELECT COUNT(avaliacao), AVG(avaliacao) FROM tracos "
                              "WHERE rota='rapido' AND avaliacao IS NOT NULL").fetchone()
    if mem.meta_get("rota_rapida_ativa", "1") == "1" and n >= 5 and (media or 0) < 0.5:
        mem.meta_set("rota_rapida_ativa", "0")
        return "Desativei a rota rápida: as respostas dela foram mal avaliadas."
    return ""


def metricas_rotas(db):
    rows = db.execute("SELECT rota, COUNT(*), AVG(latencia), AVG(avaliacao), COUNT(avaliacao) "
                      "FROM tracos GROUP BY rota").fetchall()
    return {r: {"pedidos": n, "latencia": lat, "avaliacao": av, "avaliados": k} for r, n, lat, av, k in rows}


@ferramenta("ver_metricas", "Mostra métricas: pedidos, latência média e avaliações por rota, e ferramentas mais usadas.")
def ver_metricas():
    db = CTX["memoria"].db
    m = metricas_rotas(db)
    if not m:
        return "Ainda não há dados."
    partes = [f"rota {r}: {d['pedidos']} pedidos, {d['latencia']:.1f}s em média" +
              (f", {d['avaliacao'] * 100:.0f}% bem avaliados ({d['avaliados']})" if d["avaliados"] and d["avaliacao"] else "")
              for r, d in m.items()]
    uso = db.execute("SELECT ferramenta, COUNT(*) c FROM uso GROUP BY ferramenta ORDER BY c DESC LIMIT 3").fetchall()
    if uso:
        partes.append("mais usadas: " + ", ".join(f"{f} ({c})" for f, c in uso))
    ativa = CTX["memoria"].meta_get("rota_rapida_ativa", "1") == "1"
    return "; ".join(partes) + f"; rota rápida {'ligada' if ativa else 'desligada'}."


@ferramenta("rota_rapida", "Liga ou desliga a rota rápida (modelo pequeno para conversa simples).",
            {"estado": "ligar | desligar"})
def rota_rapida(estado):
    on = str(estado).lower().startswith("l")
    CTX["memoria"].meta_set("rota_rapida_ativa", "1" if on else "0")
    return f"Rota rápida {'ligada' if on else 'desligada'}."
