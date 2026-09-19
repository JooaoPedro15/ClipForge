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

O SubtitleForge tem duas opcoes opcionais para traduzir a legenda gerada, alem do `.srt` original: **"Traduzir p/ ingles"** e **"Traduzir p/ chines (simplificado)"**. Ao marcar uma ou ambas, o app gera arquivos adicionais (`arquivo.en.srt`, `arquivo.zh.srt`) ao lado do `.srt` original, usando o modelo NLLB para traducao.

O modelo NLLB precisa ser convertido pra ctranslate2 **localmente**, uma unica vez (mirrors prontos de terceiros no HuggingFace se mostraram instaveis — um foi removido, outro gerava traducao degenerada por tokenizer incompativel com os pesos). Com o ambiente do SubtitleForge ativado:

```bash
pip install transformers torch
ct2-transformers-converter --model facebook/nllb-200-distilled-600M --output_dir D:\Projetos\subtitle-forge\models\nllb-200-distilled-600M-ct2 --quantization int8 --copy_files sentencepiece.bpe.model
```

Isso baixa o modelo original do Facebook (~2,4GB) e gera a versao ctranslate2 em `D:\Projetos\subtitle-forge\models\nllb-200-distilled-600M-ct2` (caminho fixo, sem acento — sentencepiece nao le corretamente caminhos do Windows com caracteres acentuados, como `C:\Users\<usuario com acento>`). Depois da conversao, `transformers`/`torch` podem ser removidos; so `ctranslate2` e `sentencepiece` sao necessarios em tempo de execucao. Para usar outro caminho, defina `CLIPFORGE_NLLB_MODEL_DIR`.

A traducao roda por frase (agrupando os cards do mesmo segmento do Whisper, nao card a card) e mantem um glossario de nomes/genero de personagens persistente entre videos, em `D:\Projetos\subtitle-forge\glossario_canal.json` (caminho fixo, ver `DEFAULT_CHANNEL_GLOSSARY_PATH` em `python/glossary_service.py`). Cada nome novo detectado (frequencia >= 2 no video) e traduzido uma vez e travado nesse arquivo, garantindo que o mesmo personagem saia com a mesma grafia em chines em todos os videos seguintes. E um JSON simples — pode ser aberto e editado manualmente pra corrigir uma grafia errada.

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
