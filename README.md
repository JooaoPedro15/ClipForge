<div align="center">
  <img src="resources/icon.png" alt="ClipForge" width="96" height="96" />

  <h1>ClipForge</h1>

  <p><strong>Aplicativo desktop de edicao para creators, focado em acelerar cortes e legendas.</strong></p>

  <p>
    <img alt="Electron" src="https://img.shields.io/badge/Electron-41-47848F?style=for-the-badge&logo=electron&logoColor=white" />
    <img alt="React" src="https://img.shields.io/badge/React-19-61DAFB?style=for-the-badge&logo=react&logoColor=0B1220" />
    <img alt="TypeScript" src="https://img.shields.io/badge/TypeScript-6-3178C6?style=for-the-badge&logo=typescript&logoColor=white" />
    <img alt="Vite" src="https://img.shields.io/badge/Vite-8-646CFF?style=for-the-badge&logo=vite&logoColor=white" />
  </p>
</div>

---

## Sobre

O **ClipForge** e um app desktop feito com Electron, React e TypeScript para centralizar ferramentas locais de edicao usadas no workflow de criadores.

O escopo atual e simples: preparar material bruto com rapidez, gerar legendas e apoiar futuras ferramentas de edicao. Modulos comerciais e de inteligencia de parcerias foram separados do ClipForge.

## Funcionalidades

| Modulo | Status | O que faz |
| --- | --- | --- |
| **SubtitleForge** | Estavel | Transcreve audio/video com Whisper e gera arquivos `.srt`. |
| **Pre-Editor** | Em evolucao | Pre-edita videos brutos, comprime pausas e gera uma versao longa mais rapida de revisar. |

### Traducao de legendas (SubtitleForge)

O SubtitleForge tem duas opcoes opcionais para traduzir a legenda gerada, alem do `.srt` original: **"Traduzir p/ ingles"** e **"Traduzir p/ chines (simplificado)"**. Ao marcar uma ou ambas, o app gera arquivos adicionais (`arquivo.en.srt`, `arquivo.zh.srt`) ao lado do `.srt` original.

- **Chines** usa um **LLM local via Ollama** (padrao `qwen2.5:7b-instruct`, custo zero, offline, ~5,5GB de VRAM). Sem o Ollama rodando, a traducao pro chines falha com erro claro — nao cai em silencio no NLLB.
- **Ingles** usa o modelo NLLB (ctranslate2), que tambem pode ser forcado pro chines com `CLIPFORGE_TRANSLATION_ENGINE=nllb` (qualidade bem menor).

#### Chines: pipeline em dois estagios (LLM local)

Os cards de exibicao de um video vertical sao cortados a cada 2-3 palavras; traduzir card a card gera fragmento de frase, ordem de palavras do portugues e genero chutado. Por isso a traducao pro chines roda em dois estagios, ambos com a **transcricao inteira** (`arquivo.cards.json`, gravado pela transcricao com `segment_id` e `avg_logprob` de cada card):

1. **Glossario do video** (`glossary_service.build_video_glossary_llm`): o modelo recebe a transcricao inteira, o glossario do canal (travado) e o campo **"Tipo de video"** da UI (ex.: `gameplay de terror`, `corte engracado`, `reacao`), e devolve resumo da historia, personagens com genero/relacao/grafia chinesa fixa, termos recorrentes, registro adequado e os indices de cards ilegiveis.
2. **Traducao por frase** (`llm_translation.translate_with_llm`): o modelo recebe a transcricao inteira + o glossario e devolve **um objeto por frase**, agrupando cards consecutivos: `{"cards": [7, 8, 9], "start": 7.4, "end": 9.8, "zh": "...", "flag": ""}`. O `.zh.srt` final e montado a partir desses grupos, nao dos cards. Cards com `avg_logprob < -0.6` (Whisper inseguro) vao marcados como `low_confidence` pro modelo nao inventar texto no buraco.

As fronteiras de frase sao decididas pelo **Python**, nao pelo modelo (`llm_translation.propose_sentences`): ponto fecha sempre, virgula fecha a partir de 5 palavras, nunca corta antes de preposicao/conectivo nem num card terminado em palavra pendente, e frase com menos de 1,2s funde com a vizinha. O modelo traduz **uma frase por chamada**, vendo a transcricao inteira e as linhas ja traduzidas — deixa-lo agrupar e traduzir tudo de uma vez fazia o modelo de 7B resumir o video numa linha so ou deslocar o conteudo entre as frases.

