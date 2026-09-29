import json
import os
import re
from urllib import request as urllib_request, error as urllib_error

from app import app, AjtSendLog

API_KEY = os.environ.get("RESEND_API_KEY", "").strip()

def get_email(email_id):
    req = urllib_request.Request(
        f"https://api.resend.com/emails/{email_id}",
        headers={
            "Authorization": f"Bearer {API_KEY}",
            "User-Agent": "HM-Resend-Audit/1.0",
        },
        method="GET",
    )
    try:
        with urllib_request.urlopen(req, timeout=20) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return json.loads(raw) if raw else {}
    except urllib_error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        return {"_http_error": exc.code, "_detail": detail[:800]}
    except Exception as exc:
        return {"_error": str(exc)}

def extract_id(detail):
    if not detail:
        return None
    m = re.search(r"Resend ID:\s*([A-Za-z0-9-]+)", detail)
    return m.group(1) if m else None

def main():
    if not API_KEY:
        raise RuntimeError("RESEND_API_KEY ausente")

    with app.app_context():
        rows = (
            AjtSendLog.query
            .filter(AjtSendLog.tribunal == "TRT-3")
            .filter(AjtSendLog.recipient.like("varabh%@trt3.jus.br"))
            .filter(AjtSendLog.result == "sent")
            .order_by(AjtSendLog.sent_at.asc())
            .all()
        )

        latest_by_recipient = {}
        for row in rows:
            latest_by_recipient[row.recipient] = row

        summary = {}
        details = []

        for recipient in sorted(
            latest_by_recipient,
            key=lambda x: int(re.search(r"varabh(\d+)@", x).group(1))
        ):
            row = latest_by_recipient[recipient]
            email_id = extract_id(row.detail)
            if not email_id:
                state = "missing_resend_id"
                info = {}
            else:
                info = get_email(email_id)
                state = (
                    info.get("last_event")
                    or info.get("status")
                    or ("http_error" if "_http_error" in info else None)
                    or ("error" if "_error" in info else None)
                    or "unknown"
                )

            summary[state] = summary.get(state, 0) + 1
            item = {
                "recipient": recipient,
                "resend_id": email_id,
                "state": state,
            }
            for key in ("created_at", "from", "to", "subject"):
                if key in info:
                    item[key] = info.get(key)
            if "_http_error" in info:
                item["http_error"] = info["_http_error"]
                item["detail"] = info.get("_detail")
            if "_error" in info:
                item["error"] = info["_error"]
            details.append(item)
            print(json.dumps({"event":"email_status", **item}, ensure_ascii=False), flush=True)

        print(json.dumps({
            "event":"audit_summary",
            "total": len(details),
            "summary": summary,
        }, ensure_ascii=False), flush=True)

if __name__ == "__main__":
    main()
