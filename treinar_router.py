"""Treina a rede neuronal do router do ORION.

Um classificador (regressão logística = rede neuronal linear) sobre embeddings
nomic-embed-text aprende a classificar o PEDIDO em rotas (rapido, principal,
codigo, seguranca, financas) por semântica — não por palavras-chave. Dados: tracos reais (orion_memoria.db) + exemplos
semânticos para classes com poucos dados. Resultado: modelos/router_nn.pkl
"""
import os
import pickle
import sqlite3
import sys
import time

import numpy as np
import ollama
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import cross_val_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config  # noqa: E402

ROTAS = ["rapido", "principal", "codigo", "seguranca", "financas"]
SAIDA = os.path.join(config.BASE, "modelos", "router_nn.pkl")

# Exemplos semânticos por rota (reforçam classes com poucos dados reais)
SEMENTES = {
    "rapido": [
        "bom dia, como estás?", "conta-me uma anedota", "o que achas de futebol?",
        "gostavas de ser humana?", "sabes tocar piano?", "que música ouves?",
        "preferes praia ou montanha?", "o que é a felicidade para ti?",
        "dizes-me uma palavra em latim", "achas que os gatos são melhores que os cães?",
        "estou entediado", "que livros me recomendarias?", "consegues imitar o voz do gervásio?",
        "fazes anos este mês?", "o que é que tu sonhas?", "achas que extraterrestres existem?",
    ],
    "principal": [
        "abre o spotify", "que tarefas tenho pendentes?", "guarda que prefiro café sem açúcar",
        "faz um resumo do meu dia", "como está o tempo para amanhã?",
        "pesquisa o preço do bitcoin", "cria uma nota no obsidian sobre o projeto",
        "desliga a luz do quarto", "agenda um lembrete para as 18 horas",
        "lista os ficheiros da pasta downloads", "qual é a previsão do tempo para o fim de semana?",
        "procura na internet quanto custa um voo para Paris", "mostra as métricas do sistema",
        "apaga o ficheiro temporário", "organiza a minha secretária", "liga o computador ao telemóvel",
        "quanto tempo falta para o fim do mês?", "olá orion", "podes falar mais devagar?",
    ],
    "codigo": [
        "cria um script python que organiza fotografias", "corrige o erro no meu programa",
        "escreve um código arduino para acender um led", "faz uma função que calcula a média",
        "explica o que faz este código", "cria um bot em javascript",
        "o meu script dá erro de sintaxe", "refatora este programa",
        "programa um jogo simples em python", "faz um html com um formulário",
        "o python não corre o meu ficheiro", "cria um executável a partir do script",
        "como instalo as dependências do projeto?", "melhora o desempenho deste algoritmo",
        "traduz este código de javascript para python",
    ],
    "seguranca": [
        "está tudo bem com a segurança do sistema?", "verifica se algum ficheiro foi alterado",
        "há algum alerta de segurança?", "faz um backup dos documentos",
        "o watchdog detetou alguma intrusão?", "audita as permissões da pasta",
        "está o firewall ativo?", "mostra o estado da proteção",
        "alguém tentou aceder ao meu pc?", "verifica a integridade dos backups",
        "há processos suspeitos a correr?", "quais as últimas ações de segurança?",
        "protege esta pasta contra alterações", "revê os acessos à rede",
    ],
    "financas": [
        "como está a minha carteira de ações?", "regista que comprei 10 ações da microsoft",
        "qual foi o lucro este mês?", "adiciona um custo de 15 euros de netflix",
        "quanto investi em etfs?", "vendi as minhas ações da apple",
        "faz uma simulação com 1000 euros", "quais são os meus custos fixos?",
        "regista dividendo de 50 euros", "como se comportou o bitcoin?",
        "quanto gastei este mês?", "atualiza o preço das minhas ações",
        "quero comprar mais etf, simula", "quanto tenho em criptomoedas?",
        "regista uma receita de 2000 euros", "qual a rentabilidade da carteira?",
    ],
}


def _embs(textos, modelo):
    out = []
    for i in range(0, len(textos), 32):
        out += ollama.embed(model=modelo, input=textos[i:i + 32])["embeddings"]
    return np.array(out, dtype=np.float32)


def _norm(a):
    n = np.linalg.norm(a, axis=1, keepdims=True)
    return a / np.where(n == 0, 1, n)


def main():
    cfg = config.carregar()
    db = sqlite3.connect(os.path.join(config.BASE, "orion_memoria.db"))
    rows = db.execute("SELECT pergunta, rota FROM tracos WHERE pergunta IS NOT NULL AND rota IS NOT NULL").fetchall()
    X_txt, y = [], []
    for p, r in rows:
        p = p.strip()
        if p and r in ROTAS:
            X_txt.append(p[:400])
            y.append(r)
    for r, exemplos in SEMENTES.items():
        for e in exemplos:
            X_txt.append(e)
            y.append(r)
    print(f"{len(X_txt)} exemplos ({len(rows)} reais + sementes)")

    t = time.time()
    E = _norm(_embs(X_txt, cfg["modelo_embeddings"]))
    print(f"embeddings em {time.time() - t:.1f}s")

    idx = {r: i for i, r in enumerate(ROTAS)}
    yi = np.array([idx[r] for r in y])

    # Regressão logística = rede neuronal de uma camada; com ~200 exemplos
    # generaliza melhor que um MLP profundo (testado: 52% vs 38-49% CV).
    clf = make_pipeline(StandardScaler(),
                        LogisticRegression(max_iter=3000, C=0.5, random_state=7))
    acc = cross_val_score(clf, E, yi, cv=5).mean()
    print(f"accuracy CV (5-fold): {acc:.2%}")
    clf.fit(E, yi)

    os.makedirs(os.path.dirname(SAIDA), exist_ok=True)
    with open(SAIDA, "wb") as f:
        pickle.dump({"modelo": clf, "classes": ROTAS, "n": len(X_txt),
                     "acc_cv": float(acc)}, f)
    print(f"guardado em {SAIDA}")


if __name__ == "__main__":
    main()
