"""Benchmark WER/latência: modelo antigo (faster-whisper CT2) vs novo adaptador LoRA whisper-small."""
import csv
import json
import os
import random
import re
import sys
import time
import unicodedata

BASE = os.path.dirname(os.path.abspath(__file__))
DEV = os.path.join(BASE, "cv-corpus-27.0-2026-09-11", "pt", "dev.tsv")
CLIPS = os.path.join(BASE, "cv-corpus-27.0-2026-09-11", "pt", "clips")
ANTIGO = os.path.join(BASE, "modelos", "whisper-portuguese-finetuned")
NOVO = os.path.join(BASE, "whisper-portuguese-finetuned")
N = int(sys.argv[1]) if len(sys.argv) > 1 else 50


def normalizar(t):
    t = unicodedata.normalize("NFD", t.lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    t = re.sub(r"[^\w\s]", " ", t, flags=re.UNICODE)
    return t.split()


def wer(ref, hyp):
    r, h = normalizar(ref), normalizar(hyp)
    if not r:
        return 0.0 if not h else 1.0
    d = [[0] * (len(h) + 1) for _ in range(len(r) + 1)]
    for i in range(len(r) + 1):
        d[i][0] = i
    for j in range(len(h) + 1):
        d[0][j] = j
    for i in range(1, len(r) + 1):
        for j in range(1, len(h) + 1):
            d[i][j] = min(d[i - 1][j] + 1, d[i][j - 1] + 1,
                          d[i - 1][j - 1] + (r[i - 1] != h[j - 1]))
    return d[len(r)][len(h)] / len(r)


def carregar_amostras(n):
    rows = []
    with open(DEV, encoding="utf-8") as f:
        rd = csv.DictReader(f, delimiter="\t")
        for row in rd:
            p = os.path.join(CLIPS, row["path"])
            s = (row.get("sentence") or "").strip()
            if s and os.path.exists(p):
                rows.append((p, s))
    random.seed(42)
    random.shuffle(rows)
    return rows[:n]


def rodar_antigo(amostras):
    from faster_whisper import WhisperModel
    import librosa
    m = WhisperModel(ANTIGO, device="cpu", compute_type="int8", cpu_threads=8)
    out = []
    for path, ref in amostras:
        audio, _ = librosa.load(path, sr=16000)
        t0 = time.time()
        segs, _ = m.transcribe(audio, language="pt", beam_size=5,
                               vad_filter=True,
                               vad_parameters={"min_silence_duration_ms": 500})
        txt = " ".join(s.text.strip() for s in segs).strip()
        out.append({"ref": ref, "hyp": txt, "lat": time.time() - t0})
    return out


def rodar_novo(amostras):
    import torch
    from transformers import WhisperForConditionalGeneration, WhisperProcessor
    from peft import PeftModel
    with open(os.path.join(NOVO, "adapter_config.json"), encoding="utf-8") as f:
        base = json.load(f)["base_model_name_or_path"]
    modelo = WhisperForConditionalGeneration.from_pretrained(base, torch_dtype=torch.float32)
    modelo = PeftModel.from_pretrained(modelo, NOVO).merge_and_unload()
    modelo.generation_config.forced_decoder_ids = None
    modelo.eval()
    proc = WhisperProcessor.from_pretrained(NOVO)
    import librosa
    out = []
    with torch.no_grad():
        for path, ref in amostras:
            audio, _ = librosa.load(path, sr=16000)
            inp = proc(audio=audio, sampling_rate=16000, return_tensors="pt")
            t0 = time.time()
            ids = modelo.generate(**inp, language="portuguese", task="transcribe",
                                  max_new_tokens=224)
            lat = time.time() - t0
            txt = proc.tokenizer.decode(ids[0], skip_special_tokens=True).strip()
            out.append({"ref": ref, "hyp": txt, "lat": lat})
    return out


def relatorio(nome, res):
    wers = [wer(r["ref"], r["hyp"]) for r in res]
    lat = [r["lat"] for r in res]
    mw = sum(wers) / len(wers) * 100
    print(f"\n=== {nome} ===")
    print(f"clips: {len(res)}")
    print(f"WER médio: {mw:.2f}%")
    print(f"latência média: {sum(lat)/len(lat)*1000:.0f} ms/clip "
          f"(min {min(lat)*1000:.0f}, max {max(lat)*1000:.0f})")
    piores = sorted(zip(wers, res), key=lambda x: -x[0])[:5]
    for w, r in piores:
        print(f"  WER {w*100:5.1f}% | ref: {r['ref'][:60]} | hyp: {r['hyp'][:60]}")
    return mw


def main():
    amostras = carregar_amostras(N)
    print(f"Amostra: {len(amostras)} clips do dev.tsv (seed 42)")
    res_antigo = rodar_antigo(amostras)
    print("antigo OK")
    res_novo = rodar_novo(amostras)
    print("novo OK")
    with open(os.path.join(BASE, "bench_whisper_resultados.json"), "w", encoding="utf-8") as f:
        json.dump({"antigo": res_antigo, "novo": res_novo}, f, ensure_ascii=False, indent=1)
    wa = relatorio("ANTIGO (faster-whisper CT2, whisper-base LoRA r16)", res_antigo)
    wn = relatorio("NOVO (HF whisper-small + LoRA r96)", res_novo)
    print(f"\n>>> Diferença de WER: {wa - wn:+.2f} pontos (negativo = novo melhor)")


if __name__ == "__main__":
    main()
