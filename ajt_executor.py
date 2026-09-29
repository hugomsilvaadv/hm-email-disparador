import json
import os
import sys
from datetime import datetime, timezone

from app import app, send_trt15_secretariat_email


def main():
    secretariat = os.environ.get("AJT_SECRETARIAT", "").strip()

    if not secretariat:
        print(json.dumps({
            "ok": False,
            "error": "AJT_SECRETARIAT não informado.",
        }, ensure_ascii=False))
        return 2

    started_at = datetime.now(timezone.utc)

    with app.app_context():
        try:
            recipient, total_varas = send_trt15_secretariat_email(secretariat)
            print(json.dumps({
                "ok": True,
                "secretariat": secretariat,
                "recipient": recipient,
                "total_varas": total_varas,
                "started_at": started_at.isoformat(),
                "finished_at": datetime.now(timezone.utc).isoformat(),
            }, ensure_ascii=False))
            return 0
        except Exception as exc:
            print(json.dumps({
                "ok": False,
                "secretariat": secretariat,
                "error": str(exc),
                "started_at": started_at.isoformat(),
                "finished_at": datetime.now(timezone.utc).isoformat(),
            }, ensure_ascii=False))
            return 1


if __name__ == "__main__":
    sys.exit(main())
