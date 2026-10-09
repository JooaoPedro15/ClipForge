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

<p align="center">
  <img src="docs/screenshots/legendas-shorts.png" alt="Tela de Legendas do ClipForge: fila de transcricao no centro e Inspetor com a previa da legenda em 9:16" width="100%" />
</p>

---

## Sobre

O **ClipForge** e um app desktop feito com Electron, React e TypeScript para centralizar ferramentas locais de edicao usadas no workflow de criadores.

O escopo atual e simples: preparar material bruto com rapidez, gerar legendas e apoiar futuras ferramentas de edicao. Modulos comerciais e de inteligencia de parcerias foram separados do ClipForge.

## Funcionalidades

| Modulo | Status | O que faz |
| --- | --- | --- |
| **Legendas** (SubtitleForge) | Estavel | Transcreve audio/video com Whisper e gera arquivos `.srt`. |
| **Pre-edicao** (Pre-Editor) | Em evolucao | Pre-edita videos brutos, comprime pausas e gera uma versao longa mais rapida de revisar. |
| **Cortes** | Em construcao (linha de comando) | Corta o react gravado em clipes 9:16 e gera o XML pro Premiere no layout de um molde seu. |

## Interface

A interface segue o desenho de um editor de video: barra de titulo com o estado da fila de GPU, trilho de ferramentas a esquerda, fila no centro e um **Inspetor** fixo a direita, com as opcoes em secoes recolhiveis (secao fechada mostra o resumo dos valores atuais). Paineis grafite, preto puro so no monitor e o amarelo de legenda reservado pro que esta acontecendo agora: progresso, item ativo, agulha da previa.

| Legendas | Pre-edicao |
| --- | --- |
| ![Fila de legendas com um video transcrevendo, um na fila e um pronto com os botoes de queima](docs/screenshots/legendas.png) | ![Pre-edicao com o video bruto escolhido, fila e o diagrama de pausas no Inspetor](docs/screenshots/pre-edicao.png) |

<img align="right" src="docs/screenshots/monitor.png" alt="Monitor de previa da legenda em 9:16 com barra de transporte" width="260" />

- **Monitor de previa (Legendas):** mostra uma frase de exemplo como ela vai sair, no formato escolhido (9:16 ou 16:9), na posicao da queima e com as opcoes de texto aplicadas: maiusculas/minusculas, acentos, pontuacao, palavras por legenda e caracteres por linha. A formatacao espelha o `render_srt` do Python (`src/lib/captionPreview.ts`, com testes). Troca de legenda como no video e tem pausa.
- **Diagrama de pausas (Pre-edicao):** o mesmo trecho de exemplo antes e depois, com os limites reais de cada tipo de pausa (`PREEDIT_MODE_SETTINGS`) pra intensidade escolhida: Leve, Equilibrada ou Forte (`src/lib/pausePreview.ts`).
- **Duas entradas em Legendas:** **Legendar** (bruto ou audio, sai o `.srt` pra editar) e **Versao em chines** (video pronto, sai traduzido e queimado). O que acontece com o arquivo depende de onde ele foi solto, nao de uma opcao lembrada que poderia queimar um video sem querer. O pedido vai junto da tarefa pro processo principal do Electron, que enfileira a queima quando a transcricao termina (`autoBurn`, ver `electron/ipc/autoBurn.flow.test.ts`).
- **Fila:** uma linha por arquivo, com anel de progresso, o que esta rodando e o que saiu. Video da versao em chines mostra a etapa (1/2 Transcricao, 2/2 Traducao e queima) e so fica pronto quando o video em chines sai. Legenda pronta de Legendar mostra os botoes de queima; pre-edicao pronta mostra quanto o bruto encolheu. A barra de titulo conta a queima como GPU ocupada.
- **Aviso quando termina:** com a janela em segundo plano, legenda, queima ou pre-edicao que termina (ou falha) gera um aviso do Windows, e clicar nele traz o app pra frente. O icone tambem pisca na barra de tarefas ate voce voltar, o que funciona mesmo com o **Nao incomodar** do Windows ligado (ele bloqueia o aviso, nao o piscar). Cancelamento nao avisa.
- **Lembra as escolhas:** a ferramenta aberta e as opcoes do Inspetor voltam como estavam na proxima abertura (`localStorage`, chave `clipforge:preferencias`). Caminhos de saida nao sao lembrados, porque valem pra um video so. Opcao nova numa versao futura nasce com o valor padrao e dado corrompido e ignorado (`src/store/preferences.ts`).

