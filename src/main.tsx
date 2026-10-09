import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

import App from '@/App'

import './index.css'

// Localiza o container raiz onde o React vai montar toda a aplicacao.
const rootElement = document.getElementById('root')

if (!rootElement) {
  throw new Error('Root element #root não encontrado.')
}

const container = rootElement

// Inicia a aplicacao no modo estrito para destacar efeitos colaterais durante o desenvolvimento.
function render() {
  createRoot(container).render(
    <StrictMode>
      <App />
    </StrictMode>,
  )
}

// ?demo so existe em dev: no build de producao o DEV e false e o import some do pacote.
const params = new URLSearchParams(window.location.search)
if (import.meta.env.DEV && params.has('demo')) {
  void import('@/demo/installDemo').then(({ installDemo }) => {
    installDemo(params)
    render()
  })
} else {
  render()
}
