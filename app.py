import base64
import csv
import html
import hmac
import io
import json
import os
import re
import threading
import time
from datetime import datetime, timezone
from functools import wraps
from urllib import error as urllib_error
from urllib import request as urllib_request

from flask import Flask, flash, redirect, render_template, request, session, url_for
from flask_sqlalchemy import SQLAlchemy

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "change-this-secret-before-production")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["MAX_CONTENT_LENGTH"] = 6 * 1024 * 1024
app.config["SESSION_COOKIE_SECURE"] = True
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

db_url = os.environ.get("DATABASE_URL", "sqlite:///hm_email.db")
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql+psycopg://", 1)
elif db_url.startswith("postgresql://") and "+psycopg" not in db_url:
    db_url = db_url.replace("postgresql://", "postgresql+psycopg://", 1)
app.config["SQLALCHEMY_DATABASE_URI"] = db_url

db = SQLAlchemy(app)

STATUS_OPTIONS = [
    "Não contatado",
    "Enviado",
    "Respondeu",
    "Reunião agendada",
    "Cliente",
    "Sem interesse",
    "Não contatar",
    "Erro",
]

DEFAULT_SUBJECT = "Apoio técnico em cálculos trabalhistas"
DEFAULT_BODY = """Olá, equipe do {office}, tudo bem?

Meu nome é Hugo Mendes e sou responsável pela HM Perícia & Cálculos.

Vi que o escritório atua{profile_hint}. Prestamos apoio técnico terceirizado a advogados e escritórios na elaboração e conferência de cálculos trabalhistas, especialmente em PJe-Calc, liquidação de sentença, atualização de cálculos, conferência da conta da parte contrária e suporte técnico para impugnações.

A proposta é funcionar como uma retaguarda técnica do escritório: quando surgir uma demanda de cálculo, a equipe jurídica pode concentrar o tempo na condução do processo e deixar a etapa quantitativa conosco.

Caso atualmente terceirizem esse tipo de trabalho — ou tenham interesse em conhecer nosso modelo de parceria — posso encaminhar uma apresentação curta com os serviços e valores.

Atenciosamente,
Hugo Mendes
Diretor Técnico | Advogado | Perito Judicial
HM Perícia & Cálculos
WhatsApp: (31) 99587-1227
E-mail: hugo@hmpericia.com.br
hmpericia.com.br

Caso prefira não receber novos contatos da HM, basta nos avisar por este e-mail.
"""


class Lead(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    region = db.Column(db.String(120))
    city = db.Column(db.String(120))
    office = db.Column(db.String(240), nullable=False)
    profile = db.Column(db.String(300))
    email = db.Column(db.String(240), nullable=False, index=True)
    whatsapp = db.Column(db.String(80))
    address = db.Column(db.String(400))
    adherence = db.Column(db.String(40))
    source_url = db.Column(db.String(500))
    status = db.Column(db.String(60), default="Não contatado", index=True)
    last_contact = db.Column(db.DateTime(timezone=True))
    notes = db.Column(db.Text)
    last_error = db.Column(db.Text)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class CampaignAttachment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(255), nullable=False)
    mimetype = db.Column(db.String(120), nullable=False)
    data = db.Column(db.LargeBinary, nullable=False)
    uploaded_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class SendLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    lead_id = db.Column(db.Integer, db.ForeignKey("lead.id"), nullable=False, index=True)
    sent_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)
    recipient = db.Column(db.String(240), nullable=False)
    subject = db.Column(db.String(300), nullable=False)
    result = db.Column(db.String(40), nullable=False)
    detail = db.Column(db.Text)
    lead = db.relationship("Lead")


batch_state = {"running": False, "total": 0, "done": 0, "errors": 0, "started_at": None}
batch_lock = threading.Lock()


