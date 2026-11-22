"""Módulo de serviço reutilizável para o Whisper fine-tuned em português (ORION.V3) - VERSÃO OTIMIZADA."""
try:
    import torch
    import librosa
    from transformers import pipeline
except ImportError:
    torch = None
    librosa = None
    pipeline = None

class WhisperService:
    def __init__(self, model_dir: str = "whisper-portuguese-finetuned"):
        """Inicializa e carrega o modelo Whisper fine-tuned uma única vez para a memória."""
        if torch is None or librosa is None or pipeline is None:
            raise RuntimeError(
                "Dependências do Whisper fine-tuned em falta (torch, librosa, transformers). "
                "Para este módulo, ativa o ambiente Python 3.10 com CUDA: setup_python310_finetune.bat"
            )
        self.model_dir = model_dir
        self.device = 0 if torch.cuda.is_available() else -1

        print(f"[WhisperService] A carregar o modelo de '{self.model_dir}'...")
        if self.device == 0:
            print("[WhisperService] Modo de aceleração por GPU (CUDA) ativo.")
        else:
            print("[WhisperService] Aviso: A utilizar CPU para inferência.")

        # Inicialização do pipeline ASR otimizado
        self.asr_pipeline = pipeline(
            "automatic-speech-recognition",
            model=self.model_dir,
            device=self.device
        )
        print("[WhisperService] Modelo carregado com sucesso e pronto para uso.")

    def transcribe(self, audio_path: str) -> str:
        """Transcreve um ficheiro de áudio (.flac ou .wav) para texto em português."""
        try:
            # Carregar e reamostrar para 16kHz via librosa (evita dependências externas do FFmpeg)
            speech_array, sampling_rate = librosa.load(audio_path, sr=16000)

            # Normalização RMS (volume consistente)
            rms = float((speech_array ** 2).mean() ** 0.5)
            if rms > 0:
                speech_array = speech_array / rms

            # Executar a inferência com parâmetros OTIMIZADOS para velocidade + precisão
            result = self.asr_pipeline(
                {"array": speech_array, "sampling_rate": sampling_rate},
                generate_kwargs={
                    "language": "portuguese",
                    "task": "transcribe",
                    "num_beams": 5,             # Beam search equilibrado (velocidade vs precisao) 
                    "temperature": 0.0,          # Determinístico (sem sampling)
                    "best_of": 5,               # Candidatos equilibrados
                    "patience": 1,               # Menos paciência para mais velocidade
                    "length_penalty": 1.0,
                    "repetition_penalty": 1.0,  # Reduzido para evitar falsos positivos
                    "no_repeat_ngram_size": 2,  # Reduzido para mais velocidade
                }
            )

            return result["text"].strip()

        except Exception as e:
            print(f"[WhisperService Error] Ocorreu um erro ao processar o áudio '{audio_path}': {e}")
            raise e

# Bloco de teste direto do módulo
if __name__ == "__main__":
    service = WhisperService()
    test_audio = r"C:\caminho\para\um\audio\de\teste.flac"

    print(f"\nA testar o serviço com: {test_audio}")
    transcription = service.transcribe(test_audio)

    print("\n" + "="*40)
    print("🎯 RESULTADO DO WHISPER SERVICE (OTIMIZADO):")
    print("="*40)
    print(transcription)
    print("="*40)
