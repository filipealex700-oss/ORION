"""Funde o adaptador LoRA whisper-portuguese-finetuned no whisper-small e guarda o modelo HF completo."""
import json
import os

import torch
from peft import PeftModel
from transformers import WhisperForConditionalGeneration, WhisperProcessor

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ADAPTER = os.path.join(BASE_DIR, "whisper-portuguese-finetuned")
OUT = os.path.join(BASE_DIR, "ct2_build", "fused")

with open(os.path.join(ADAPTER, "adapter_config.json"), encoding="utf-8") as f:
    base = json.load(f)["base_model_name_or_path"]

device = "cuda" if torch.cuda.is_available() else "cpu"
dtype = torch.float16 if device == "cuda" else torch.float32
print(f"base={base} device={device} dtype={dtype}")

modelo = WhisperForConditionalGeneration.from_pretrained(base, torch_dtype=dtype)
modelo = PeftModel.from_pretrained(modelo, ADAPTER).merge_and_unload()
modelo.config.forced_decoder_ids = None
modelo.save_pretrained(OUT)
proc = WhisperProcessor.from_pretrained(ADAPTER)
proc.save_pretrained(OUT)
print("guardado em", OUT)