def env_bool(name, default=False):
    return os.environ.get(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login", next=request.path))
        return fn(*args, **kwargs)
    return wrapper


def profile_hint(lead):
    return f" na área de {lead.profile}" if lead.profile else ""


def render_body(lead):
    return DEFAULT_BODY.format(office=lead.office, profile_hint=profile_hint(lead))


def text_to_html(text):
    safe = html.escape(text)
    safe = safe.replace("HM Perícia &amp; Cálculos", "<strong>HM Perícia &amp; Cálculos</strong>")
    safe = safe.replace("PJe-Calc", "<strong>PJe-Calc</strong>")
    return "".join(
        f"<p style='margin:0 0 14px 0;line-height:1.55'>{block.replace(chr(10), '<br>')}</p>"
        for block in safe.split("\n\n")
    )


def resend_config_ready():
    return bool(
        os.environ.get("RESEND_API_KEY", "").strip()
        and os.environ.get("FROM_EMAIL", "").strip()
    )


def send_via_resend(recipient, subject, text_body, html_body, attachments=None):
    api_key = os.environ.get("RESEND_API_KEY", "").strip()
    from_email = os.environ.get("FROM_EMAIL", "hugo@hmpericia.com.br").strip()
    reply_to = os.environ.get("REPLY_TO", from_email).strip()
    from_name = os.environ.get("FROM_NAME", "Hugo Mendes | HM Perícia & Cálculos").strip()

    if not api_key:
        raise RuntimeError("RESEND_API_KEY ainda não está configurada.")
    if not from_email:
        raise RuntimeError("FROM_EMAIL ainda não está configurado.")

    payload = {
        "from": f"{from_name} <{from_email}>",
        "to": [recipient],
        "subject": subject,
        "text": text_body,
        "html": html_body,
        "reply_to": reply_to,
    }

    if attachments:
        payload["attachments"] = [
            {
                "filename": item["filename"],
                "content": base64.b64encode(item["data"]).decode("ascii"),
            }
            for item in attachments
        ]

    req = urllib_request.Request(
        "https://api.resend.com/emails",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "HM-Email-Disparador/1.0",
        },
        method="POST",
    )

    try:
        with urllib_request.urlopen(req, timeout=20) as response:
            raw = response.read().decode("utf-8")
            data = json.loads(raw) if raw else {}
            if response.status < 200 or response.status >= 300:
                raise RuntimeError(f"Resend retornou HTTP {response.status}.")
            return data
    except urllib_error.HTTPError as exc:
        try:
            detail = exc.read().decode("utf-8")
        except Exception:
            detail = str(exc)
        raise RuntimeError(f"Resend HTTP {exc.code}: {detail[:800]}") from exc
    except urllib_error.URLError as exc:
        raise RuntimeError(f"Falha de conexão com a API da Resend: {exc.reason}") from exc
    except TimeoutError as exc:
        raise RuntimeError("Timeout ao conectar à API HTTPS da Resend.") from exc


def sent_today_count():
    now = datetime.now(timezone.utc)
    start = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
    return SendLog.query.filter(SendLog.sent_at >= start, SendLog.result == "sent").count()