<br clear="right" />

### Capturas de tela

As imagens deste README saem do proprio app em **modo demonstracao** (fila de exemplo, sem GPU nem video):

```bash
npm run screenshots
```

O script (`scripts/capture-screenshots.mjs`) sobe o Vite, abre o app com `?demo` numa janela escondida do Electron e salva PNG em 2x em `docs/screenshots/`. Pra ver a demo no navegador: `npm run dev` e abra `http://localhost:5173/?demo` (`?demo=clip-splitter` abre na Pre-edicao). O modo demo so existe em dev; o build de producao nao inclui nada dele.

Pra um video curto (LinkedIn, portfolio):

```bash
npm run video
```

Grava ~30s em 1920x1080 (MP4 H.264) com um roteiro de cliques: formato Shorts, maiusculas, sem pontuacao, menos palavras por legenda, depois a intensidade da pre-edicao. A janela e offscreen (nao aparece na tela) e cada quadro vai direto pro ffmpeg, que precisa estar instalado. Sai em `docs/media/clipforge-demo.mp4`, fora do git como todo `.mp4` do projeto.

### Traducao de legendas (SubtitleForge)

**Fluxo recomendado:** com o video pronto (ja editado), solte ele na entrada **Versao em chines**. O app transcreve, traduz e queima sozinho, sem clique no meio, e avisa quando o `video.hardsub.zh.mp4` sai ao lado do original. A entrada **Legendar** e pra quando o video ainda esta em edicao: so gera o `.srt` pra trabalhar no Premiere. Num video que entrou por Legendar, o painel **Queimar no video** do item pronto faz a versao em chines com um clique e tambem tem as combinacoes **"Chines + ingles"** e **"Chines + [idioma original]"** — a queima traduz sozinha o que faltar. As chaves **"Gerar .en.srt junto"** / **"Gerar .zh.srt junto"** (secao **Traducao** do Inspetor) sao opcionais: servem so pra ter o `arquivo.en.srt` / `arquivo.zh.srt` pronto logo na transcricao (ex.: pra revisar ou corrigir a mao antes de queimar).

A queima so reaproveita um `.zh.srt` existente se ele for **mais novo que o `cards.json`** da transcricao — traducao de uma transcricao anterior e gerada de novo, e correcao manual feita no `.zh.srt` depois da traducao e respeitada. Pra pedir uma traducao nova mesmo assim, use o botao **"Traduzir de novo"** no painel de queima: ele ignora o `.zh.srt` atual e gera outro **sem queimar**, pra dar pra revisar antes de clicar em "So chines". Se a validacao reprovar a traducao nova, o `.zh.srt` anterior continua intacto. Se a traducao falhar, a tarefa mostra um aviso em destaque com o motivo (a validacao nomeia grupo e regra). Os arquivos temporarios da queima (`.burn-N.ass`) sao apagados no fim.

Arquivos que aparecem ao lado do video: `.srt` (legenda original), `.cards.json` (tempos e confianca do Whisper, usado pela traducao), `.zh.srt` / `.en.srt` (traducoes), `.zh.REJEITADO.srt` (rascunho de traducao reprovada na validacao, so pra inspecao) e `.hardsub.<modo>.mp4` (video final).

