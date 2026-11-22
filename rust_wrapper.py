"""Wrapper Python para o módulo Rust do ORION via ctypes (FFI)."""
import ctypes
import os
from pathlib import Path
import numpy as np

# Caminho para a DLL compilada
DLL_PATH = Path(__file__).parent / "rust_modules" / "target" / "release" / "orion_rust.dll"

# Carregar DLL
try:
    _lib = ctypes.CDLL(str(DLL_PATH))
    print(f"[rust_wrapper] DLL carregada: {DLL_PATH}")
except Exception as e:
    print(f"[rust_wrapper] Erro ao carregar DLL: {e}")
    _lib = None

if _lib:
    # Configurar tipos de retorno
    _lib.hash_string.argtypes = [ctypes.c_char_p, ctypes.c_size_t]
    _lib.hash_string.restype = ctypes.c_uint64

    _lib.cache_put.argtypes = [ctypes.c_uint64, ctypes.POINTER(ctypes.c_float), ctypes.c_size_t]
    _lib.cache_put.restype = None

    _lib.cache_get.argtypes = [ctypes.c_uint64, ctypes.POINTER(ctypes.c_float), ctypes.c_size_t]
    _lib.cache_get.restype = ctypes.c_int

    _lib.cache_clear.argtypes = []
    _lib.cache_clear.restype = None

    _lib.vector_store_add.argtypes = [ctypes.c_uint64, ctypes.POINTER(ctypes.c_float), ctypes.c_size_t]
    _lib.vector_store_add.restype = None

    _lib.vector_store_search.argtypes = [
        ctypes.POINTER(ctypes.c_float),
        ctypes.c_size_t,
        ctypes.c_size_t,
        ctypes.POINTER(ctypes.c_uint64),
        ctypes.POINTER(ctypes.c_float),
    ]
    _lib.vector_store_search.restype = ctypes.c_size_t

    _lib.vector_store_clear.argtypes = []
    _lib.vector_store_clear.restype = None

    _lib.vector_store_len.argtypes = []
    _lib.vector_store_len.restype = ctypes.c_size_t


class RustEmbeddings:
    """Interface Python para cache de embeddings em Rust."""

    def __init__(self, cache_size=10000):
        self.cache_size = cache_size
        self._lib = _lib

    def hash_text(self, text: str) -> int:
        """Calcula hash de uma string."""
        if not self._lib:
            return hash(text)
        encoded = text.encode('utf-8')
        return self._lib.hash_string(encoded, len(encoded))

    def cache_put(self, key: int, embedding: np.ndarray):
        """Adiciona embedding ao cache."""
        if not self._lib:
            return
        embedding_f32 = embedding.astype(np.float32)
        self._lib.cache_put(key, embedding_f32.ctypes.data_as(ctypes.POINTER(ctypes.c_float)), len(embedding_f32))

    def cache_get(self, key: int, expected_len: int) -> np.ndarray | None:
        """Obtém embedding do cache."""
        if not self._lib:
            return None
        output = np.zeros(expected_len, dtype=np.float32)
        found = self._lib.cache_get(key, output.ctypes.data_as(ctypes.POINTER(ctypes.c_float)), expected_len)
        return output if found else None

    def cache_clear(self):
        """Limpa o cache."""
        if self._lib:
            self._lib.cache_clear()


class RustVectorStore:
    """Interface Python para vector store em Rust."""

    def __init__(self):
        self._lib = _lib

    def add(self, id: int, embedding: np.ndarray, metadata: str = None):
        """Adiciona vetor ao store."""
        if not self._lib:
            return
        embedding_f32 = embedding.astype(np.float32)
        self._lib.vector_store_add(id, embedding_f32.ctypes.data_as(ctypes.POINTER(ctypes.c_float)), len(embedding_f32))

    def search(self, query: np.ndarray, k: int = 4):
        """Busca k vizinhos mais próximos."""
        if not self._lib:
            return []
        query_f32 = query.astype(np.float32)
        ids = np.zeros(k, dtype=np.uint64)
        scores = np.zeros(k, dtype=np.float32)
        count = self._lib.vector_store_search(
            query_f32.ctypes.data_as(ctypes.POINTER(ctypes.c_float)),
            len(query_f32),
            k,
            ids.ctypes.data_as(ctypes.POINTER(ctypes.c_uint64)),
            scores.ctypes.data_as(ctypes.POINTER(ctypes.c_float)),
        )
        return list(zip(ids[:count], scores[:count]))

    def clear(self):
        """Limpa o store."""
        if self._lib:
            self._lib.vector_store_clear()

    def len(self) -> int:
        """Número de vetores no store."""
        if not self._lib:
            return 0
        return self._lib.vector_store_len()


# Verificar disponibilidade
RUST_AVAILABLE = _lib is not None
print(f"[rust_wrapper] Módulo Rust disponível: {RUST_AVAILABLE}")
