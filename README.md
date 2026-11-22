# ORION — assistente pessoal local (Windows)

Corre no teu PC, sem APIs externas: cérebro (Ollama), ouvidos (Whisper), voz (SAPI do Windows), memória (SQLite).
Internet só é precisa na instalação.

## Configurado para GTX 1660 (6 GB VRAM) · Ryzen 5 5600X · 32 GB RAM
- **LLM `qwen2.5:3b` na placa gráfica** (~2 GB): cabe inteiro na VRAM — respostas em ~0.5-15s.
  O `qwen2.5:7b` foi testado e era ~5-10x mais lento por falta de VRAM.
- **Whisper `small` fine-tuned em português (CT2)** em `modelos/whisper-portuguese-finetuned/` —
  corre no GPU via faster-whisper (~0.5s/clip). O adaptador LoRA original está em
  `whisper-portuguese-finetuned/` (excluído do repo — regenera-se com `fine_tune_whisper.py`).
- **Voz Edge TTS** (`voz_provider: "edge"`, pt-PT-RaquelNeural) com fallback automático para SAPI.
- Roteamento por palavras-chave + rede neural (`routing.py`, `modelos/router_nn.pkl` via `treinar_router.py`).
- Contexto 512 tokens e `keep_alive` 30 min para o Ollama não descarregar os modelos.

## Novo: arquitetura inspirada no OpenJarvis
Presets por hardware (`python main.py --preset equilibrado --descarregar`), roteamento rápido/principal, traços e métricas,
skills em `skills\*.md` e `avaliar.py` para comparar modelos no teu PC. Vê `ARQUITETURA.md`.

