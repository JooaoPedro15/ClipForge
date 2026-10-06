# ClipForge - Documentacao Tecnica

Este documento descreve o estado atual do ClipForge apos a limpeza de escopo.

## Visao geral

O ClipForge e um app desktop em `Electron + React + TypeScript` focado em ferramentas de edicao para creators.

Ferramentas ativas:

- `SubtitleForge`: transcricao e geracao de `.srt`.
- `Pre-Editor`: pre-edicao de videos brutos com compressao de pausas e exportacao de uma versao longa revisavel.

Modulos comerciais, prospeccao e recomendacao nao fazem parte do shell ativo. Referencias historicas ficam em `docs/legacy_modules.md`.

## Arquitetura

```text
Renderer React  <->  Preload seguro  <->  Electron main  <->  Python workers
```

### Renderer

Fica em `src/`.

Responsabilidades:

- desenhar a interface;
- coletar acoes do usuario;
- mostrar progresso, erro e sucesso;
- atualizar estado global via Zustand.

### Main process

Fica em `electron/`.

Responsabilidades:

- criar a janela do app;
- abrir dialogos de arquivo e pasta;
- registrar IPC de edicao;
- orquestrar workers Python;
- repassar progresso para a interface.

### Workers Python

Ficam em `python/`.

Responsabilidades:

- transcrever audio/video;
- gerar legenda `.srt`;
- processar videos para cortes;
- emitir progresso em JSON para o Electron.

## Estrutura principal

```text
clip-forge/
|-- electron/
|   |-- ipc/
|   |   |-- clipSplitter.ts
|   |   `-- subtitle.ts
|   |-- clipFeedbackStore.ts
|   |-- main.ts
|   `-- preload.ts
|-- python/
|   |-- clip_splitter_service.py
|   |-- events.py
|   |-- segmentation.py
|   |-- srt_utils.py
|   |-- subtitle_service.py
|   `-- text_utils.py
|-- src/
|   |-- components/
|   |   |-- clipSplitter/
|   |   |-- layout/
|   |   |-- subtitle/
|   |   `-- ui/
|   |-- hooks/
|   |-- pages/
|   |-- store/
|   |-- types/
|   |-- App.tsx
|   |-- index.css
|   `-- main.tsx
|-- package.json
|-- tsconfig.json
|-- tsconfig.electron.json
`-- vite.config.ts
```

## Fluxo SubtitleForge

1. O usuario escolhe ou arrasta um arquivo.
2. `useSubtitleForge` chama `window.clipforge.subtitle.process`.
3. `electron/ipc/subtitle.ts` inicia o worker Python.
4. `python/subtitle_service.py` transcreve (Whisper), `segmentation.py` transforma as palavras em legendas e `srt_utils.render_srt` grava o `.srt`; o progresso sai como eventos JSON (`events.py`).
5. O Electron repassa eventos para o renderer.
6. A store atualiza a lista de tarefas.
7. A UI mostra progresso, erro ou o arquivo `.srt` final.

## Fluxo Pre-Editor

1. O usuario escolhe o video e as opcoes de corte.
2. `useClipSplitter` chama `window.clipforge.clipSplitter.process`.
3. `electron/ipc/clipSplitter.ts` inicia o worker Python.
4. `python/clip_splitter_service.py` adapta o pipeline de corte.
5. O Electron repassa progresso e resultado.
6. A store atualiza tarefas e feedback de clipes.

## API exposta pelo preload

`window.clipforge` expoe apenas namespaces necessarios ao escopo atual:

- `window`: minimizar, maximizar e fechar;
- `dialog`: selecionar arquivos e diretorios;
- `shell`: abrir ou revelar caminhos;
- `subtitle`: processar, cancelar e escutar eventos de legenda;
- `clipSplitter`: processar, cancelar, salvar feedback e escutar eventos de corte.

## Manutencao

- Mantenha novas ferramentas dentro do escopo de edicao.
- Use IPC dedicado por ferramenta.
- Nao habilite `nodeIntegration` no renderer.
- Prefira hooks para isolar integracao UI/backend.
- Atualize este documento quando a arquitetura mudar.
