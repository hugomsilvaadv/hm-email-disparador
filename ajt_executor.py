import json
import os
from datetime import datetime, timezone

from app import app, send_trt15_secretariat_email


def dispatch_once():
    secretariat = os.environ.get("AJT_SECRETARIAT", "").strip()
    started_at = datetime.now(timezone.utc)

    if not secretariat:
        result = {
            "ok": False,
            "error": "AJT_SECRETARIAT não informado.",
            "started_at": started_at.isoformat(),
            "finished_at": datetime.now(timezone.utc).isoformat(),
        }
        print(json.dumps(result, ensure_ascii=False), flush=True)
        return result

    with app.app_context():
        try:
            recipient, total_varas = send_trt15_secretariat_email(secretariat)
            result = {
                "ok": True,
                "secretariat": secretariat,
                "recipient": recipient,
                "total_varas": total_varas,
                "started_at": started_at.isoformat(),
                "finished_at": datetime.now(timezone.utc).isoformat(),
            }
        except Exception as exc:
            result = {
                "ok": False,
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
