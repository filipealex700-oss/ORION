"""Memória local do ORION (SQLite no teu disco).
mensagens: histórico | memorias: factos de longo prazo com embeddings | e tabelas de aprendizagem."""
import json
import time

import numpy as np
import ollama

from dbutil import DBSeguro

# Tentar importar módulo Rust otimizado via ctypes
RUST_AVAILABLE = False
try:
    from rust_wrapper import RustEmbeddings, RustVectorStore, RUST_AVAILABLE as RUST_OK
    RUST_AVAILABLE = RUST_OK
    if RUST_AVAILABLE:
        print("[memória] Módulo Rust carregado - embeddings e busca otimizados")
except ImportError:
    print("[memória] Módulo Rust não disponível - usando ollama (fallback)")


class Memoria:
    def __init__(self, caminho, modelo_emb):
        self.db = DBSeguro(caminho)
        self.modelo_emb = modelo_emb
        self.db.executescript(
            """
            CREATE TABLE IF NOT EXISTS mensagens(
                id INTEGER PRIMARY KEY, ts REAL, papel TEXT, texto TEXT);
            CREATE TABLE IF NOT EXISTS memorias(
                id INTEGER PRIMARY KEY, ts REAL, texto TEXT, emb BLOB);
            CREATE TABLE IF NOT EXISTS meta(chave TEXT PRIMARY KEY, valor TEXT);
            CREATE TABLE IF NOT EXISTS uso(
                id INTEGER PRIMARY KEY, ts REAL, ferramenta TEXT, args TEXT);
            CREATE TABLE IF NOT EXISTS correcoes(errado TEXT PRIMARY KEY, certo TEXT);
            CREATE TABLE IF NOT EXISTS vocabulario(palavra TEXT PRIMARY KEY);
            CREATE TABLE IF NOT EXISTS sugestoes(
                id INTEGER PRIMARY KEY, descr TEXT, ferramenta TEXT, args TEXT,
                hora TEXT, estado TEXT DEFAULT 'nova');
            CREATE TABLE IF NOT EXISTS tracos(
                id INTEGER PRIMARY KEY, ts REAL, pergunta TEXT, rota TEXT, modelo TEXT,
                ferramentas TEXT, latencia REAL, avaliacao INTEGER);
            CREATE TABLE IF NOT EXISTS feedback(
                id INTEGER PRIMARY KEY, ts REAL, pergunta TEXT, resposta TEXT,
                avaliacao INTEGER, comentario TEXT);
            """
        )
        self.db.commit()

        # Inicializar módulo Rust se disponível
        self.rust_embeddings = None
        if RUST_AVAILABLE:
            try:
                self.rust_embeddings = RustEmbeddings(cache_size=10000)
                print("[memória] Cache Rust inicializado")
            except Exception as e:
                print(f"[memória] Erro ao inicializar Rust: {e}")
                self.rust_embeddings = None

    # ---------- embeddings ----------
    def _emb(self, texto):
        # Usar módulo Rust se disponível (cache ultra-rápido via hash)
        if self.rust_embeddings:
            try:
                key = self.rust_embeddings.hash_text(texto)
                cached = self.rust_embeddings.cache_get(key, 768)  # Dimensão padrão
                if cached is not None:
                    return cached

                # Calcular via ollama e guardar no cache
                v = ollama.embed(model=self.modelo_emb, input=texto, keep_alive="10m")["embeddings"][0]
                a = np.array(v, dtype=np.float32)
                n = np.linalg.norm(a)
                emb = a / n if n else a
                self.rust_embeddings.cache_put(key, emb)
                return emb
            except Exception as e:
                print(f"[memória] Erro no embedding Rust: {e}, fallback para ollama")

        # Fallback para ollama
        v = ollama.embed(model=self.modelo_emb, input=texto, keep_alive="10m")["embeddings"][0]
        a = np.array(v, dtype=np.float32)
        n = np.linalg.norm(a)
        return a / n if n else a

    def _todas(self):
        linhas = self.db.execute("SELECT id, texto, emb FROM memorias").fetchall()
        return [(i, t, np.frombuffer(e, dtype=np.float32)) for i, t, e in linhas]

    # ---------- longo prazo ----------
    def guardar(self, texto):
        texto = texto.strip()
        if not texto:
            return "Nada para guardar."
        emb = self._emb(texto)
        for _, t, e in self._todas():
            if float(np.dot(emb, e)) > 0.95:
                return "Já tinha essa informação."
        self.db.execute("INSERT INTO memorias(ts, texto, emb) VALUES(?,?,?)",
                        (time.time(), texto, emb.tobytes()))
        self.db.commit()
        return "Guardado na memória."

    def buscar(self, consulta, k=4, min_score=0.45):
        try:
            q = self._emb(consulta)
        except Exception as e:
            print(f"[memória] embeddings indisponíveis: {e}")
            return []

        # Fallback: busca linear em Python (Rust vector store simplificado)
        pont = sorted(((float(np.dot(q, e)), t) for _, t, e in self._todas()), reverse=True)
        return [t for s, t in pont[:k] if s >= min_score]

    def esquecer(self, consulta):
        q = self._emb(consulta)
        melhor = None
        for i, t, e in self._todas():
            s = float(np.dot(q, e))
            if melhor is None or s > melhor[0]:
                melhor = (s, i, t)
        if melhor and melhor[0] >= 0.6:
            self.db.execute("DELETE FROM memorias WHERE id=?", (melhor[1],))
            self.db.commit()
            return f"Esquecido: {melhor[2]}"
        return "Não encontrei nada parecido na memória."

    # ---------- curto prazo ----------
    def registar(self, papel, texto):
        self.db.execute("INSERT INTO mensagens(ts, papel, texto) VALUES(?,?,?)",
                        (time.time(), papel, texto))
        self.db.commit()

    def historico_recente(self, n=8):
        linhas = self.db.execute(
            "SELECT papel, texto FROM mensagens ORDER BY id DESC LIMIT ?", (n,)).fetchall()
        return [{"role": p, "content": t} for p, t in reversed(linhas)]

    # ---------- aprendizagem ----------
    def meta_get(self, chave, padrao=None):
        r = self.db.execute("SELECT valor FROM meta WHERE chave=?", (chave,)).fetchone()
        return r[0] if r else padrao

    def meta_set(self, chave, valor):
        self.db.execute("INSERT OR REPLACE INTO meta(chave, valor) VALUES(?,?)", (chave, str(valor)))
        self.db.commit()

    def registar_uso(self, ferramenta, args):
        self.db.execute("INSERT INTO uso(ts, ferramenta, args) VALUES(?,?,?)",
                        (time.time(), ferramenta,
                         json.dumps(args or {}, sort_keys=True, ensure_ascii=False)))
        self.db.commit()

    def registar_traco(self, pergunta, rota, modelo, ferramentas, latencia):
        r = self.db.execute(
            "INSERT INTO tracos(ts, pergunta, rota, modelo, ferramentas, latencia) VALUES(?,?,?,?,?,?)",
            (time.time(), pergunta, rota, modelo, json.dumps(ferramentas, ensure_ascii=False), latencia))
        self.db.commit()
        return r.lastrowid