- **Chines** usa um **LLM local via Ollama** (padrao `qwen2.5:14b-instruct`, custo zero, offline). Numa placa de 8GB o 14B roda parte na GPU e parte na RAM: um corte de ~40s leva ~7 min pra traduzir e o PC fica pesado nesse tempo. O `qwen2.5:7b-instruct` e ~2x mais rapido mas erra bem mais (troca personagem, inverte sentido) — use so se precisar de velocidade, com `CLIPFORGE_OLLAMA_MODEL=qwen2.5:7b-instruct`. Sem o Ollama rodando, a traducao pro chines falha com erro claro — nao cai em silencio no NLLB.
- **Ingles** usa o modelo NLLB (ctranslate2), que tambem pode ser forcado pro chines com `CLIPFORGE_TRANSLATION_ENGINE=nllb` (qualidade bem menor).

#### Chines: pipeline em dois estagios (LLM local)

Os cards de exibicao de um video vertical sao cortados a cada 2-3 palavras; traduzir card a card gera fragmento de frase, ordem de palavras do portugues e genero chutado. Por isso a traducao pro chines roda em dois estagios, ambos com a **transcricao inteira** (`arquivo.cards.json`, gravado pela transcricao com `segment_id` e `avg_logprob` de cada card):

1. **Glossario do video** (`glossary_service.build_video_glossary_llm`): o modelo recebe a transcricao inteira, o glossario do canal (travado) e o campo **"Tipo de video"** (secao Traducao do Inspetor; ex.: `gameplay de terror`, `corte engracado`, `reacao`), e devolve resumo da historia, personagens com genero/relacao/grafia chinesa fixa, termos recorrentes, registro adequado e os indices de cards ilegiveis.
2. **Traducao por frase** (`llm_translation.translate_with_llm`): o modelo recebe a transcricao inteira + o glossario e devolve **um objeto por frase**, agrupando cards consecutivos: `{"cards": [7, 8, 9], "start": 7.4, "end": 9.8, "zh": "...", "flag": ""}`. O `.zh.srt` final e montado a partir desses grupos, nao dos cards. Cards com `avg_logprob < -0.6` (Whisper inseguro) vao marcados como `low_confidence` pro modelo nao inventar texto no buraco.

As fronteiras de frase sao decididas pelo **Python**, nao pelo modelo (`llm_translation.propose_sentences`): ponto fecha sempre, virgula fecha a partir de 5 palavras, nunca corta antes de preposicao/conectivo nem num card terminado em palavra pendente, e frase com menos de 1,2s funde com a vizinha. O modelo traduz **uma frase por chamada**, vendo a transcricao inteira e as linhas ja traduzidas — deixa-lo agrupar e traduzir tudo de uma vez fazia o modelo de 7B resumir o video numa linha so ou deslocar o conteudo entre as frases.

Chamadas usam `temperature: 0` e saida JSON forcada. Resposta rejeitada (id errado, vazia, letra latina, longa demais, mesmo conectivo de abertura da linha anterior) volta pro modelo com o motivo e um pouco de temperatura (0 / 0,4 / 0,7) — com 0 ele repetiria a mesma resposta. Linha que passa de 20 caracteres e dividida em quantas legendas forem precisas, sempre na pontuacao chinesa, com o tempo repartido em fronteira de card. Pontuacao latina (`,` `.`) vira a de largura inteira (`，` `。`) e aspas/parenteses caem.

**Glossario persistente do canal** em `D:\Projetos\subtitle-forge\glossario_canal.json` (ver `DEFAULT_CHANNEL_GLOSSARY_PATH` em `python/glossary_service.py`): nome do canal, bordoes, personagens e jogos recorrentes. Entra no estagio 1 como **travado** — grafia que ja existe nunca e reescrita — e no fim do video as entradas novas sao fundidas nele (so as que vieram com grafia em chines; uma vazia travaria o nome sem traducao pra sempre). E um JSON simples, pode ser editado a mao pra corrigir uma grafia.