Chamadas usam `temperature: 0` e saida JSON forcada. Resposta rejeitada (id errado, vazia, letra latina, longa demais, mesmo conectivo de abertura da linha anterior) volta pro modelo com o motivo e um pouco de temperatura (0 / 0,4 / 0,7) — com 0 ele repetiria a mesma resposta. Linha que passa de 20 caracteres e dividida em quantas legendas forem precisas, sempre na pontuacao chinesa, com o tempo repartido em fronteira de card. Pontuacao latina (`,` `.`) vira a de largura inteira (`，` `。`) e aspas/parenteses caem.

**Glossario persistente do canal** em `D:\Projetos\subtitle-forge\glossario_canal.json` (ver `DEFAULT_CHANNEL_GLOSSARY_PATH` em `python/glossary_service.py`): nome do canal, bordoes, personagens e jogos recorrentes. Entra no estagio 1 como **travado** — grafia que ja existe nunca e reescrita — e no fim do video as entradas novas sao fundidas nele. E um JSON simples, pode ser editado a mao pra corrigir uma grafia.

O campo **"Tipo de video"** tambem e repassado pela queima (hardsub), pra legenda gerada na hora da queima sair no mesmo registro da gerada na transcricao.

**Validacao antes de gravar** (`subtitle_validation.py`, sem chamar API): todo card em exatamente um grupo e em ordem; nenhum caractere latino nem pontuacao latina na linha traduzida; no maximo 20 caracteres chineses por linha (video vertical); nenhum grupo com menos de 1,2s na tela; 她 com sujeito masculino / 他 com feminino; 嫁给 com sujeito masculino / 娶 com feminino; nome com grafia divergente da canonica (variantes do glossario, canonico + sufixo tipo 埃德加尔, ultimo caractere trocado tipo 伯纳德/伯纳多); personagem trocado (a fonte cita um nome, a traducao usa outro no lugar); grupos com `flag` preenchido. Qualquer violacao **falha a traducao** apontando grupo e regra, grava o rascunho em `arquivo.zh.REJEITADO.srt` pra inspecao e nao funde o glossario do canal.

#### Instalando o Ollama

```bash
ollama pull qwen2.5:7b-instruct
```

O servidor precisa estar rodando (`ollama serve`, ou o app do Ollama na bandeja). Variaveis: `CLIPFORGE_OLLAMA_URL` (padrao `http://127.0.0.1:11434`), `CLIPFORGE_OLLAMA_MODEL` (padrao `qwen2.5:7b-instruct`). Pra guardar os modelos fora do `C:\Users\<usuario>\.ollama`, defina `OLLAMA_MODELS` (ex.: `D:\Projetos\subtitle-forge\models\ollama`) antes de subir o servidor.

#### Ingles / fallback: NLLB

O modelo NLLB precisa ser convertido pra ctranslate2 **localmente**, uma unica vez (mirrors prontos de terceiros no HuggingFace se mostraram instaveis — um foi removido, outro gerava traducao degenerada por tokenizer incompativel com os pesos). Com o ambiente do SubtitleForge ativado:

```bash
pip install transformers torch
ct2-transformers-converter --model facebook/nllb-200-distilled-600M --output_dir D:\Projetos\subtitle-forge\models\nllb-200-distilled-600M-ct2 --quantization int8 --copy_files sentencepiece.bpe.model
```

Isso baixa o modelo original do Facebook (~2,4GB) e gera a versao ctranslate2 em `D:\Projetos\subtitle-forge\models\nllb-200-distilled-600M-ct2` (caminho fixo, sem acento — sentencepiece nao le corretamente caminhos do Windows com caracteres acentuados, como `C:\Users\<usuario com acento>`). Depois da conversao, `transformers`/`torch` podem ser removidos; so `ctranslate2` e `sentencepiece` sao necessarios em tempo de execucao. Para usar outro caminho, defina `CLIPFORGE_NLLB_MODEL_DIR`.

No caminho NLLB a traducao agrupa os cards do mesmo segmento do Whisper e usa um glossario heuristico (nome capitalizado com frequencia >= 2, genero por artigo/concordancia) com pos-processamento de nome/pronome — bem mais fraco que o caminho LLM.

### Queima de legenda no video (hardsub)

Apos a transcricao de um video terminar, o SubtitleForge oferece 3 botoes pra gerar um arquivo de video final com a legenda queimada (hardsub): **"So chines"**, **"Chines + ingles"** e **"Chines + [idioma original]"** — as duas ultimas empilham 2 legendas no video (chines em cima), gerando a traducao que faltar automaticamente se ainda nao existir. O preset **"Formato"** (Shorts/Video longo) na configuracao ajusta o tamanho de fonte e a segmentacao padrao (`maxWords`) pro tipo de video. O arquivo final sai como `video.hardsub.<modo>.mp4` ao lado do original.

