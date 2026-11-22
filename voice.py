"""Ouvidos e voz.
Ouvir: microfone -> deteção de fala adaptativa -> Whisper local (faster-whisper ou o teu fine-tuned
       via Transformers/LoRA) -> devolve texto + confiança.
Falar: voz Edge TTS (online) ou SAPI do Windows (offline), escolhendo voz feminina ou masculina."""
import json
import os
import queue
import re
import threading
import time
from collections import deque

import numpy as np

from config import BASE

SR = 16000
BLOCO = 512
ALUCINACOES = ("obrigado por assistir", "legendas pela comunidade", "amara.org",
               "subtitles by", "até à próxima", "ate a proxima", "e aí, pessoal")
NOMES_FASTER = {"tiny", "base", "small", "medium", "large-v2", "large-v3", "large-v3-turbo", "turbo",
                "tiny.en", "base.en", "small.en", "medium.en", "distil-large-v3"}


def _localizar(nome):
    """Procura o modelo em modelos/<nome>, <nome> ao lado do ORION, ou caminho absoluto.
    Se existir mais do que uma pasta (ex.: adaptador LoRA na raiz e versão convertida
    em modelos/), prefere a que tiver model.bin (CTranslate2/faster-whisper, mais rápido)
    sobre a pasta HF/LoRA."""
    candidatos = [c for c in (os.path.join(BASE, "modelos", nome),
                              os.path.join(BASE, nome), nome) if os.path.isdir(c)]
    if not candidatos:
        return None
    for c in candidatos:
        if os.path.exists(os.path.join(c, "model.bin")):
            return c
    for c in candidatos:
        if os.path.exists(os.path.join(c, "adapter_config.json")):
            return c
    return candidatos[0]