O campo **"Tipo de video"** tambem e repassado pela queima (hardsub), pra legenda gerada na hora da queima sair no mesmo registro da gerada na transcricao.

**Conferencia de sentido (pra quem nao le chines):** cada linha que passa nas regras e traduzida de volta pro portugues **as cegas** — o modelo ve so o chines, nao a fala original, senao "corrigiria" a retraducao e o erro sumiria. Se a fala tem negacao ("nao", "faltou", "nem"...) e a retraducao nao tem (ou o contrario), o sentido foi invertido e a linha volta pro modelo. Se continuar errada depois das tentativas, ela **nao reprova o video**: vai marcada pra revisao. A retraducao e a suspeita ficam em `arquivo.zh.review.json`, ao lado do `.zh.srt` (base da tela de revisao). Custo: ~2 chamadas a mais por frase. `CLIPFORGE_MEANING_CHECK=0` desliga. (Um "juiz" LLM comparando as frases foi testado e descartado: no 14B local errou 3 em 10 e levava ~40s por linha.)

**Validacao antes de gravar** (`subtitle_validation.py`, sem chamar API): todo card em exatamente um grupo e em ordem; nenhum caractere latino nem pontuacao latina na linha traduzida; no maximo 20 caracteres chineses por linha (video vertical); nenhum grupo com menos de 1,2s na tela; 她 com sujeito masculino / 他 com feminino; 嫁给 com sujeito masculino / 娶 com feminino, e 嫁给/娶 entre duas pessoas do mesmo genero (pede 和…结婚); nome com grafia divergente da canonica (variantes do glossario, canonico + sufixo tipo 埃德加尔, ultimo caractere trocado tipo 伯纳德/伯纳多); personagem trocado (a fonte cita um nome, a traducao usa outro no lugar); grupos com `flag` preenchido. Qualquer violacao **falha a traducao** apontando grupo e regra, grava o rascunho em `arquivo.zh.REJEITADO.srt` pra inspecao e nao funde o glossario do canal.

#### Instalando o Ollama

```bash
ollama pull qwen2.5:14b-instruct
```

Se o servidor local nao estiver rodando, o app sobe `ollama serve` sozinho em segundo plano (procura o executavel em `CLIPFORGE_OLLAMA_EXE`, no PATH, em `D:\Ollama\app` e na pasta padrao do instalador). Variaveis: `CLIPFORGE_OLLAMA_URL` (padrao `http://127.0.0.1:11434`), `CLIPFORGE_OLLAMA_MODEL` (padrao `qwen2.5:14b-instruct`). Pra guardar os modelos fora do `C:\Users\<usuario>\.ollama`, defina `OLLAMA_MODELS` (ex.: `D:\Projetos\subtitle-forge\models\ollama`) antes de subir o servidor.

#### Ingles / fallback: NLLB

O modelo NLLB precisa ser convertido pra ctranslate2 **localmente**, uma unica vez (mirrors prontos de terceiros no HuggingFace se mostraram instaveis — um foi removido, outro gerava traducao degenerada por tokenizer incompativel com os pesos). Com o ambiente do SubtitleForge ativado:

```bash
pip install transformers torch
ct2-transformers-converter --model facebook/nllb-200-distilled-600M --output_dir D:\Projetos\subtitle-forge\models\nllb-200-distilled-600M-ct2 --quantization int8 --copy_files sentencepiece.bpe.model
```

Isso baixa o modelo original do Facebook (~2,4GB) e gera a versao ctranslate2 em `D:\Projetos\subtitle-forge\models\nllb-200-distilled-600M-ct2` (caminho fixo, sem acento — sentencepiece nao le corretamente caminhos do Windows com caracteres acentuados, como `C:\Users\<usuario com acento>`). Depois da conversao, `transformers`/`torch` podem ser removidos; so `ctranslate2` e `sentencepiece` sao necessarios em tempo de execucao. Para usar outro caminho, defina `CLIPFORGE_NLLB_MODEL_DIR`.

