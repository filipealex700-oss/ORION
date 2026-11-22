# Fine-tuning do Whisper com Dataset MLS Português

## Requisitos

### Hardware
- **GPU com CUDA** (recomendado: NVIDIA RTX 3060 ou superior com 8GB+ VRAM)
- CPU funciona mas será muito lento (não recomendado)

### Software
Instalar as dependências:

```bash
pip install transformers datasets peft torch accelerate
```

## Como usar

### 1. Configurar parâmetros
Edite `fine_tune_whisper.py` e ajuste:

```python
MAX_SAMPLES = 500  # Número de amostras para treinar (aumentar se tiver mais VRAM)
BATCH_SIZE = 4     # Batch size (reduzir se tiver OOM)
NUM_EPOCHS = 3     # Número de épocas
```

### 2. Executar o treino

```bash
python fine_tune_whisper.py
```

### 3. Usar o modelo treinado

Depois do treino, atualize `config.json`:

```json
{
  "whisper_modelo": "whisper-portuguese-finetuned"
}
```

## Parâmetros importantes

### MAX_SAMPLES
- **500** = ~2GB VRAM, treino rápido
- **1000** = ~4GB VRAM, melhor qualidade
- **5000** = ~16GB VRAM, excelente qualidade

### BATCH_SIZE
- **4** = padrão, funciona com 8GB VRAM
- **2** = se tiver OOM (out of memory)
- **8** = se tiver 16GB+ VRAM

## Tempo estimado

- 500 amostras: ~30-60 minutos
- 1000 amostras: ~1-2 horas
- 5000 amostras: ~6-10 horas

## Resultados esperados

O fine-tuning vai:
- Melhorar reconhecimento de português
- Adaptar ao sotaque do dataset (audiobooks)
- Reduzir erros em palavras específicas

## Troubleshooting

### CUDA out of memory
Reduza `BATCH_SIZE` para 2 ou `MAX_SAMPLES` para 250.

### Treino muito lento no CPU
Use GPU ou reduza drasticamente `MAX_SAMPLES` para 100.

### Erro de memória do sistema
Reduza `MAX_SAMPLES` e feche outros programas.

## Notas

- O modelo é salvo em `whisper-portuguese-finetuned/`
- Usa LoRA para fine-tuning eficiente (não guarda o modelo completo)
- Pode continuar o treino alterando `output_dir`
