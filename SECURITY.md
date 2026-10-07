# Security Policy

## Reportando vulnerabilidades

Se você encontrar uma vulnerabilidade neste projeto, **não abra uma issue pública**.

Envie um email para: **jp3447601@gmail.com**

Inclua:

- Descrição do problema
- Passos para reproduzir
- Impacto estimado
- Sugestão de correção (opcional)

Responderei em até **72 horas**.

## Escopo

Estão em escopo:

- Código TypeScript/JavaScript em `src/` e `electron/`
- Scripts Python em `python/`
- Configuração do Electron (contextIsolation, IPC)
- Dependências NPM com vulnerabilidades conhecidas

Estão fora de escopo:

- Engenharia social
- Phishing
- Acesso físico ao dispositivo do usuário

## Práticas adotadas

- **Electron**: `contextIsolation: true`, `nodeIntegration: false`, preload com whitelist de IPC
- **Secrets**: o app não usa chaves de API hoje; a configuração é por variáveis de ambiente `CLIPFORGE_*` (ver README). `.env` continua no `.gitignore` por precaução
- **Dependências**: `npm audit` rodado periodicamente
- **CSP**: política restritiva no `index.html`