No caminho NLLB a traducao agrupa os cards do mesmo segmento do Whisper e usa um glossario heuristico (nome capitalizado com frequencia >= 2, genero por artigo/concordancia) com pos-processamento de nome/pronome — bem mais fraco que o caminho LLM.

### Aprender o seu estilo de legenda (SubtitleForge)

O app aprende onde voce quebra as legendas e como ajusta entrada/saida, a partir dos videos que voce corrige no Premiere:

1. Gere a legenda no app (ela salva tambem `video.words.json`, com o tempo de cada palavra).
2. Corrija no Premiere e exporte o `.srt` corrigido e o video final (com os cortes).
3. Na secao **Meu estilo** do Inspetor, escolha video original, SRT corrigido e video final e clique **Ensinar**.

A comparacao e pelo texto (cortes de silencio nao atrapalham). Uma arvore de decisao (scikit-learn) aprende as quebras e medianas aprendem os tempos, com um perfil para vertical e outro para horizontal. Com 3+ videos ensinados no formato, a chave **Usar meu estilo** passa a segmentar novas legendas assim. Biblioteca em `%APPDATA%/<app>/subtitle-style` (cada video pode ser removido e o perfil e retreinado).

### Queima de legenda no video (hardsub)

Pela entrada **Versao em chines** a queima "So chines" comeca sozinha quando a transcricao termina. Pela entrada **Legendar**, apos a transcricao terminar, o SubtitleForge oferece 3 botoes pra gerar um arquivo de video final com a legenda queimada (hardsub): **"So chines"**, **"Chines + ingles"** e **"Chines + [idioma original]"** — as duas ultimas empilham 2 legendas no video (chines em cima), gerando a traducao que faltar automaticamente se ainda nao existir. O seletor **Formato** (Shorts 9:16 / Video longo 16:9), embaixo do monitor de previa, ajusta o tamanho de fonte e a segmentacao padrao (`maxWords`) pro tipo de video. O arquivo final sai como `video.hardsub.<modo>.mp4` ao lado do original.

Requisito: `ffmpeg`/`ffprobe` precisam estar instalados e acessiveis no PATH (ou em `C:\ffmpeg\bin`) — nao ha download automatico como o modelo Whisper/NLLB.

### Cortes para TikTok (linha de comando)

Gera um **XML do Premiere** (Final Cut Pro XML) com os clipes do react numa sequencia so, um depois do outro, com um espaco entre eles e um marcador em cada um. O layout vem de um **molde**: uma sequencia sua ja montada, exportada em *Arquivo > Exportar > Final Cut Pro XML*. Do primeiro clipe do molde o modulo copia filme (V1), webcam (V2, inclusive o Lumetri), loop do link (V3, sequencia aninhada) e as faixas de audio com o volume, e repete pra cada clipe novo trocando so os tempos e o caminho do bruto. No projeto do react, *Arquivo > Importar* o XML: a sequencia aponta pro bruto inteiro, entao da pra esticar clipe, mover tela e mexer no volume normalmente.

```bash
npm run cortes -- xml --template molde.xml --source "E:\Bruto\react.mp4" --ranges "2:24.44-3:39.72,3:39.72-5:28.56"
```

Pra o app achar as cenas sozinho, primeiro analise o bruto (o trecho e opcional):

```bash
npm run cortes -- analyze "E:\Bruto\react.mp4" --start 2:24.44 --end 1:58:00
npm run cortes -- xml --template molde.xml --analysis "E:\Bruto\react.cortes.json"
```

O `analyze` le o bruto uma vez so (metade esquerda = filme, faixa 1 = filme, faixa 2 = mic; mude com `--film-track`/`--mic-track`), transcreve as duas faixas com o Whisper, marca como ponto de corte possivel os momentos em que ninguem fala (de preferencia num corte de plano) e escolhe as fronteiras por programacao dinamica com cada clipe entre `--min` e `--max` (padrao 70 e 240s, alvo 150s). Tudo vai pro `react.cortes.json` ao lado do bruto. No `xml`, `--clips 1,3,5` ou `--top 5` escolhem quais clipes entram.

