"""fine_tune_whisper.py

Fine-tuning iterativo do Whisper (Português) com adaptadores LoRA via PEFT.

Usa o dataset MLS Portuguese que já existe localmente em DataSET/mls_portuguese/,
ou qualquer dataset do HuggingFace Hub.

Uso (PowerShell – tudo numa linha):
    python fine_tune_whisper.py --epochs 1 --batch_size 4 --merge

Ou com argumentos explícitos:
    python fine_tune_whisper.py --local_dir DataSET/mls_portuguese --epochs 3 --batch_size 4 --learning_rate 5e-4 --merge

Ver todos os argumentos:
    python fine_tune_whisper.py -h
"""

import argparse
import io
import os
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Union

import numpy as np
import soundfile as sf
import torch
from datasets import Audio, Dataset, DatasetDict
from peft import LoraConfig, get_peft_model
from transformers import (
    Trainer,
    TrainingArguments,
    WhisperForConditionalGeneration,
    WhisperProcessor,
    Seq2SeqTrainingArguments,
    Seq2SeqTrainer,
    default_data_collator,
)

# Data augmentation
try:
    from audiomentations import Compose, Gain, AddGaussianNoise, TimeStretch, PitchShift
    AUGMENTATION_AVAILABLE = True
except ImportError:
    AUGMENTATION_AVAILABLE = False
    print("AVISO: audiomentations não instalado. Data augmentation será desativada.")
    print("Instala com: pip install audiomentations")

# ---------------------------------------------------------------------------
# Argumentos CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Fine-tune Whisper (PT) com LoRA")
    p.add_argument("--local_dir", type=str, default="DataSET/mls_portuguese",
                   help="Pasta local com o dataset MLS Portuguese (default: DataSET/mls_portuguese)")
    p.add_argument("--cv_dir", type=str, default=None,
                   help="Pasta de um corpus Common Voice extraído (a pasta 'pt' que contém "
                        "train.tsv/dev.tsv/test.tsv e clips/)")
    p.add_argument("--hf_dataset", type=str, default=None,
                   help="Dataset do HuggingFace Hub (ex.: 'google/fleurs', "
                        "'mozilla-foundation/common_voice_17_0', 'PolyAI/minds14')")
    p.add_argument("--hf_config", type=str, default=None,
                   help="Config/subset do dataset HF (ex.: 'pt_pt' para FLEURS, 'pt' para Common Voice)")
    p.add_argument("--hf_split", type=str, default="train",
                   help="Split do dataset HF (default: train)")
    p.add_argument("--base_model", type=str, default="openai/whisper-small",
                   help="Modelo base Whisper (default: openai/whisper-small; 'openai/whisper-medium' "
                        "precisa de mais VRAM e batch_size menor)")
    p.add_argument("--output_dir", type=str, default="modelos/whisper-portuguese-finetuned",
                   help="Pasta de saída para checkpoints e modelo final")
    p.add_argument("--adapter_dir", type=str, default="whisper-portuguese-finetuned",
                   help="Pasta para guardar o adaptador LoRA (default: whisper-portuguese-finetuned)")
    p.add_argument("--epochs", type=int, default=20, help="Número de épocas de treino (default: 20 - agressivo)")
    p.add_argument("--batch_size", type=int, default=4, help="Batch size por GPU (default: 4 - para 6GB VRAM)")
    p.add_argument("--learning_rate", type=float, default=5e-5, help="Learning rate (AdamW, default: 5e-5 - mais conservador)")
    p.add_argument("--gradient_accumulation_steps", type=int, default=8,
                   help="Acumular gradientes por N steps (default: 8 - batch efetivo 32)")
    p.add_argument("--max_train_samples", type=int, default=None,
                   help="Limitar exemplos de treino (útil para testes rápidos)")
    p.add_argument("--max_eval_samples", type=int, default=None,
                   help="Limitar exemplos de validação")
    p.add_argument("--merge", action="store_true",
                   help="Fundir LoRA no modelo base após o treino")
    p.add_argument("--seed", type=int, default=42, help="Semente para reprodutibilidade")
    return p.parse_args()


def set_seed(seed: int):
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


# ---------------------------------------------------------------------------
# Carregamento do dataset MLS Portuguese (local)
# ---------------------------------------------------------------------------

