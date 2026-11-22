# ORION — notas para agentes de código

Assistente pessoal local para Windows. Voz (Whisper fine-tuned PT + Edge TTS),
cérebro (Ollama), memória SQLite, ferramentas Windows, Home Assistant, Obsidian,
painel web FastAPI, módulo Rust para embeddings.

## Arquitetura (fluxo principal)

- `main.py` / `nucleo.py` — loop principal, orquestração
- `voice.py` — captura de áudio, Whisper (faster-whisper CT2 preferido via `model.bin`), TTS (Edge TTS → fallback SAPI)
- `brain.py` — prompt do sistema, chamadas Ollama, loop de ferramentas (2 iterações)
- `routing.py` + `treinar_router.py` — roteamento multi-modelo (rede neural `modelos/router_nn.pkl` + palavras-chave)
- `tools.py` — ferramentas executáveis (pesquisa Bing, crypto CoinGecko, Windows, etc.)
- `memory.py`, `aprendizagem.py` — memória SQLite e aprendizagem
- `orion_web/app.py` — painel web (FastAPI, porta 8765)
- `config.py` / `config.json` — configuração; segredos via `.env` (`ORION_LANGFLOW_API_KEY`, `ORION_HA_TOKEN`, `ORION_WEB_TOKEN`)

## Regras importantes

- **Nunca commitar**: `.env`, `config.json` (usar `config.example.json`), `*.db`, `modelos/` binários,
  `whisper-portuguese-finetuned/` (adaptador regenerável), datasets, venvs, `Vault/`, `projetos/`, `orion_core/`.
- Caminhos sempre relativos a `config.BASE`/`__file__` — nunca paths absolutos de máquina.
- Windows-first: PowerShell/Batch. `.bat` na raiz são os launchers.
- Whisper: preferir CTranslate2 (`model.bin`) como motor principal; HF/Transformers é fallback.
  Pipeline de retreino: `fine_tune_whisper.py` → `build_ct2.py` → `run_ct2_convert.py`.
- Dois venvs possíveis: `venv` (CPU torch) e `venv310` (CUDA torch). GPU Whisper requer
  `faster-whisper` + `ctranslate2` com CUDA; `voice.py` regista DLLs NVIDIA automaticamente.

## Verificação

- Sintaxe: `python -m py_compile <ficheiro>`
- Sem testes automatizados formais — testar via `iniciar_texto.bat` ou `python test_orion.py`
- GPU: `nvidia-smi` para VRAM; Ollama: `ollama ps`