Com `--judge qwen2.5:14b-instruct` (ou `qwen2.5:7b-instruct`, ~2x mais rapido e menos preciso), um **juiz** no LLM local le a transcricao em janelas de 10 min com os pontos possiveis marcados (`[C12]`) e da nota de 0 a 10 pra "aqui termina uma cena?". A nota final de cada ponto e 40% regra + 60% juiz; a programacao dinamica continua garantindo as duracoes, entao o modelo nunca cria clipe curto ou longo demais. Sem o Ollama (ou sem o modelo baixado), a analise segue so com as regras e registra um aviso.

Pra medir os cortes contra uma sequencia que voce montou a mao no mesmo bruto (gabarito):

```bash
npm run cortes -- evaluate --reference sequencia.xml --analysis "E:\Bruto\react.cortes.json" --from 2:24.44 --to 12:54
```

Conta como acerto o corte do app que cai a ate `--tolerance` segundos (padrao 10) de um corte seu e mostra precisao, revocacao e F1.

Com o LLM ligado, cada clipe ganha um **titulo** curto (vira o nome do marcador, `03 - titulo`) e uma **nota** de 0 a 10: 70% gancho (o LLM le a transcricao do clipe) + 30% reacao (quanto voce fala no mic, comparado com o resto do react). `xml --top 5` usa essa nota. Pra trocar a duracao dos clipes sem reler o bruto nem chamar o juiz de novo:

```bash
npm run cortes -- resegment "E:\Bruto\react.cortes.json" --min 60 --target 120 --max 200 --judge qwen2.5:14b-instruct
```

Clipe com a mesma fronteira de antes mantem titulo e nota; so os que mudaram passam pelo LLM.

O XML sai como `<bruto>.cortes.xml` (ou em `--out`). O `npm run cortes` roda `python/cortes_service.py` com o mesmo Python e as mesmas DLLs CUDA do app. O codigo fica em `python/cortes/` e nao depende do Electron.

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
- **Main process** (`electron/`): IPC handlers, dialogs, janela e orquestracao de workers. Tudo que usa GPU (transcricao, queima e Pre-Editor) passa por uma fila unica (`electron/python/gpuQueue.ts`): um job por vez, pra nao disputar VRAM.
- **Workers Python** (`python/`): pipelines de legenda e corte.

## Pre-requisitos

- Node.js 22+
- npm 10+
- Python 3.10+
- FFmpeg e FFprobe disponiveis no sistema
- GPU NVIDIA com CUDA e opcional, mas recomendada para transcricao com Whisper

## Configuracao

Tudo tem padrao e funciona sem configurar nada. Pra mudar, defina **variaveis de ambiente do sistema** (o app nao le arquivo `.env`) e reabra o terminal/app depois. Exemplo no Windows:

```bash
setx CLIPFORGE_OLLAMA_MODEL qwen2.5:7b-instruct
```

Variaveis opcionais:

- `CLIPFORGE_SUBTITLE_FORGE_PATH`: caminho do ambiente Python usado pelo SubtitleForge.
- `CLIPFORGE_NLLB_MODEL_DIR`: caminho do modelo NLLB ja convertido pra ctranslate2 (ver secao "Traducao de legendas" acima). Padrao: `D:\Projetos\subtitle-forge\models\nllb-200-distilled-600M-ct2`.
- `CLIPFORGE_OLLAMA_URL` / `CLIPFORGE_OLLAMA_MODEL`: servidor e modelo do LLM local usado na traducao pro chines. Padrao: `http://127.0.0.1:11434` / `qwen2.5:14b-instruct`.
- `CLIPFORGE_TRANSLATION_ENGINE`: `auto` (padrao, LLM pro chines), `nllb` (forca o NLLB tambem pro chines).
- `CLIPFORGE_CLIP_SPLITTER_PATH`: caminho do projeto externo usado pelo Pre-Editor.
- `CLIPFORGE_TEMP`: pasta temporaria curta usada pelo Pre-Editor (ex.: `D:\cs_tmp`). Evita [WinError 206] quando o input/output esta em caminho profundo. Se nao definido, o app tenta `<drive>:\cs_tmp` e cai para a pasta do video como fallback.