def load_mls_split(base_dir: str, split: str) -> Dataset:
    """Carrega um split (train/dev/test) do MLS Portuguese a partir do disco.

    O formato MLS tem:
        <split>/transcripts.txt   -> linhas "ID\\ttexto"
        <split>/audio/<spk>/<book>/<ID>.flac

    Devolve um datasets.Dataset com colunas: audio (bytes), sentence (str).
    """
    split_dir = Path(base_dir) / split
    transcripts_file = split_dir / "transcripts.txt"

    if not transcripts_file.exists():
        raise FileNotFoundError(f"Ficheiro de transcrições não encontrado: {transcripts_file}")

    # Ler todas as transcrições
    entries = []
    with open(transcripts_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split("\t", 1)
            if len(parts) != 2:
                continue
            uid, text = parts
            # Construir o caminho do áudio: ID é do tipo "12249_10229_000000"
            # -> audio/12249/10229/12249_10229_000000.flac
            id_parts = uid.split("_")
            if len(id_parts) >= 2:
                speaker, book = id_parts[0], id_parts[1]
                audio_path = split_dir / "audio" / speaker / book / f"{uid}.flac"
            else:
                audio_path = split_dir / "audio" / f"{uid}.flac"

            if audio_path.exists():
                entries.append({"audio_path": str(audio_path), "sentence": text})

    if not entries:
        raise ValueError(f"Nenhuma entrada válida encontrada no split '{split}' de {base_dir}")

    print(f"  [{split}] {len(entries)} exemplos encontrados")

    # Construir o Dataset – guardar apenas os caminhos; o áudio será lido no preprocessing
    return Dataset.from_dict({
        "audio_path": [e["audio_path"] for e in entries],
        "sentence": [e["sentence"] for e in entries],
    })


def load_hf_data(args) -> DatasetDict:
    """Carrega um dataset do HuggingFace Hub e normaliza para audio_path/sentence."""
    from datasets import load_dataset

    ds = load_dataset(args.hf_dataset, args.hf_config, split=args.hf_split)

    # Detetar colunas de áudio e texto
    audio_col = next((c for c in ds.column_names
                      if c.lower() in ("audio", "path", "file", "audio_filepath")), None)
    text_col = next((c for c in ("sentence", "raw_transcription", "transcription",
                                 "text", "sentence_low", "transcript")
                     if c in ds.column_names), None)
    if not audio_col or not text_col:
        raise ValueError(f"Não consegui detetar colunas de áudio/texto em {ds.column_names}")

    # Manter só áudio + texto; renomear para os nomes que preprocess_fn espera.
    # Manter a feature Audio original (guarda arrays de forma eficiente).
    ds = ds.remove_columns([c for c in ds.column_names if c not in (audio_col, text_col)])
    ds = ds.rename_column(audio_col, "audio")
    ds = ds.rename_column(text_col, "sentence")
    return DatasetDict({"train": ds, "eval": ds})


def load_cv_split(cv_dir: str, split: str) -> Dataset:
    """Carrega um split do Common Voice a partir do corpus extraído.

    Estrutura: <cv_dir>/train.tsv, dev.tsv, test.tsv, validated.tsv
    e <cv_dir>/clips/<id>.mp3. Colunas do TSV: client_id, path, sentence, ...
    """
    # validated.tsv tem TODO o corpus validado (~162k no CV 27); train.tsv é
    # só uma fração (~23k). Usar validated como fonte principal de treino.
    tsv = Path(cv_dir) / "validated.tsv"
    if not tsv.exists():
        tsv = Path(cv_dir) / f"{split}.tsv"
    clips = Path(cv_dir) / "clips"

    entries = []
    with open(tsv, "r", encoding="utf-8") as f:
        header = f.readline().rstrip("\n").split("\t")
        idx_path = header.index("path")
        idx_sent = header.index("sentence")
        for line in f:
            parts = line.rstrip("\n").split("\t")
            if len(parts) <= max(idx_path, idx_sent):
                continue
            audio = clips / parts[idx_path]
            sentence = parts[idx_sent].strip()
            if audio.exists() and sentence:
                entries.append({"audio_path": str(audio), "sentence": sentence})

    print(f"  [cv/{split}] {len(entries)} exemplos")
    return Dataset.from_dict({
        "audio_path": [e["audio_path"] for e in entries],
        "sentence": [e["sentence"] for e in entries],
    })


def load_data(args) -> DatasetDict:
    """Carrega train + dev do MLS local, Common Voice ou dataset HF."""
    if args.cv_dir:
        print(f"A carregar Common Voice de: {args.cv_dir}")
        # validated.tsv = corpus completo; dev.tsv está contido nele,
        # por isso a validação é um slice separado do próprio treino.
        full = load_cv_split(args.cv_dir, "train")
        sp = full.train_test_split(test_size=0.02, seed=args.seed)
        return DatasetDict({"train": sp["train"], "eval": sp["test"]})

    if args.hf_dataset:
        print(f"A carregar dataset HF '{args.hf_dataset}'"
              + (f" (config {args.hf_config})" if args.hf_config else ""))
        return load_hf_data(args)

    base_dir = args.local_dir
    print(f"A carregar dataset local de: {base_dir}")

    train_ds = load_mls_split(base_dir, "train")
    # Usar "dev" como validação (é o padrão do MLS)
    dev_dir = Path(base_dir) / "dev"
    if dev_dir.exists():
        eval_ds = load_mls_split(base_dir, "dev")
    else:
        # Se não houver dev, fazer split 90/10
        split = train_ds.train_test_split(test_size=0.1, seed=args.seed)
        train_ds = split["train"]
        eval_ds = split["test"]

    return DatasetDict({"train": train_ds, "eval": eval_ds})


# ---------------------------------------------------------------------------
# Data Augmentation
# ---------------------------------------------------------------------------

def get_augmenter():
    """Retorna um augmenter de áudio AGRESSIVO se audiomentations estiver disponível."""
    if not AUGMENTATION_AVAILABLE:
        return None

    return Compose([
        AddGaussianNoise(min_amplitude=0.0005, max_amplitude=0.02, p=0.6),  # Mais ruído
        TimeStretch(min_rate=0.85, max_rate=1.15, p=0.6),  # Mais variação de velocidade
        PitchShift(min_semitones=-3, max_semitones=3, p=0.4),  # Mais variação de pitch
    ])


# ---------------------------------------------------------------------------
# Preprocessing: áudio -> features do Whisper
# ---------------------------------------------------------------------------

def preprocess_fn(batch, processor, augmenter=None, is_training=True):
    """Processa um exemplo: lê o áudio, aplica augmentation avançada, extrai features, tokeniza a transcrição."""
    # Dataset HF: áudio embutido (dict com 'array' e 'sampling_rate')
    if "audio" in batch:
        a = batch["audio"]
        if isinstance(a, dict):
            speech = np.asarray(a["array"], dtype=np.float32)
            sr = a.get("sampling_rate", 16000)
        else:
            speech, sr = sf.read(a)
    else:
        # Dataset local MLS: caminho para ficheiro .flac
        speech, sr = sf.read(batch["audio_path"])

    # Converter para mono se necessário
    if len(speech.shape) > 1:
        speech = speech.mean(axis=1)

    # Resample para 16kHz se necessário
    if sr != 16000:
        import librosa
        speech = librosa.resample(speech, orig_sr=sr, target_sr=16000)

    # Data augmentation (apenas durante treino)
    if is_training and augmenter is not None:
        speech = augmenter(samples=speech, sample_rate=16000)

    # Normalização RMS (volume consistente)
    rms = np.sqrt(np.mean(speech ** 2))
    if rms > 0:
        speech = speech / rms

    # Trim de silêncio (remover silêncio no início/fim)
    if is_training:
        import librosa
        speech, _ = librosa.effects.trim(speech, top_db=20)

    # Usar o processor do Whisper para formatar corretamente
    inputs = processor(
        audio=speech,
        sampling_rate=16000,
        text=batch["sentence"],
        return_tensors="pt",
    )

    return {
        "input_features": inputs.input_features[0],
        "labels": inputs.labels[0],
    }


def preprocess_dataset(ds: Dataset, processor, augmenter=None, is_training=True) -> Dataset:
    """Aplica o preprocessing a todo o dataset."""
    cols_to_remove = [c for c in ds.column_names if c not in ("input_features", "labels")]
    ds = ds.map(
        lambda batch: preprocess_fn(batch, processor, augmenter, is_training),
        remove_columns=cols_to_remove,
        desc="Preprocessing",
    )
    return ds


# ---------------------------------------------------------------------------
# Data Collator para Seq2Seq com padding
# ---------------------------------------------------------------------------

@dataclass
class DataCollatorSpeechSeq2SeqWithPadding:
    """Collator que faz padding dos input_features e labels separadamente."""
    processor: Any

    def __call__(self, features: List[Dict[str, Union[torch.Tensor, List[int]]]]) -> Dict[str, torch.Tensor]:
        # Pad input_features (mel spectrograms)
        input_features = [{"input_features": f["input_features"]} for f in features]
        batch = self.processor.feature_extractor.pad(input_features, return_tensors="pt")

        # Usar float16 se GPU disponível, senão float32
        if torch.cuda.is_available():
            batch["input_features"] = batch["input_features"].to(torch.float16)

        # Pad labels (token IDs)
        label_features = [{"input_ids": f["labels"]} for f in features]
        labels_batch = self.processor.tokenizer.pad(label_features, return_tensors="pt")

        # Substituir tokens de padding por -100 (ignorados pela loss)
        labels = labels_batch["input_ids"].masked_fill(
            labels_batch["attention_mask"].ne(1), -100
        )

        # Remover o BOS token se estiver no início de todos os exemplos
        if (labels[:, 0] == self.processor.tokenizer.bos_token_id).all():
            labels = labels[:, 1:]

        batch["labels"] = labels
        # Não incluir input_ids no batch - Whisper usa apenas input_features e labels
        return batch


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    args = parse_args()
    set_seed(args.seed)
    os.makedirs(args.output_dir, exist_ok=True)
    os.makedirs(args.adapter_dir, exist_ok=True)

    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"Dispositivo: {device}")
    if device == "cuda":
        print(f"  GPU: {torch.cuda.get_device_name(0)}")
        print(f"  VRAM: {torch.cuda.get_device_properties(0).total_memory / 1024**3:.1f} GB")

    # 1. Carregar o processor do Whisper
    print(f"\n1. A carregar processor de '{args.base_model}'...")
    processor = WhisperProcessor.from_pretrained(args.base_model)

    # 2. Carregar o dataset
    print("\n2. A carregar dataset...")
    ds = load_data(args)
    train_ds = ds["train"]
    eval_ds = ds["eval"]

    # Limitar amostras se pedido
    if args.max_train_samples:
        n = min(args.max_train_samples, len(train_ds))
        train_ds = train_ds.select(range(n))
        print(f"   Treino limitado a {n} exemplos")
    if args.max_eval_samples:
        n = min(args.max_eval_samples, len(eval_ds))
        eval_ds = eval_ds.select(range(n))
        print(f"   Validação limitada a {n} exemplos")

    # 3. Data augmentation
    print("\n3. A configurar data augmentation...")
    augmenter = get_augmenter()
    if augmenter:
        print("   Data augmentation ativada (Gain, Noise, TimeStretch, PitchShift)")
    else:
        print("   Data augmentation desativada (audiomentations não instalado)")

    # 4. Preprocessing
    print(f"\n4. Preprocessing ({len(train_ds)} treino, {len(eval_ds)} validação)...")
    train_ds = preprocess_dataset(train_ds, processor, augmenter=augmenter, is_training=True)
    eval_ds = preprocess_dataset(eval_ds, processor, augmenter=None, is_training=False)

    # 5. Carregar o modelo base
    print(f"\n5. A carregar modelo base '{args.base_model}'...")
    model = WhisperForConditionalGeneration.from_pretrained(
        args.base_model,
        torch_dtype=torch.float16 if device == "cuda" else torch.float32,
        low_cpu_mem_usage=True,
    )

    # Configurar para treino
    model.config.forced_decoder_ids = None
    model.config.suppress_tokens = []
    model.gradient_checkpointing_enable()

    # 6. Aplicar LoRA (configuração AGRESSIVA para 99% de precisão)
    print("\n6. A aplicar adaptador LoRA (configuração AGRESSIVA para 99%)...")
    peft_cfg = LoraConfig(
        r=96,                                    # 6x mais capacidade (16→96) - agressivo mas cabe em 6GB
        lora_alpha=192,                         # Alpha/r = 2 (razão ideal)
        target_modules=[
            "q_proj", "k_proj", "v_proj", "o_proj",  # Todos os attention layers
            "fc1", "fc2",                         # FFN layers (feed-forward)
        ],
        lora_dropout=0.15,                        # Dropout mais alto para evitar overfitting
        bias="lora_only",                        # Treinar bias também
        task_type="SEQ_2_SEQ_LM",
    )
    model = get_peft_model(model, peft_cfg)
    model.print_trainable_parameters()

    # 7. Configurar o treino
    print("\n7. A configurar o treino...")
    data_collator = DataCollatorSpeechSeq2SeqWithPadding(processor=processor)

    training_args = Seq2SeqTrainingArguments(
        output_dir=args.output_dir,
        per_device_train_batch_size=args.batch_size,
        per_device_eval_batch_size=args.batch_size,
        eval_strategy="epoch",
        learning_rate=args.learning_rate,
        weight_decay=0.01,
        num_train_epochs=args.epochs,
        fp16=(device == "cuda"),
        gradient_accumulation_steps=args.gradient_accumulation_steps,
        save_strategy="epoch",
        logging_steps=25,
        push_to_hub=False,
        report_to=[],
        remove_unused_columns=False,
        dataloader_num_workers=0,
        warmup_steps=1000,
        lr_scheduler_type="cosine_with_restarts",
        load_best_model_at_end=True,
        metric_for_best_model="eval_loss",
        greater_is_better=False,
        save_total_limit=3,
        optim="adamw_torch",
    )

    trainer = Seq2SeqTrainer(
        model=model,
        args=training_args,
        train_dataset=train_ds,
        eval_dataset=eval_ds,
        data_collator=data_collator,
    )

    # 7. Treinar!
    print("\n" + "=" * 60)
    print("   A INICIAR O TREINO")
    print("=" * 60)
    trainer.train()
    print("\n" + "=" * 60)
    print("   TREINO CONCLUÍDO")
    print("=" * 60)

    # 8. Guardar o adaptador LoRA
    print(f"\n8. A guardar adaptador LoRA em '{args.adapter_dir}'...")
    model.save_pretrained(args.adapter_dir)
    # Guardar também o processor para que voice.py o encontre
    processor.save_pretrained(args.adapter_dir)

    # 9. (Opcional) Fundir LoRA no modelo base
    if args.merge:
        print("\n9. A fundir LoRA no modelo base...")
        model = model.merge_and_unload()
        fused_dir = Path(args.output_dir) / "fused"
        fused_dir.mkdir(parents=True, exist_ok=True)
        model.save_pretrained(fused_dir)
        processor.save_pretrained(fused_dir)
        print(f"   Modelo fundido guardado em: {fused_dir}")

        # Tentar converter para CTranslate2 (para faster-whisper)
        try:
            import subprocess
            ct2_dir = Path(args.output_dir) / "ct2"
            print(f"   A converter para CTranslate2 em: {ct2_dir}")
            subprocess.run([
                "ct2-whisper-converter",
                "--model", str(fused_dir),
                "--output_dir", str(ct2_dir),
                "--quantization", "float16",
            ], check=True)
            print(f"   CTranslate2 model guardado em: {ct2_dir}")
        except FileNotFoundError:
            print("   AVISO: ct2-whisper-converter não encontrado.")
            print("   Instala com: pip install ctranslate2")
            print("   O adaptador LoRA continua funcional com voice.py.")
        except Exception as e:
            print(f"   AVISO: Conversão CTranslate2 falhou: {e}")
            print("   O adaptador LoRA continua funcional com voice.py.")

    # 10. Resumo final
    print("\n" + "=" * 60)
    print("   TUDO PRONTO!")
    print("=" * 60)
    print(f"\n  Adaptador LoRA:  {Path(args.adapter_dir).resolve()}")
    if args.merge:
        print(f"  Modelo fundido:  {(Path(args.output_dir) / 'fused').resolve()}")
    print(f"\n  Para usar no ORION, garante que config.json tem:")
    print(f'    "whisper_modelo": "{args.adapter_dir}"')
    print(f"\n  Testa com:")
    print(f"    python -c \"from voice import ASR; a=ASR({{'whisper_modelo':'{args.adapter_dir}','whisper_device':'cuda'}}, print)\"")


if __name__ == "__main__":
    main()
