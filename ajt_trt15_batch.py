import json
import os
import sys
import time
from datetime import datetime, timezone

from app import app, send_trt15_secretariat_email

BATCHES = {
    "QUARTA_30_09": [
        "Araraquara",
        "São José do Rio Preto",
        "Campinas",
    ],
    "QUINTA_01_10": [
        "Piracicaba",
        "Jundiaí",
        "Bauru",
    ],
    "SEXTA_02_10": [
        "São José dos Campos",
        "Sorocaba",
        "Presidente Prudente",
    ],
}


def run_batch(batch_key):
    batch_key = batch_key.strip().upper()
    secretariats = BATCHES.get(batch_key)
    if not secretariats:
        raise RuntimeError(f"Lote TRT-15 inválido: {batch_key}")

    os.environ["AJT_TRT15_DAILY_LIMIT"] = "3"
    delay = max(30, int(os.environ.get("AJT_BATCH_DELAY_SECONDS", "90")))

    summary = {
        "batch": batch_key,
        "sent": 0,
        "skipped": 0,
        "errors": [],
        "started_at": datetime.now(timezone.utc).isoformat(),
    }

    with app.app_context():
        for index, secretariat in enumerate(secretariats):
            try:
                recipient, total_varas = send_trt15_secretariat_email(secretariat)
                summary["sent"] += 1
                print(json.dumps({
                    "event": "sent",
                    "batch": batch_key,
                    "secretariat": secretariat,
                    "recipient": recipient,
                    "total_varas": total_varas,
                }, ensure_ascii=False), flush=True)
            except Exception as exc:
                message = str(exc)
                if "Já existe envio concluído" in message:
                    summary["skipped"] += 1
                    print(json.dumps({
                        "event": "duplicate_skipped",
                        "batch": batch_key,
                        "secretariat": secretariat,
                        "detail": message,
                    }, ensure_ascii=False), flush=True)
                else:
                    summary["errors"].append({
                        "secretariat": secretariat,
                        "error": message,
                    })
                    print(json.dumps({
                        "event": "error",
                        "batch": batch_key,
                        "secretariat": secretariat,
                        "error": message,
                    }, ensure_ascii=False), flush=True)

            if index < len(secretariats) - 1:
                time.sleep(delay)

    summary["finished_at"] = datetime.now(timezone.utc).isoformat()
    print(json.dumps({"event": "batch_finished", **summary}, ensure_ascii=False), flush=True)
    return summary


def main():
    batch_key = sys.argv[1] if len(sys.argv) > 1 else "QUARTA_30_09"
    run_batch(batch_key)


if __name__ == "__main__":
    main()
