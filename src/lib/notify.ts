import type { Notice } from '@/lib/finishNotices'

// Avisa que uma tarefa terminou quando a janela esta sem foco (com o app na frente, a
// propria fila ja mostra o resultado). Sao dois sinais: o toast do Windows, que o
// "Nao incomodar" pode bloquear, e o icone piscando na barra de tarefas, que nao depende dele.
export function notifyIfAway(notice: Notice | null): void {
  if (!notice || typeof document === 'undefined' || document.hasFocus()) {
    return
  }
  void window.clipforge?.window?.requestAttention()
  if (typeof Notification !== 'undefined') {
    const toast = new Notification(notice.title, { body: notice.body })
    toast.onclick = () => void window.clipforge?.window?.focus()
  }
}