def send_email_for_lead(lead):
    if not env_bool("SEND_ENABLED", False):
        raise RuntimeError("Envios estão bloqueados. Defina SEND_ENABLED=true no Railway somente após o teste Resend.")
    if not resend_config_ready():
        raise RuntimeError("RESEND_API_KEY/FROM_EMAIL ainda não estão configurados.")
    if lead.status == "Não contatar":
        raise RuntimeError("Lead marcado como Não contatar.")

    daily_limit = int(os.environ.get("DAILY_LIMIT", "20"))
    if sent_today_count() >= daily_limit:
        raise RuntimeError(f"Limite diário de {daily_limit} mensagens atingido.")

    subject = os.environ.get("EMAIL_SUBJECT", DEFAULT_SUBJECT)
    body = render_body(lead)
    html_body = (
        "<!doctype html><html><body style='font-family:Arial,Helvetica,sans-serif;"
        "color:#14283d;background:#ffffff'>"
        "<div style='max-width:680px;margin:auto;padding:24px'>"
        "<div style='border-top:5px solid #c9a24a;padding-top:18px'>"
        + text_to_html(body)
        + "</div>"
        "<div style='margin-top:22px;padding-top:14px;border-top:1px solid #ddd;"
        "color:#667;font-size:12px'>"
        "HM Perícia &amp; Cálculos · Precisão técnica · Informações confiáveis · Decisões seguras"
        "</div></div></body></html>"
    )

    attachments = []
    if env_bool("ATTACH_MATERIAL", False):
        material = CampaignAttachment.query.order_by(CampaignAttachment.id.desc()).first()
        if material:
            attachments.append({"filename": material.filename, "data": material.data})

    send_via_resend(
        recipient=lead.email,
        subject=subject,
        text_body=body,
        html_body=html_body,
        attachments=attachments,
    )

    lead.status = "Enviado"
    lead.last_contact = datetime.now(timezone.utc)
    lead.last_error = None
    db.session.add(SendLog(lead_id=lead.id, recipient=lead.email, subject=subject, result="sent"))
    db.session.commit()


def batch_worker(lead_ids):
    interval = max(10, int(os.environ.get("MIN_INTERVAL_SECONDS", "120")))
    with app.app_context():
        try:
            for index, lead_id in enumerate(lead_ids):
                lead = db.session.get(Lead, lead_id)
                if not lead:
                    continue
                try:
                    send_email_for_lead(lead)
                except Exception as exc:
                    lead.status = "Erro"
                    lead.last_error = str(exc)[:1000]
                    db.session.add(SendLog(
                        lead_id=lead.id,
                        recipient=lead.email,
                        subject=os.environ.get("EMAIL_SUBJECT", DEFAULT_SUBJECT),
                        result="error",
                        detail=str(exc)[:2000],
                    ))
                    db.session.commit()
                    batch_state["errors"] += 1
                    if "Limite diário" in str(exc) or "bloqueados" in str(exc):
                        break
                finally:
                    batch_state["done"] += 1
                if index < len(lead_ids) - 1:
                    time.sleep(interval)
        finally:
            batch_state["running"] = False


def import_lead_rows(rows):
    imported = 0
    updated = 0
    skipped = 0

    for row in rows:
        office = (row.get("Escritório") or row.get("office") or "").strip()
        email_addr = (row.get("E-mail") or row.get("Email") or row.get("email") or "").strip().lower()
        if not office or not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email_addr):
            skipped += 1
            continue

        lead = Lead.query.filter(db.func.lower(Lead.email) == email_addr).first()
        payload = {
            "region": (row.get("Região") or row.get("region") or "").strip(),
            "city": (row.get("Cidade") or row.get("city") or "").strip(),
            "office": office,
            "profile": (row.get("Perfil / área") or row.get("Perfil") or row.get("profile") or "").strip(),
            "email": email_addr,
            "whatsapp": (row.get("WhatsApp") or row.get("whatsapp") or "").strip(),
            "address": (row.get("Endereço") or row.get("address") or "").strip(),
            "adherence": (row.get("Aderência") or row.get("adherence") or "").strip(),
            "source_url": (row.get("Fonte pública") or row.get("source_url") or "").strip(),
            "notes": (row.get("Observações") or row.get("notes") or "").strip(),
        }
        if lead:
            for key, value in payload.items():
                if value:
                    setattr(lead, key, value)
            updated += 1
        else:
            db.session.add(Lead(**payload, status="Não contatado"))
            imported += 1

    db.session.commit()
    return imported, updated, skipped


@app.get("/health")
def health():
    return {"ok": True, "service": "hm-email-disparador"}, 200