## Instalacao

```bash
npm install
```

Dependencias Python (no venv usado pelo app, por padrao `D:\Projetos\subtitle-forge\.venv`):

```bash
D:\Projetos\subtitle-forge\.venv\Scripts\python.exe -m pip install -r python/requirements.txt
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
| `npm run test:py` | Executa os testes Python (`python/*_test.py`) com o Python do app. `npm run test:py -- srt` roda so `srt*_test.py`. |
| `npm run test:all` | Vitest + testes Python. |
| `npm run cortes -- <subcomando>` | Roda o modulo de cortes pela linha de comando (ver "Cortes para TikTok"). |
| `npm run screenshots` | Gera as imagens do README em `docs/screenshots/` (modo demonstracao). |
| `npm run video` | Grava o video de demonstracao em `docs/media/clipforge-demo.mp4` (precisa do ffmpeg). |

## Estrutura

```text
clip-forge/
├─ electron/             # Processo principal, preload e handlers IPC
│  ├─ ipc/               # Handlers IPC (subtitle, subtitleBurn, clipSplitter)
│  ├─ python/            # Runner Python, leitura de eventos e fila unica de GPU
│  └─ testing/           # Processo falso e utilitarios dos testes de IPC
├─ python/               # Workers locais (faster-whisper, FFmpeg) + modulos puros
│  ├─ events.py          # Protocolo de eventos JSON com o Electron
│  ├─ text_utils.py      # Helpers de texto (limpeza, timestamps, quebra de linha)
│  ├─ segmentation.py    # Palavras do Whisper -> legendas (cards)
│  ├─ style_*.py         # Aprendizado do estilo (alinhamento, features, arvore, biblioteca, servico)
│  ├─ cortes/            # Cortes: molde do Premiere, XML, analise do bruto (sem Electron)
│  ├─ cortes_service.py  # CLI do modulo de cortes (npm run cortes)
│  └─ requirements.txt   # Dependencias Python fixadas
├─ resources/            # Icones do aplicativo
├─ scripts/              # Scripts utilitarios (inclui a captura das telas do README)
├─ src/
│  ├─ components/
│  │  ├─ clipSplitter/   # Pre-edicao: video bruto, diagrama de pausas, fila
│  │  ├─ inspector/      # Secoes recolhiveis e campos do Inspetor
│  │  ├─ layout/         # Barra de titulo, trilho de ferramentas e area de trabalho
│  │  ├─ subtitle/       # Legendas: monitor de previa, fila, queima, meu estilo
│  │  └─ ui/             # Botao, select, stepper, controle segmentado, status
│  ├─ demo/              # Modo demonstracao (so em dev, ?demo)
│  ├─ hooks/             # Hooks que conectam UI ao Electron
│  ├─ lib/               # Logica pura com testes (previa da legenda, pausas, fila)
│  ├─ pages/             # Telas das ferramentas de edicao
│  ├─ store/             # Estado global Zustand
│  └─ types/             # Contratos TypeScript compartilhados
└─ docs/                 # Documentacao tecnica, referencias legadas e screenshots/
```

## Modulos legados

Modulos fora do escopo atual foram removidos do shell ativo. Veja [docs/legacy_modules.md](docs/legacy_modules.md) para referencia historica.

## Seguranca

Reporte vulnerabilidades conforme [SECURITY.md](SECURITY.md).

## Licenca

[MIT](LICENSE) © 2026 Joao Pedro Costa e Silva
