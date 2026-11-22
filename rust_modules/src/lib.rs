use std::sync::{Arc, RwLock};
use once_cell::sync::Lazy;

mod cache;
mod vector_store;

use cache::EmbeddingCache;
use vector_store::VectorStore;

// Global singletons
static EMBEDDING_CACHE: Lazy<Arc<RwLock<EmbeddingCache>>> =
    Lazy::new(|| Arc::new(RwLock::new(EmbeddingCache::new(10000))));

static VECTOR_STORE: Lazy<Arc<RwLock<VectorStore>>> =
    Lazy::new(|| Arc::new(RwLock::new(VectorStore::new())));

// FFI functions para Python via ctypes

/// Calcula hash de uma string
#[no_mangle]
pub extern "C" fn hash_string(text: *const u8, len: usize) -> u64 {
    use std::hash::{Hash, Hasher};
    use std::collections::hash_map::DefaultHasher;

    let bytes = unsafe { std::slice::from_raw_parts(text, len) };
    let str_slice = std::str::from_utf8(bytes).unwrap_or("");

    let mut hasher = DefaultHasher::new();
    str_slice.hash(&mut hasher);
    hasher.finish()
}

/// Adiciona embedding ao cache
#[no_mangle]
pub extern "C" fn cache_put(key: u64, embedding: *const f32, len: usize) {
    let emb = unsafe { std::slice::from_raw_parts(embedding, len) }.to_vec();
    let mut cache = EMBEDDING_CACHE.write().unwrap();
    cache.put_raw(key, emb);
}

/// Obtém embedding do cache (retorna 1 se encontrado, 0 se não)
#[no_mangle]
pub extern "C" fn cache_get(key: u64, output: *mut f32, max_len: usize) -> i32 {
    let cache = EMBEDDING_CACHE.read().unwrap();
    if let Some(emb) = cache.get_raw(key) {
        let len = emb.len().min(max_len);
        unsafe {
            std::ptr::copy_nonoverlapping(emb.as_ptr(), output, len);
        }
        1
    } else {
        0
    }
}

/// Limpa o cache
#[no_mangle]
pub extern "C" fn cache_clear() {
    EMBEDDING_CACHE.write().unwrap().clear();
}

/// Adiciona vetor ao store
#[no_mangle]
pub extern "C" fn vector_store_add(id: u64, embedding: *const f32, len: usize) {
    let emb = unsafe { std::slice::from_raw_parts(embedding, len) }.to_vec();
    let mut store = VECTOR_STORE.write().unwrap();
    store.add(id, emb, None);
}

/// Busca k vizinhos mais próximos
#[no_mangle]
pub extern "C" fn vector_store_search(
    query: *const f32,
    query_len: usize,
    k: usize,
    ids_out: *mut u64,
    scores_out: *mut f32,
) -> usize {
    let q = unsafe { std::slice::from_raw_parts(query, query_len) }.to_vec();
    let store = VECTOR_STORE.read().unwrap();
    let results = store.search(&q, k);

    for (i, result) in results.iter().enumerate() {
        unsafe {
            *ids_out.add(i) = result.id;
            *scores_out.add(i) = result.score;
        }
    }

    results.len()
}

/// Limpa o vector store
#[no_mangle]
pub extern "C" fn vector_store_clear() {
    VECTOR_STORE.write().unwrap().clear();
}

/// Número de vetores no store
#[no_mangle]
pub extern "C" fn vector_store_len() -> usize {
    VECTOR_STORE.read().unwrap().len()
}
