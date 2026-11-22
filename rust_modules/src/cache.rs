/// Cache simples ultra-rápido para embeddings
/// Reduz dramaticamente chamadas repetidas ao modelo de embeddings

use std::collections::HashMap;

pub struct EmbeddingCache {
    cache: HashMap<u64, Vec<f32>>,
    capacity: usize,
}

impl EmbeddingCache {
    pub fn new(capacity: usize) -> Self {
        Self {
            cache: HashMap::new(),
            capacity,
        }
    }

    /// Adiciona embedding ao cache (com chave raw)
    pub fn put_raw(&mut self, key: u64, embedding: Vec<f32>) {
        // Se atingir capacidade, limpar metade (LRU simplificado)
        if self.cache.len() >= self.capacity {
            let keys_to_remove: Vec<_> = self.cache.keys().take(self.capacity / 2).cloned().collect();
            for k in keys_to_remove {
                self.cache.remove(&k);
            }
        }
        self.cache.insert(key, embedding);
    }

    /// Obtém embedding do cache (com chave raw)
    pub fn get_raw(&self, key: u64) -> Option<Vec<f32>> {
        self.cache.get(&key).cloned()
    }

    /// Limpa o cache
    pub fn clear(&mut self) {
        self.cache.clear();
    }

    /// Tamanho do cache
    pub fn len(&self) -> usize {
        self.cache.len()
    }
}
