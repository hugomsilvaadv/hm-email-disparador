import json
import os
from datetime import datetime, timezone

from app import app, send_trt15_secretariat_email
from ajt_trt3 import send_trt3_individual_email


def dispatch_once():
    tribunal = os.environ.get("AJT_TRIBUNAL", "TRT-15").strip().upper()
    secretariat = os.environ.get("AJT_SECRETARIAT", "").strip()
    started_at = datetime.now(timezone.utc)

    if not secretariat:
        result = {
            "ok": False,
            "tribunal": tribunal,
            "error": "AJT_SECRETARIAT não informado.",
            "started_at": started_at.isoformat(),
            "finished_at": datetime.now(timezone.utc).isoformat(),
        }
        print(json.dumps(result, ensure_ascii=False), flush=True)
        return result

    with app.app_context():
        try:
            provider_id = ""
            if tribunal == "TRT-15":
                recipient, total_varas = send_trt15_secretariat_email(secretariat)
            elif tribunal == "TRT-3":
                recipient, total_varas, provider_id = send_trt3_individual_email(secretariat)
            else:
                raise RuntimeError(f"Tribunal ainda não suportado pelo executor: {tribunal}")

            result = {
                "ok": True,
                "tribunal": tribunal,
                "secretariat": secretariat,
                "recipient": recipient,
                "total_varas": total_varas,
                "provider_id": provider_id or None,
                "started_at": started_at.isoformat(),
                "finished_at": datetime.now(timezone.utc).isoformat(),
            }
        except Exception as exc:
            result = {
                "ok": False,
                "tribunal": tribunal,
                "secretariat": secretariat,
                "error": str(exc),
                "started_at": started_at.isoformat(),
                "finished_at": datetime.now(timezone.utc).isoformat(),
            }

    print(json.dumps(result, ensure_ascii=False), flush=True)
    return result


if __name__ == "__main__":
    dispatch_once()
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "5000")),
        debug=False,
    )