## Instalar e arrancar
1. Python 3.10+ ("Add to PATH") e Ollama (ollama.com), com o Ollama aberto.
2. `instalar.bat` (pacotes) e depois `ollama pull qwen2.5:3b phi3:mini nomic-embed-text`.
3. `cp config.example.json config.json` e ajusta os caminhos (obsidian, pastas protegidas).
4. `iniciar.bat` abre a **interface web** (http://127.0.0.1:8765). `iniciar_gui.bat` abre a janela desktop.
5. `iniciar_texto.bat` é um modo de teste só com teclado.

## Whisper fine-tuned (opcional, para treinar o teu próprio)
1. `python fine_tune_whisper.py --cv_dir <pasta-do-corpus> --epochs 20 --merge`
   — treina LoRA no whisper-small com Common Voice e grava o adaptador em `whisper-portuguese-finetuned/`.
2. `python build_ct2.py` — funde o LoRA no modelo base (HF completo).
3. `python run_ct2_convert.py` (no venv com transformers 5.x + ctranslate2) — gera o modelo CT2.
4. Copia `model.bin`, `config.json`, `vocabulary.json` do CT2 para `modelos/whisper-portuguese-finetuned/`.
Sem este modelo, o ORION usa o `small` standard do faster-whisper (a configurar em `whisper_modelo`).

## Criar o executável (.exe)
Duplo clique em `build_exe.bat` (depois do `instalar.bat`). Demora alguns minutos e cria `dist\ORION\ORION.exe`.
- Mantém a pasta `ORION` inteira junta (não é um ficheiro único: as bibliotecas e modelos são grandes).
- O `config.json`, as bases de dados e os projetos ficam ao lado do `.exe`. O registo de erros é `orion.log`.
- O Ollama continua a ser necessário (é o cérebro). A 1.ª vez, o Whisper descarrega o modelo (precisa de internet);
  para ficar 100% offline, descarrega-o antes e põe-no em `modelos\small\`.
- Para executar código `.py` a partir do .exe é preciso ter o Python instalado no Windows.

## A janela
- Mostra **o que ela ouviu** (com a % de certeza; a laranja quando duvidou; a cinzento o que ouviu sem "ORION") e **o que ela disse**.
- Indicador de estado (à escuta / a ouvir / a perceber / a pensar / a falar) e nível do microfone.
- **Mulher / Homem**: muda a voz e também a forma de ela falar (estou pronta / pronto). Também por voz: "muda para voz de homem".
- Velocidade da fala, "Testar voz", "Vozes" (as instaladas), microfone on/off, modo só texto, "Iniciar com o Windows",
  "Aprovar ferramentas" (rever código que ela escreveu).
- Painel da direita: ações executadas, trabalhos em segundo plano e o que ela aprendeu.

## Interface web
- A interface web oferece a mesma funcionalidade que a janela, mas num navegador.
- **Personalização visual**: edita a secção `web.tema` no `config.json` para mudar cores (primário, secundário, fundo, texto, bordas, sucesso, erro, aviso).
- **Configuração do servidor**: define `web.host` e `web.porta` no `config.json` para mudar o endereço e porta.
- **Acesso pela rede**: para aceder de outros dispositivos, define `ORION_WEB_TOKEN` como variável de ambiente com pelo menos 24 caracteres.

### Vozes
Por padrão usa as vozes do Windows (SAPI, offline). Escolhe por género e idioma (816 = PT-PT, 416 = PT-BR). O que existe depende do teu Windows:
vê em "Vozes". Se não houver voz masculina em português, ela avisa e usa a melhor disponível; podes instalar mais em
Definições > Hora e idioma > Voz. Podes forçar uma voz com `"voz_nome"` no `config.json`.

**Edge TTS (opcional):** Para usar vozes mais naturais do Microsoft Edge (online, gratuito):
1. No `config.json`, define:
   - `"voz_provider": "edge"`
   - `"edge_tts.voice": "pt-PT-FrancescaNeural"` (ou outra voz: `pt-PT-ManuelNeural`, `pt-BR-FranciscaNeural`, etc.)
   - `"edge_tts.rate": "+0%"` (velocidade: `-50%` a `+50%`)
2. Lista de vozes disponíveis: `edge-tts --list-voices`
Se houver erro, volta automaticamente para SAPI.

## Perceber melhor
- Whisper fine-tuned com busca ampla (`whisper_beam`), VAD, normalização do áudio, ruído ambiente que se adapta,
  e vocabulário próprio (nomes dos programas + palavras que lhe ensinares: "ensina a palavra Arduino").
- Se a certeza for baixa, ela pede para repetires (no máximo 2 vezes seguidas; `confianca_minima`).
- Corrige-a: "não disse 'ipom', disse ORION" → ela aprende para sempre (tabela `correcoes`).
- Alternativas de modelo: `whisper_modelo` aceita qualquer modelo faster-whisper (`small`, `medium`, `large-v3-turbo`)
  ou uma pasta CT2 própria; com `"whisper_device": "cuda"` corre na placa gráfica.

## Trabalho sem estares presente
Enquanto o ORION estiver aberto (podes minimizá-lo), ela executa trabalhos agendados: "todos os dias às 8h faz o resumo do dia",
"agora cria um script que organiza ficheiros", "lembra-me às 17:00 de beber água", "de 2 em 2 horas ...".
- Só usam ferramentas seguras (resumos, listas, criar/editar código, organizar pastas). Nunca abrem programas nem executam código sozinhos.
- Esperam que não estejas a usar o ORION. No fim guardam um relatório e ela conta-te quando voltares a falar com ela.
- "O que fizeste?" mostra os resultados; "lista os trabalhos" / "cancela o trabalho X" gerem a agenda.
- O PC tem de estar ligado e o ORION aberto. Com "Iniciar com o Windows" arranca sozinho, minimizado.

## Aprender sozinha (nos tempos livres)
Quando está em repouso, de 30 em 30 minutos (`aprendizagem_intervalo_min`):
1. Lê as conversas novas e guarda factos e preferências que disseste (sem dados sensíveis) na memória.
2. Deteta hábitos (ex.: abres o VS Code todos os dias às 9h) e propõe lembrar-te à hora certa.
3. Aprende as tuas correções de voz e o vocabulário.
4. Regista o teu feedback ("boa resposta", "má resposta, devias ter dito X") em `treino\feedback.jsonl`.

**Limite honesto:** isto não altera o modelo de linguagem; ela fica a conhecer-te melhor, mas não "re-treina" o Llama.
O `feedback.jsonl` fica preparado para um afinamento (fine-tuning) futuro, que exige GPU e é feito à parte.

## Código, trabalho e ações
- Código: "cria um script Python que...", "cria o código Arduino para..." (`.ino`), "corrige o erro X". Fica em `projetos\`
  com cópia `.bak`. Executar `.py` pede sempre a tua confirmação.
- Tarefas, candidaturas a emprego e carteira de ações (preços registados por ti; só dá números, não recomenda comprar/vender).

## Ficheiros importantes
`config.json` (tudo configurável) · `definicoes.json` (género, velocidade) · `orion_memoria.db` (memória e aprendizagem) ·
`orion_gestao.db` (tarefas, empregos, ações) · `orion_jobs.db` (trabalhos agendados) · `projetos\` · `plugins\` ·
`treino\` · `orion.log` (só no .exe).

## Problemas comuns
- "Não consegui ligar ao Ollama": abre o Ollama. "Falta o modelo": `ollama pull <nome>`.
- Não apanha "ORION": vê o que ela escreveu em "Tu:" e acrescenta essa forma a `wake_variantes`, ou corrige-a por voz.
- Apanha ruído ou não ouve: ajusta `sensibilidade_microfone`.
- Lenta: modelo menor (`llama3.2:3b`, Whisper `base`).
#
# ORION