Requisito: `ffmpeg`/`ffprobe` precisam estar instalados e acessiveis no PATH (ou em `C:\ffmpeg\bin`) — nao ha download automatico como o modelo Whisper/NLLB.

## Stack

- **Desktop:** Electron
- **Frontend:** React, TypeScript e Vite
- **Estilo:** Tailwind CSS
- **Estado:** Zustand
- **Icones:** Lucide React
- **Testes:** Vitest
- **Workers locais:** Python para transcricao e processamento de video

## Arquitetura

```text
Renderer React  <->  Electron main/preload  <->  Python workers
```

- **Renderer** (`src/`): UI React + Tailwind, estado via Zustand.
- **Main process** (`electron/`): IPC handlers, dialogs, janela e orquestracao de workers.
- **Workers Python** (`python/`): pipelines de legenda e corte.

## Pre-requisitos

- Node.js 22+
- npm 10+
- Python 3.10+
- FFmpeg e FFprobe disponiveis no sistema
- GPU NVIDIA com CUDA e opcional, mas recomendada para transcricao com Whisper

## Configuracao

```bash
cp .env.example .env
```

Variaveis opcionais:

- `CLIPFORGE_SUBTITLE_FORGE_PATH`: caminho do ambiente Python usado pelo SubtitleForge.
- `CLIPFORGE_NLLB_MODEL_DIR`: caminho do modelo NLLB ja convertido pra ctranslate2 (ver secao "Traducao de legendas" acima). Padrao: `D:\Projetos\subtitle-forge\models\nllb-200-distilled-600M-ct2`.
- `CLIPFORGE_OLLAMA_URL` / `CLIPFORGE_OLLAMA_MODEL`: servidor e modelo do LLM local usado na traducao pro chines. Padrao: `http://127.0.0.1:11434` / `qwen2.5:7b-instruct`.
- `CLIPFORGE_TRANSLATION_ENGINE`: `auto` (padrao, LLM pro chines), `nllb` (forca o NLLB tambem pro chines).
- `CLIPFORGE_CLIP_SPLITTER_PATH`: caminho do projeto externo usado pelo Pre-Editor.
- `CLIPFORGE_TEMP`: pasta temporaria curta usada pelo Pre-Editor (ex.: `D:\cs_tmp`). Evita [WinError 206] quando o input/output esta em caminho profundo. Se nao definido, o app tenta `<drive>:\cs_tmp` e cai para a pasta do video como fallback.
- `GEMINI_API_KEY`: opcional para recursos de IA do Pre-Editor externo, quando habilitados.

## Instalacao

```bash
npm install
```

## Desenvolvimento

```bash
npm run electron:dev
```

Esse comando inicia o Vite, compila o processo principal do Electron em modo watch e abre o aplicativo desktop.

## Scripts

| Comando | Descricao |
| --- | --- |
| `npm run dev` | Inicia apenas o renderer com Vite. |
| `npm run electron:dev` | Inicia o app completo em modo desenvolvimento. |
| `npm run build` | Compila renderer e processo principal. |
| `npm run electron:build` | Gera build do app Electron. |
| `npm test` | Executa a suite de testes com Vitest. |
| `npm run test:watch` | Executa os testes em modo watch. |

## Estrutura

```text
clip-forge/
├─ electron/             # Processo principal, preload e handlers IPC
│  ├─ ipc/               # Handlers IPC (clipSplitter, subtitle)
│  └─ clipFeedbackStore.ts
├─ python/               # Workers locais (faster-whisper, FFmpeg)
├─ resources/            # Icones do aplicativo
├─ scripts/              # Scripts utilitarios
├─ src/
│  ├─ components/
│  │  ├─ clipSplitter/
│  │  ├─ layout/
│  │  ├─ subtitle/
│  │  └─ ui/
│  ├─ hooks/             # Hooks que conectam UI ao Electron
│  ├─ pages/             # Telas das ferramentas de edicao
│  ├─ store/             # Estado global Zustand
│  └─ types/             # Contratos TypeScript compartilhados
└─ docs/                 # Documentacao tecnica e referencias legadas
```

## Modulos legados

Modulos fora do escopo atual foram removidos do shell ativo. Veja [docs/legacy_modules.md](docs/legacy_modules.md) para referencia historica.

## Seguranca

Reporte vulnerabilidades conforme [SECURITY.md](SECURITY.md).

## Licenca

[MIT](LICENSE) © 2026 Joao Pedro Costa e Silva
