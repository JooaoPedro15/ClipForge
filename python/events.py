"""Protocolo de eventos entre os servicos Python e o Electron.

Cada evento e UMA linha JSON no stdout; o Electron le linha a linha
(parseRunnerEvent em electron/ipc/*.ts). flush=True pra UI receber na hora.
"""

import json
from typing import Any


def emit(event: str, status: str, stage: str, message: str, **extra: Any) -> None:
    payload = {"event": event, "status": status, "stage": stage, "message": message, **extra}
    print(json.dumps(payload, ensure_ascii=False), flush=True)