@app.route("/login", methods=["GET", "POST"])
def login():
    admin_user = os.environ.get("ADMIN_USER", "hugo")
    admin_password = os.environ.get("ADMIN_PASSWORD", "")
    if request.method == "POST":
        supplied_user = request.form.get("username", "")
        supplied_password = request.form.get("password", "")
        valid_user = hmac.compare_digest(supplied_user, admin_user)
        valid_password = bool(admin_password) and hmac.compare_digest(supplied_password, admin_password)
        if valid_user and valid_password:
            session["logged_in"] = True
            return redirect(request.args.get("next") or url_for("dashboard"))
        if not admin_password:
            flash("ADMIN_PASSWORD ainda não foi definido no Railway.", "danger")
        else:
            flash("Usuário ou senha inválidos.", "danger")
    return render_template("login.html", admin_user=admin_user)


@app.get("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.get("/")
@login_required
def dashboard():
    return render_template(
        "dashboard.html",
        total=Lead.query.count(),
        pending=Lead.query.filter_by(status="Não contatado").count(),
        sent=Lead.query.filter_by(status="Enviado").count(),
        replies=Lead.query.filter(Lead.status.in_(["Respondeu", "Reunião agendada", "Cliente"])).count(),
        sent_today=sent_today_count(),
        daily_limit=int(os.environ.get("DAILY_LIMIT", "20")),
        send_enabled=env_bool("SEND_ENABLED", False),
        resend_ready=resend_config_ready(),
        batch=batch_state.copy(),
        material=CampaignAttachment.query.order_by(CampaignAttachment.id.desc()).first(),
    )


@app.route("/leads", methods=["GET", "POST"])
@login_required
def leads():
    if request.method == "POST":
        file = request.files.get("file")
        if not file or not file.filename:
            flash("Selecione um CSV de leads.", "warning")
            return redirect(url_for("leads"))
        if not file.filename.lower().endswith(".csv"):
            flash("A importação aceita arquivo CSV.", "danger")
            return redirect(url_for("leads"))
        try:
            raw = file.read().decode("utf-8-sig")
            imported, updated, skipped = import_lead_rows(csv.DictReader(io.StringIO(raw)))
            flash(f"Importação concluída: {imported} novo(s), {updated} atualizado(s), {skipped} ignorado(s).", "success")
        except Exception as exc:
            flash(f"Falha na importação: {exc}", "danger")
        return redirect(url_for("leads"))

    q = Lead.query
    status = request.args.get("status", "")
    region = request.args.get("region", "")
    search = request.args.get("q", "").strip()
    if status:
        q = q.filter(Lead.status == status)
    if region:
        q = q.filter(Lead.region == region)
    if search:
        term = f"%{search}%"
        q = q.filter(db.or_(Lead.office.ilike(term), Lead.city.ilike(term), Lead.email.ilike(term)))
    rows = q.order_by(Lead.adherence.asc(), Lead.city.asc(), Lead.office.asc()).all()
    regions = [r[0] for r in db.session.query(Lead.region).distinct().order_by(Lead.region).all() if r[0]]
    return render_template("leads.html", leads=rows, status_options=STATUS_OPTIONS, regions=regions)


@app.post("/lead/<int:lead_id>/status")
@login_required
def update_status(lead_id):
    lead = db.get_or_404(Lead, lead_id)
    new_status = request.form.get("status")
    if new_status in STATUS_OPTIONS:
        lead.status = new_status
        db.session.commit()
        flash("Status atualizado.", "success")
    return redirect(request.referrer or url_for("leads"))


@app.get("/lead/<int:lead_id>/preview")
@login_required
def preview(lead_id):
    lead = db.get_or_404(Lead, lead_id)
    return render_template(
        "preview.html",
        lead=lead,
        subject=os.environ.get("EMAIL_SUBJECT", DEFAULT_SUBJECT),
        body=render_body(lead),
        send_enabled=env_bool("SEND_ENABLED", False),
    )


@app.post("/lead/<int:lead_id>/send")
@login_required
def send_one(lead_id):
    lead = db.get_or_404(Lead, lead_id)
    try:
        send_email_for_lead(lead)
        flash(f"E-mail enviado para {lead.office} ({lead.email}).", "success")
    except Exception as exc:
        lead.status = "Erro"
        lead.last_error = str(exc)[:1000]
        db.session.commit()
        flash(f"Falha no envio: {exc}", "danger")
    return redirect(url_for("preview", lead_id=lead.id))


@app.post("/send-selected")
@login_required
def send_selected():
    ids = [int(raw) for raw in request.form.getlist("lead_ids") if raw.isdigit()]
    if not ids:
        flash("Selecione pelo menos um lead.", "warning")
        return redirect(url_for("leads"))

    with batch_lock:
        if batch_state["running"]:
            flash("Já existe um lote em execução.", "warning")
            return redirect(url_for("dashboard"))
        batch_state.update({
            "running": True,
            "total": len(ids),
            "done": 0,
            "errors": 0,
            "started_at": datetime.now(timezone.utc).isoformat(),
        })
        threading.Thread(target=batch_worker, args=(ids,), daemon=True).start()

    flash(f"Lote de {len(ids)} e-mails iniciado. Os envios serão individuais e espaçados.", "success")
    return redirect(url_for("dashboard"))


@app.route("/material", methods=["GET", "POST"])
@login_required
def material():
    current = CampaignAttachment.query.order_by(CampaignAttachment.id.desc()).first()
    if request.method == "POST":
        file = request.files.get("file")
        if not file or not file.filename:
            flash("Selecione um arquivo.", "warning")
        else:
            name = file.filename.strip()
            ext = os.path.splitext(name)[1].lower()
            allowed = {
                ".pdf": "application/pdf",
                ".png": "image/png",
                ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg",
            }
            if ext not in allowed:
                flash("Use PDF, PNG ou JPG.", "danger")
            else:
                data = file.read()
                if len(data) > 5 * 1024 * 1024:
                    flash("O material deve ter no máximo 5 MB.", "danger")
                else:
                    CampaignAttachment.query.delete()
                    db.session.add(CampaignAttachment(filename=name, mimetype=allowed[ext], data=data))
                    db.session.commit()
                    flash("Material comercial salvo e será anexado aos próximos envios.", "success")
                    current = CampaignAttachment.query.order_by(CampaignAttachment.id.desc()).first()
    return render_template("material.html", current=current)


@app.route("/test-email", methods=["GET", "POST"])
@login_required
def test_email():
    if request.method == "POST":
        recipient = request.form.get("recipient", "").strip()
        if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", recipient):
            flash("Informe um e-mail válido.", "danger")
        elif not resend_config_ready():
            flash("Configure RESEND_API_KEY e FROM_EMAIL no Railway primeiro.", "danger")
        else:
            try:
                test_text = "Teste concluído com sucesso. O disparador da HM está enviando pela API HTTPS da Resend."
                send_via_resend(
                    recipient=recipient,
                    subject="Teste Resend — HM Perícia & Cálculos",
                    text_body=test_text,
                    html_body=f"<p>{html.escape(test_text)}</p>",
                )
                flash("Teste enviado com sucesso pela Resend.", "success")
            except Exception as exc:
                flash(f"Falha no teste Resend: {exc}", "danger")

    return render_template(
        "test_email.html",
        resend_ready=resend_config_ready(),
        send_enabled=env_bool("SEND_ENABLED", False),
    )


with app.app_context():
    db.create_all()
    seed_b64 = os.environ.get("LEADS_SEED_B64", "").strip()
    if seed_b64 and Lead.query.count() == 0:
        try:
            seed_csv = base64.b64decode(seed_b64).decode("utf-8-sig")
            import_lead_rows(csv.DictReader(io.StringIO(seed_csv)))
        except Exception as exc:
            app.logger.error("Falha ao carregar base inicial de leads: %s", exc)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")), debug=False)
