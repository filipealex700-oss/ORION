"""Teste local de modelos: vê qual escolhe melhor as ferramentas e quão rápido é no TEU PC.
python avaliar.py                      (usa o modelo_llm do config)
python avaliar.py llama3.1:8b qwen2.5:14b   (compara vários)"""
import sys
import time

import config
import tools
import gestao, codigo, autonomo, aprendizagem, routing  # noqa: F401,E401  (registam as ferramentas)
from brain import Cerebro

CASOS = [
    ("abre o chrome", "abrir_programa"), ("fecha o discord", "fechar_programa"),
    ("que horas são?", "hora_data"), ("como está o computador?", "estado_sistema"),
    ("limpa o meu ambiente de trabalho", "organizar_pasta"), ("pausa a música", "media"),
    ("baixa o volume", "ajustar_volume"), ("ativa o modo estudo", "ativar_modo"),
    ("adiciona a tarefa entregar o relatório até 2026-11-06", "adicionar_tarefa"),
    ("guarda que prefiro luz azul à noite", "guardar_memoria"),
    ("cria um script python que renomeia ficheiros", "criar_codigo"),
    ("todos os dias às 8h faz o resumo do dia", "agendar_job"),
    ("regista que comprei 10 ações da AAPL a 150", "registar_operacao"),
    ("olá, tudo bem?", None), ("o que é um buraco negro?", None),
]


class MemNula:
    def buscar(self, *a, **k):
        return []

    def historico_recente(self, n=8):
        return []


def correr(modelos, cfg):
    resumo = []
    for modelo in modelos:
        certos, tempos = 0, []
        print(f"\n=== {modelo} ===")
        for frase, esperado in CASOS:
            usadas = []

            def exec_(nome, args, usadas=usadas):
                usadas.append(nome)
                return "feito"

            c = Cerebro(cfg, MemNula(), tools.FERRAMENTAS, exec_, {"genero": "feminino"})
            t = time.time()
            try:
                c.responder(frase, modelo=modelo)
            except Exception as e:
                print(f"  ERRO ({e})")
            dt = time.time() - t
            obtido = usadas[0] if usadas else None
            ok = obtido == esperado
            certos += ok
            tempos.append(dt)
            print(f"  {'OK ' if ok else 'ERR'} {dt:5.1f}s  {frase!r} -> {obtido}  (esperado: {esperado})")
        resumo.append((modelo, certos, len(CASOS), sum(tempos) / len(tempos)))
    print("\nResumo:")
    for m, c, n, t in resumo:
        print(f"  {m}: {c}/{n} certos, {t:.1f}s por pedido")
    return resumo


if __name__ == "__main__":
    cfg = config.carregar()
    correr(sys.argv[1:] or [cfg["modelo_llm"]], cfg)
