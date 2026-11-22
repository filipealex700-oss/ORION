/// Store vetorial otimizado usando busca linear
/// Versão simplificada sem HNSW (dependência não disponível)

use std::collections::HashMap;

#[derive(Clone)]
pub struct VectorEntry {
    pub id: u64,
    pub embedding: Vec<f32>,
}

pub struct SearchResult {
    pub id: u64,
    pub score: f32,
}

pub struct VectorStore {
    vectors: HashMap<u64, VectorEntry>,
    dimension: usize,
}

impl VectorStore {
    pub fn new() -> Self {
        Self {
            vectors: HashMap::new(),
            dimension: 768, // Dimensão padrão para embeddings
        }
    }

    pub fn add(&mut self, id: u64, embedding: Vec<f32>, _metadata: Option<String>) {
        if self.vectors.is_empty() {
            self.dimension = embedding.len();
        }

        self.vectors.insert(id, VectorEntry {
            id,
            embedding,
        });
    }

    pub fn remove(&mut self, id: u64) {
        self.vectors.remove(&id);
    }

    pub fn clear(&mut self) {
        self.vectors.clear();
    }

    pub fn len(&self) -> usize {
        self.vectors.len()
    }

    /// Busca os k vizinhos mais próximos (linear em Rust)
    pub fn search(&self, query: &[f32], k: usize) -> Vec<SearchResult> {
        if self.vectors.is_empty() {
            return vec![];
        }

        // Busca linear (ainda muito rápido em Rust)
        let mut results: Vec<SearchResult> = self.vectors.values()
            .map(|entry| {
                let score = cosine_similarity(query, &entry.embedding);
                SearchResult {
                    id: entry.id,
                    score,
                }
            })
            .collect();

        results.sort_by(|a, b| b.score.partial_cmp(&a.score).unwrap());
        results.truncate(k);
        results
    }

    /// Placeholder para compatibilidade (não faz nada sem HNSW)
    pub fn build_index(&mut self) {
        // Nada a fazer na versão linear
    }
}

fn cosine_similarity(a: &[f32], b: &[f32]) -> f32 {
    let dot: f32 = a.iter().zip(b.iter()).map(|(x, y)| x * y).sum();
    let norm_a: f32 = a.iter().map(|x| x * x).sum::<f32>().sqrt();
    let norm_b: f32 = b.iter().map(|x| x * x).sum::<f32>().sqrt();
    dot / (norm_a * norm_b + 1e-8)
}