class ASR:
    """Reconhecimento de voz com 2 motores:
    - faster-whisper (CTranslate2): modelos normais (medium, small...) ou pastas convertidas (model.bin);
    - Transformers: o teu Whisper fine-tuned (pasta HF completa ou adaptador LoRA, que é fundido no modelo base).
    Se a GPU falhar (ex.: falta cublas64_12.dll), cai para CPU em vez de não arrancar."""

    def __init__(self, cfg, emitir):
        self.cfg, self.emitir = cfg, emitir
        nome = cfg["whisper_modelo"]
        pasta = _localizar(nome)
        self.dev = cfg.get("whisper_device", "cpu")
        if pasta and (os.path.exists(os.path.join(pasta, "adapter_config.json"))
                      or (os.path.exists(os.path.join(pasta, "config.json"))
                          and not os.path.exists(os.path.join(pasta, "model.bin")))):
            self.motor = "hf"
            try:
                self._hf(pasta)
            except Exception as e:
                self.emitir("sistema", f"Whisper HuggingFace falhou ({e}). A usar faster-whisper.")
                self.motor = "faster"
                fw_dir = os.path.join(BASE, "modelos", "whisper-portuguese-finetuned")
                candidato = fw_dir if os.path.exists(os.path.join(fw_dir, "model.bin")) else "small"
                self._faster(candidato)
        elif pasta or nome in NOMES_FASTER:
            self.motor = "faster"
            self._faster(pasta or nome)
        else:
            self.emitir("sistema", f"Whisper '{nome}' não encontrado localmente. A usar 'small'.")
            self.motor = "faster"
            self._faster("small")

    def _faster(self, alvo):
        # DLLs CUDA do pip (nvidia-*) nem sempre estão no PATH (ex.: fora do iniciar.bat)
        nvidia = os.path.join(BASE, "venv", "Lib", "site-packages", "nvidia")
        if os.path.isdir(nvidia):
            for pkg in os.listdir(nvidia):
                bindir = os.path.join(nvidia, pkg, "bin")
                if os.path.isdir(bindir):
                    try:
                        os.add_dll_directory(bindir)
                    except (AttributeError, OSError):
                        os.environ["PATH"] = bindir + os.pathsep + os.environ["PATH"]
        from faster_whisper import WhisperModel
        th = int(self.cfg.get("whisper_threads", 4))  # Reduzido de 8 para 4
        try:
            if self.dev != "cuda":
                raise RuntimeError("cpu pedido")
            self.modelo = WhisperModel(alvo, device="cuda", compute_type="int8_float16")
        except Exception as e:
            if self.dev == "cuda":
                self.emitir("sistema", f"Whisper na GPU falhou ({str(e)[:120]}). A usar o processador.")
            self.dev = "cpu"
            self.modelo = WhisperModel(alvo, device="cpu", compute_type="int8", cpu_threads=th)
        self.emitir("sistema", f"Whisper '{os.path.basename(str(alvo))}' pronto (faster-whisper, {self.dev}).")

    def _hf(self, pasta):
        import torch
        from transformers import WhisperForConditionalGeneration, WhisperProcessor, pipeline
        usar_gpu = self.dev == "cuda" and torch.cuda.is_available()
        if self.dev == "cuda" and not usar_gpu:
            self.emitir("sistema", "CUDA indisponível no PyTorch: o Whisper fine-tuned vai correr no processador.")
        tipo = torch.float16 if usar_gpu else torch.float32
        adaptador = os.path.join(pasta, "adapter_config.json")
        if os.path.exists(adaptador):
            from peft import PeftModel
            with open(adaptador, encoding="utf-8") as f:
                base = json.load(f).get("base_model_name_or_path") or "openai/whisper-small"
            self.emitir("sistema", f"A juntar o adaptador LoRA '{os.path.basename(pasta)}' ao modelo base {base}...")
            modelo = WhisperForConditionalGeneration.from_pretrained(base, torch_dtype=tipo)
            modelo = PeftModel.from_pretrained(modelo, pasta).merge_and_unload()
            try:
                proc = WhisperProcessor.from_pretrained(pasta)
            except Exception:
                proc = WhisperProcessor.from_pretrained(base)
        else:
            modelo = WhisperForConditionalGeneration.from_pretrained(pasta, torch_dtype=tipo)
            proc = WhisperProcessor.from_pretrained(pasta)
        modelo.generation_config.forced_decoder_ids = None
        self.proc = proc
        self.modelo = pipeline("automatic-speech-recognition", model=modelo, tokenizer=proc.tokenizer,
                               feature_extractor=proc.feature_extractor, torch_dtype=tipo,
                               device=0 if usar_gpu else -1)
        self.dev = "cuda" if usar_gpu else "cpu"
        self.emitir("sistema", f"Whisper fine-tuned '{os.path.basename(pasta)}' pronto ({self.dev}).")

    def transcrever(self, audio, prompt):
        """-> (texto, confiança 0..1)"""
        try:
            if self.motor == "faster":
                segs, _ = self.modelo.transcribe(
                    audio, language="pt",
                    beam_size=int(self.cfg.get("whisper_beam", 5)),
                    best_of=5,
                    temperature=[0.0, 0.2, 0.4, 0.6, 0.8, 1.0],
                    initial_prompt=prompt,
                    condition_on_previous_text=False,
                    vad_filter=True,
                    vad_parameters={"min_silence_duration_ms": 500})
                segs = list(segs)
                texto = " ".join(s.text.strip() for s in segs).strip()
                if not segs:
                    return "", 0.0
                lp = sum(s.avg_logprob for s in segs) / len(segs)
                return texto, float(np.clip(np.exp(lp), 0, 1))
            r = self.modelo({"array": audio, "sampling_rate": SR},
                            generate_kwargs={"language": "portuguese", "task": "transcribe"})
            texto = (r.get("text", "") if isinstance(r, dict) else str(r)).strip()
            return texto, 0.9 if texto else 0.0
        except Exception as e:
            self.emitir("sistema", f"Erro no reconhecimento Whisper: {e}")
            return "", 0.0


