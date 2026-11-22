"""Testa a latência do sistema de embeddings e busca vetorial.
Compara implementação Python (ollama) vs Rust (cache + HNSW)."""
import time
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config
from memory import Memoria, RUST_AVAILABLE

def testar_cache_hits(memoria, textos_teste):
    """Testa taxa de cache hit com múltiplas chamadas repetidas."""
    print("\n=== Teste de Cache Hit ===")
    t0 = time.time()
    for texto in textos_teste:
        memoria._emb(texto)
    primeira_vez = time.time() - t0

    t0 = time.time()
    for texto in textos_teste * 3:  # 3x repetido
        memoria._emb(texto)
    com_cache = time.time() - t0

    print(f"Primeira vez ({len(textos_teste)} embeddings): {primeira_vez:.3f}s")
    print(f"Com cache ({len(textos_teste) * 3} embeddings): {com_cache:.3f}s")
    print(f"Speedup: {primeira_vez / com_cache:.2f}x")

def testar_busca(memoria, consultas):
    """Testa latência de busca semântica."""
    print("\n=== Teste de Busca Semântica ===")
    latencias = []
    for consulta in consultas:
        t0 = time.time()
        resultados = memoria.buscar(consulta, k=4)
        lat = time.time() - t0
        latencias.append(lat)
        print(f"'{consulta[:30]}...' -> {len(resultados)} resultados em {lat*1000:.1f}ms")

    media = sum(latencias) / len(latencias)
    print(f"Latência média: {media*1000:.1f}ms")
    print(f"Latência máxima: {max(latencias)*1000:.1f}ms")
    print(f"Latência mínima: {min(latencias)*1000:.1f}ms")

def testar_embedding_individual(memoria, texto):
    """Testa latência de um embedding individual."""
    print("\n=== Teste de Embedding Individual ===")
    t0 = time.time()
    emb = memoria._emb(texto)
    lat = time.time() - t0
    print(f"Embedding de '{texto[:50]}...': {lat*1000:.1f}ms")
    print(f"Dimensão: {len(emb)}")

    # Testar cache hit
    t0 = time.time()
    emb2 = memoria._emb(texto)
    lat2 = time.time() - t0
    print(f"Segunda vez (cache): {lat2*1000:.1f}ms")
    print(f"Speedup cache: {lat / lat2:.2f}x")

def main():
    cfg = config.carregar()
    print(f"ORION Latência Test")
    print(f"Modulo Rust disponível: {RUST_AVAILABLE}")
    print(f"Modelo embeddings: {cfg['modelo_embeddings']}")

    memoria = Memoria(os.path.join(config.BASE, "orion_memoria.db"), cfg["modelo_embeddings"])

    # Textos de teste
    textos_teste = [
        "gosto de café sem açúcar",
        "trabalho em programação",
        "tenho reunião às 15h",
        "comprei ações da Microsoft",
        "fazer backup dos documentos",
    ]

    consultas = [
        "que bebo de manhã?",
        "qual a minha profissão?",
        "tenho compromissos hoje?",
        "como está a minha carteira?",
        "está o sistema seguro?",
    ]

    # Testar embeddings
    testar_embedding_individual(memoria, "o que é inteligência artificial?")

    # Testar cache
    testar_cache_hits(memoria, textos_teste)

    # Testar busca
    testar_busca(memoria, consultas)

    print("\n=== Resumo ===")
    if RUST_AVAILABLE:
        print("[OK] Modulo Rust ativo - expectativa: <50ms para embeddings em cache")
        print("[OK] Cache LRU - expectativa: 1000x+ speedup para textos repetidos")
    else:
        print("[ERRO] Modulo Rust nao disponivel - usando ollama (mais lento)")
        print("  Para ativar: cd rust_modules && cargo build --release")

if __name__ == "__main__":
    main()
