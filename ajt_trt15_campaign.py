import json
import os
import time

from app import AjtSendLog, app, db, send_trt15_secretariat_email

TRT15_GROUPS = {
    "WED": [
        "Araraquara",
        "São José do Rio Preto",
        "Campinas",
    ],
    "THU": [
        "Piracicaba",
        "Jundiaí",
        "Bauru",
    ],
    "FRI": [
        "São José dos Campos",
        "Sorocaba",
        "Presidente Prudente",
    ],
}


def already_sent(secretariat):
    return AjtSendLog.query.filter_by(
        tribunal="TRT-15",
        secretariat=secretariat,
        result="sent",
    ).first() is not None


def run_group(group_key):
    key = group_key.strip().upper()
    secretariats = TRT15_GROUPS.get(key)
    if not secretariats:
        raise RuntimeError(f"Grupo TRT-15 inválido: {key}")

    delay = max(30, int(os.environ.get("AJT_TRT15_BATCH_DELAY_SECONDS", "180")))
    summary = {"group": key, "sent": 0, "skipped": 0, "errors": []}

    for idx, secretariat in enumerate(secretariats):
        if already_sent(secretariat):
            summary["skipped"] += 1
            print(json.dumps({
                "event": "duplicate_skipped",
                "group": key,
                "secretariat": secretariat,
            }, ensure_ascii=False), flush=True)
            continue

        try:
            recipient, total_varas = send_trt15_secretariat_email(secretariat)
            summary["sent"] += 1
            print(json.dumps({
                "event": "sent",
                "group": key,
                "secretariat": secretariat,
                "recipient": recipient,
                "total_varas": total_varas,
            }, ensure_ascii=False), flush=True)
        except Exception as exc:
            db.session.rollback()
            summary["errors"].append({
                "secretariat": secretariat,
                "error": str(exc),
            })
            print(json.dumps({
                "event": "error",
                "group": key,
                "secretariat": secretariat,
                "error": str(exc),
            }, ensure_ascii=False), flush=True)

        if idx < len(secretariats) - 1:
            time.sleep(delay)

    print(json.dumps({"event": "group_finished", **summary}, ensure_ascii=False), flush=True)
    return summary


def main():
    group_key = os.environ.get("AJT_TRT15_GROUP", "").strip()
    if not group_key:
        raise RuntimeError("AJT_TRT15_GROUP não informado.")

    with app.app_context():
        run_group(group_key)


if __name__ == "__main__":
    main()