class Voz:
    def __init__(self, cfg, defs, memoria, emitir=None, modo_texto=False):
        self.cfg, self.defs, self.mem = cfg, defs, memoria
        self.emitir = emitir or (lambda *a, **k: None)
        self.modo_texto = modo_texto
        self.nivel = 0.0
        self.mic_on = True
        self.a_falar = threading.Event()
        self._lock = threading.RLock()
        self._local = threading.local()
        self._voz_atual = ""
        self._avisos = set()
        self.q = queue.Queue()
        self.stream = None
        if modo_texto:
            return

        import sounddevice as sd

        self.emitir("sistema", f"A carregar o Whisper '{cfg['whisper_modelo']}'...")
        self.asr = ASR(cfg, self.emitir)
        # Usar dispositivo de áudio da config se especificado
        device_id = cfg.get("audio_device", None)
        if device_id is not None:
            self.emitir("sistema", f"A usar dispositivo de áudio {device_id}")
        self.stream = sd.InputStream(samplerate=SR, channels=1, dtype="float32",
                                     blocksize=BLOCO, callback=self._cb, device=device_id)
        self.stream.start()
        self._calibrar()

    # ------------------------------------------------------------ microfone
    def _cb(self, indata, frames, tempo, estado):
        x = indata[:, 0]
        self.nivel = float(np.sqrt(np.mean(x ** 2)))
        if self.mic_on and not self.a_falar.is_set():
            self.q.put(x.copy())

    def _calibrar(self):
        self.emitir("sistema", "A calibrar o ruído ambiente (1,5 s de silêncio)...")
        rms = []
        for _ in range(int(1.5 * SR / BLOCO)):
            try:
                rms.append(float(np.sqrt(np.mean(self.q.get(timeout=2) ** 2))))
            except queue.Empty:
                break
        self.ruido = float(np.median(rms)) if rms else 0.005
        self.limiar = max(self.ruido * self.cfg["sensibilidade_microfone"], 0.008)

    def _capturar(self, parar):
        pre = deque(maxlen=int(0.3 * SR / BLOCO))
        frames, gravando, silencio = [], False, 0
        fim = self.cfg.get("silencio_fim_seg", 0.9)
        while not parar.is_set():
            try:
                bloco = self.q.get(timeout=0.25)
            except queue.Empty:
                continue
            if self.a_falar.is_set() or not self.mic_on:
                frames, gravando, silencio = [], False, 0
                pre.clear()
                continue
            rms = float(np.sqrt(np.mean(bloco ** 2)))
            if not gravando:
                if rms > self.limiar:
                    gravando, frames, silencio = True, list(pre) + [bloco], 0
                    self.emitir("estado", "a ouvir")
                else:
                    pre.append(bloco)
                    self.ruido = 0.98 * self.ruido + 0.02 * rms  # o limiar adapta-se ao ruído
                    self.limiar = max(self.ruido * self.cfg["sensibilidade_microfone"], 0.008)
            else:
                frames.append(bloco)
                silencio = 0 if rms > self.limiar else silencio + 1
                if silencio * BLOCO / SR > fim or len(frames) * BLOCO / SR > 15:
                    audio = np.concatenate(frames)
                    return audio if len(audio) / SR >= 0.4 else None
        return None

    # ------------------------------------------------------------ reconhecimento
    def _prompt(self):
        palavras = list(self.cfg.get("programas", {}).keys())[:12]
        try:
            palavras += [r[0] for r in self.mem.db.execute("SELECT palavra FROM vocabulario").fetchall()][:30]
        except Exception:
            pass
        base = "Conversa em português de Portugal com a assistente ORION. O utilizador fala em português europeu. "
        # Adicionar instruções para melhor reconhecimento
        instr = "Reconhece comandos de voz, perguntas e conversação natural. Corrige erros comuns de transcrição. "
        return base + instr + ("Vocabulário: " + ", ".join(p for p in palavras if p) + "." if palavras else "")

    def _corrigir(self, texto):
        try:
            for errado, certo in self.mem.db.execute("SELECT errado, certo FROM correcoes").fetchall():
                texto = re.sub(rf"(?<!\w){re.escape(errado)}(?!\w)", certo, texto, flags=re.I)
        except Exception:
            pass
        return texto

    def ouvir(self, parar):
        """Bloqueia até ouvir uma frase. Devolve {'texto','conf'} ou None."""
        audio = self._capturar(parar)
        if audio is None:
            return None
        self.emitir("estado", "a transcrever")
        audio = audio - float(np.mean(audio))
        pico = float(np.max(np.abs(audio)))
        if pico > 1e-4:
            audio = audio / pico * 0.9  # normaliza o volume: ajuda com microfones baixos
        texto, conf = self.asr.transcrever(audio.astype(np.float32), self._prompt())
        if not texto or len(texto) < 2 or any(a in texto.lower() for a in ALUCINACOES):
            return None
        return {"texto": self._corrigir(texto), "conf": conf}

    # ------------------------------------------------------------ voz (SAPI)
    def _com(self):
        if not getattr(self._local, "ok", False):
            try:
                import pythoncom
                pythoncom.CoInitialize()
            except Exception:
                pass
            self._local.ok = True

    def _sapi_vozes(self):
        self._com()
        import win32com.client
        sp = win32com.client.Dispatch("SAPI.SpVoice")
        vozes = []
        for v in sp.GetVoices():
            def attr(n, v=v):
                try:
                    return (v.GetAttribute(n) or "").lower()
                except Exception:
                    return ""
            vozes.append({"obj": v, "nome": v.GetDescription(),
                         "genero": attr("Gender"), "lang": attr("Language")})
        return sp, vozes

    def listar_vozes(self):
        _, vozes = self._sapi_vozes()
        return [{k: v[k] for k in ("nome", "genero", "lang")} for v in vozes]

    def _escolher(self, vozes):
        genero = "female" if self.defs.get("genero") == "feminino" else "male"
        manual = (self.defs.get("voz_nome") or "").lower()
        if manual:
            for v in vozes:
                if manual in v["nome"].lower():
                    return v
        langs = lambda v: v["lang"].split(";")
        cand = [v for v in vozes if "816" in langs(v) or "416" in langs(v) or "portug" in v["nome"].lower()]
        cand.sort(key=lambda v: 0 if ("816" in langs(v) or "portugal" in v["nome"].lower()) else 1)
        for v in cand:
            if v["genero"] == genero:
                return v
        nomes = self.cfg.get("vozes", {}).get("feminino" if genero == "female" else "masculino", [])
        for v in cand:
            if any(n in v["nome"].lower() for n in nomes):
                return v
        for v in vozes:
            if v["genero"] == genero:
                self._avisar(f"sem-{genero}-pt", "Não há voz em português com esse género; a usar "
                           f"'{v['nome']}'. Instala mais vozes em Definições > Hora e idioma > Voz.")
                return v
        if cand:
            self._avisar(f"sem-{genero}", "Não encontrei voz desse género; a usar a voz portuguesa disponível.")
            return cand[0]
        return None

    def _avisar(self, chave, msg):
        if chave not in self._avisos:
            self._avisos.add(chave)
            self.emitir("sistema", msg)

    def _edge_tts_falar(self, texto):
        """Gera voz usando Edge TTS (Microsoft Azure)."""
        try:
            import edge_tts
            import asyncio
            import tempfile

            edge_cfg = self.cfg.get("edge_tts", {})
            voice = edge_cfg.get("voice", "pt-PT-RaquelNeural")
            rate = edge_cfg.get("rate", "+0%")

            if not texto or not texto.strip():
                raise ValueError("Texto vazio")

            self.emitir("sistema", f"A gerar voz com Edge TTS ({voice})...")

            fd, temp_file = tempfile.mkstemp(suffix=".mp3", prefix="orion_voice_")
            os.close(fd)

            async def save_audio():
                communicate = edge_tts.Communicate(texto, voice, rate=rate)
                await communicate.save(temp_file)

            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None

            if loop and loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor(1) as pool:
                    pool.submit(lambda: asyncio.run(save_audio())).result()
            else:
                asyncio.run(save_audio())

            if not os.path.exists(temp_file) or os.path.getsize(temp_file) == 0:
                raise ValueError("Ficheiro de áudio vazio ou não criado")

            try:
                import pygame
                pygame.mixer.init()
                pygame.mixer.music.load(temp_file)
                pygame.mixer.music.play()
                while pygame.mixer.music.get_busy():
                    pygame.time.Clock().tick(10)
                pygame.mixer.music.unload()
            except ImportError:
                import ctypes
                mci = ctypes.windll.winmm
                if temp_file:
                    safe = str(temp_file).replace("/", "\\")
                    alias = f"hm_{int(time.time()*1000)}"
                    mci.mciSendStringW(f'open "{safe}" type mpegvideo alias {alias}', None, 0, None)
                    mci.mciSendStringW(f'play {alias} wait', None, 0, None)
                    mci.mciSendStringW(f'close {alias}', None, 0, None)

            try:
                os.remove(temp_file)
            except OSError:
                pass

        except Exception as e:
            self.emitir("sistema", f"Erro Edge TTS: {e}. A usar SAPI.")
            return False
        return True

    def falar(self, texto):
        with self._lock:
            self.emitir("disse", texto)
            if self.modo_texto or self.defs.get("silencio"):
                return
            self.a_falar.set()
            try:
                provider = self.cfg.get("voz_provider", "sapi")
                if provider == "edge":
                    if self._edge_tts_falar(texto):
                        self.emitir("voz", "Edge TTS")
                    else:
                        self._sapi_falar(texto)
                else:
                    self._sapi_falar(texto)
            except Exception as e:
                self.emitir("sistema", f"Erro a falar: {e}")
            finally:
                time.sleep(0.35)  # deixa o eco acabar antes de voltar a ouvir
                while not self.q.empty():
                    self.q.get_nowait()
                self.a_falar.clear()

    def _sapi_falar(self, texto):
        """Fala usando SAPI do Windows (método original)."""
        sp, vozes = self._sapi_vozes()
        v = self._escolher(vozes)
        if v:
            sp.Voice = v["obj"]
            if v["nome"] != self._voz_atual:
                self._voz_atual = v["nome"]
                self.emitir("voz", v["nome"])
        vel = int(self.defs.get("velocidade", 175))
        sp.Rate = max(-10, min(10, round((vel - 175) / 10)))
        sp.Speak(texto)

    def parar(self):
        try:
            if self.stream:
                self.stream.stop()
        except Exception:
            pass