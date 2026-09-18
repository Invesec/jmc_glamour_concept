import os
import json
import secrets
import string
from datetime import datetime

import requests
from flask import (
    Flask, render_template, request, redirect, url_for, flash, abort,
    send_from_directory
)
from flask_sqlalchemy import SQLAlchemy
from flask_login import (
    LoginManager, UserMixin, login_user, login_required,
    logout_user, current_user
)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

basedir = os.path.abspath(os.path.dirname(__file__))

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-change-me')

# ── Database ──────────────────────────────────────────────────────────────
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get(
    'DATABASE_URL',
    f"sqlite:///{os.path.join(basedir, 'instance', 'jmc.db')}"
)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
if app.config['SQLALCHEMY_DATABASE_URI'].startswith('sqlite'):
    from sqlalchemy.pool import NullPool
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {'poolclass': NullPool}

db = SQLAlchemy(app)
app.config['UPLOAD_FOLDER'] = os.path.join(basedir, 'uploads')

login_manager = LoginManager(app)
login_manager.login_view = 'admin_login'

# ── Business config ──────────────────────────────────────────────────────
BANK_NAME = os.environ.get('BANK_NAME', 'Opay')
BANK_ACCOUNT_NAME = os.environ.get('BANK_ACCOUNT_NAME', 'JMC Glamour Concept')
BANK_ACCOUNT_NUMBER = os.environ.get('BANK_ACCOUNT_NUMBER', '0000000000')
WHATSAPP_NUMBER = os.environ.get('WHATSAPP_NUMBER', '2340000000000')

# ── Admin notifications (best-effort; never blocks order placement) ────────
ADMIN_EMAIL = os.environ.get('ADMIN_EMAIL', '')
BREVO_API_KEY = os.environ.get('BREVO_API_KEY', '')
BREVO_SENDER_EMAIL = os.environ.get('BREVO_SENDER_EMAIL', '')
ADMIN_WHATSAPP_NUMBER = os.environ.get('ADMIN_WHATSAPP_NUMBER', '')
CALLMEBOT_APIKEY = os.environ.get('CALLMEBOT_APIKEY', '')

SERVICES = [
    {
        "category": "JAMB Services",
        "items": [
            {"slug": "jamb-registration", "name": "JAMB Registration", "price": 8700},
            {"slug": "jamb-pin-vending", "name": "JAMB Pin Vending", "price": 8700},
            {"slug": "jamb-slip-reprint", "name": "JAMB Slip Reprint", "price": 1500},
            {"slug": "jamb-original-result", "name": "JAMB Original Result", "price": 3500},
            {"slug": "jamb-olevel-result", "name": "JAMB O'Level Result", "price": 3500},
            {"slug": "jamb-admission-letter", "name": "JAMB Admission Letter", "price": 3500},
            {"slug": "post-utme-registration", "name": "Post UTME Registration", "price": 5000},
            {"slug": "change-course-institution", "name": "Change of Course / Institution", "price": 7000},
        ],
    },
    {
        "category": "WAEC / NECO",
        "items": [
            {"slug": "waec-gce-registration", "name": "WAEC GCE Registration", "price": None},
            {"slug": "neco-gce-registration", "name": "NECO GCE Registration", "price": None},
            {"slug": "waec-scratch-card", "name": "WAEC Scratch Card (Pin & Print)", "price": 7500},
            {"slug": "neco-scratch-card", "name": "NECO Scratch Card (Pin & Print)", "price": 5500},
        ],
    },
    {
        "category": "Institution Payments",
        "items": [
            {"slug": "clearance-acceptance", "name": "Clearance / Acceptance Fee (All Universities)", "price": None},
            {"slug": "school-fees", "name": "School Fees Payment (All Universities)", "price": None},
        ],
    },
    {
        "category": "Recruitment Forms",
        "items": [
            {"slug": "army-form", "name": "Army Form Processing", "price": 4000},
            {"slug": "navy-form", "name": "Navy Form Processing", "price": 4000},
            {"slug": "police-form", "name": "Police Form Processing", "price": 4000},
        ],
    },
    {
        "category": "Other Services",
        "items": [
            {"slug": "epin-printing", "name": "E-Pin Printing (All Networks)", "price": None},
            {"slug": "general-online-service", "name": "General Online Service (Custom Request)", "price": None},
        ],
    },
]

SERVICES_BY_SLUG = {item["slug"]: item for cat in SERVICES for item in cat["items"]}

NIGERIA_STATES = [
    "Abia", "Adamawa", "Akwa Ibom", "Anambra", "Bauchi", "Bayelsa", "Benue",
    "Borno", "Cross River", "Delta", "Ebonyi", "Edo", "Ekiti", "Enugu",
    "FCT (Abuja)", "Gombe", "Imo", "Jigawa", "Kaduna", "Kano", "Katsina",
    "Kebbi", "Kogi", "Kwara", "Lagos", "Nasarawa", "Niger", "Ogun", "Ondo",
    "Osun", "Oyo", "Plateau", "Rivers", "Sokoto", "Taraba", "Yobe", "Zamfara",
]

UTME_SUBJECTS = [
    "English Language", "Mathematics", "Physics", "Chemistry", "Biology",
    "Agricultural Science", "Economics", "Government", "Literature in English",
    "Geography", "Commerce", "Accounting", "Christian Religious Studies",
    "Islamic Religious Studies", "History", "CRK", "IRK", "Hausa", "Igbo",
    "Yoruba", "French", "Arabic", "Fine Arts", "Music", "Civic Education",
    "Insurance", "Store Management",
]

JAMB_REG_FIELDS = [
    {"name": "surname", "label": "Surname (exactly as on your NIN)", "type": "text", "required": True},
    {"name": "first_name", "label": "First Name (exactly as on your NIN)", "type": "text", "required": True},
    {"name": "other_names", "label": "Other Names (as on your NIN)", "type": "text", "required": False},
    {"name": "nin", "label": "National Identification Number (NIN)", "type": "text", "required": True,
     "help": "11 digits. Must match your NIMC record exactly — mismatches delay registration."},
    {"name": "date_of_birth", "label": "Date of Birth", "type": "date", "required": True},
    {"name": "gender", "label": "Gender", "type": "select", "options": ["Male", "Female"], "required": True},
    {"name": "state_of_origin", "label": "State of Origin", "type": "select", "options": NIGERIA_STATES, "required": True},
    {"name": "lga", "label": "Local Government Area (LGA)", "type": "text", "required": True},
    {"name": "phone_on_nin", "label": "Active Phone Number (personal SIM, never used for JAMB before)", "type": "tel", "required": True},
    {"name": "email", "label": "Email Address", "type": "email", "required": True},
    {"name": "jamb_profile_code", "label": "JAMB Profile Code (leave blank if you don't have one yet)", "type": "text", "required": False},
    {"name": "olevel_status", "label": "O'Level Result Status", "type": "select",
     "options": ["Already have result", "Awaiting result — will provide later"], "required": True},
    {"name": "olevel_exam_type", "label": "Exam Body", "type": "select",
     "options": ["WAEC", "NECO", "NABTEB", "Not yet applicable"], "required": False},
    {"name": "olevel_exam_year", "label": "Exam Year", "type": "text", "required": False},
    {"name": "olevel_exam_number", "label": "Exam Number", "type": "text", "required": False},
    {"name": "first_choice_institution", "label": "First Choice Institution", "type": "text", "required": True},
    {"name": "first_choice_course", "label": "First Choice Course", "type": "text", "required": True},
    {"name": "subject_2", "label": "Subject 2 (English Language is automatic)", "type": "select", "options": UTME_SUBJECTS, "required": True},
    {"name": "subject_3", "label": "Subject 3", "type": "select", "options": UTME_SUBJECTS, "required": True},
    {"name": "subject_4", "label": "Subject 4", "type": "select", "options": UTME_SUBJECTS, "required": True},
    {"name": "passport_photo", "label": "Passport Photograph", "type": "file", "required": True,
     "help": "Recent, plain light background, JPG or PNG."},
]


def jamb_followup_fields(extra=None):
    """Shared fields for anything that acts on an *existing* JAMB profile
    (slip reprint, result, admission letter, post-UTME, course change)."""
    base = [
        {"name": "full_name_jamb", "label": "Full Name (as registered with JAMB)", "type": "text", "required": True},
        {"name": "jamb_reg_number", "label": "JAMB Registration Number / Profile Code", "type": "text", "required": True},
        {"name": "phone", "label": "Phone Number Registered with JAMB", "type": "tel", "required": True},
        {"name": "email", "label": "Email Address", "type": "email", "required": True},
    ]
    return base + (extra or [])


def gce_fields(body_name):
    """WAEC/NECO GCE (private candidate) registration."""
    return [
        {"name": "surname", "label": "Surname", "type": "text", "required": True},
        {"name": "first_name", "label": "First Name", "type": "text", "required": True},
        {"name": "other_names", "label": "Other Names", "type": "text", "required": False},
        {"name": "date_of_birth", "label": "Date of Birth", "type": "date", "required": True},
        {"name": "gender", "label": "Gender", "type": "select", "options": ["Male", "Female"], "required": True},
        {"name": "marital_status", "label": "Marital Status", "type": "select", "options": ["Single", "Married"], "required": False},
        {"name": "state_of_origin", "label": "State of Origin", "type": "select", "options": NIGERIA_STATES, "required": True},
        {"name": "nin", "label": "National Identification Number (NIN)", "type": "text", "required": True, "help": "11 digits."},
        {"name": "phone", "label": "Active Phone Number (for SMS updates)", "type": "tel", "required": True},
        {"name": "email", "label": "Email Address", "type": "email", "required": True},
        {"name": "subjects", "label": f"Subjects to Register For ({body_name} GCE: minimum 5, maximum 9)", "type": "textarea", "required": True,
         "help": "List each subject on its own line, e.g. English Language, Mathematics, Biology..."},
        {"name": "exam_center_state", "label": "Preferred Exam Center State", "type": "select", "options": NIGERIA_STATES, "required": True},
        {"name": "passport_photo", "label": "Passport Photograph", "type": "file", "required": True,
         "help": "Plain white/light background, JPEG format, digital camera capture."},
    ]


def scratch_card_fields(body_name):
    """Result checker PIN purchase + printing."""
    return [
        {"name": "full_name", "label": "Candidate's Full Name", "type": "text", "required": True},
        {"name": "exam_number", "label": f"{body_name} Examination / Candidate Number", "type": "text", "required": True},
        {"name": "exam_year", "label": "Exam Year", "type": "text", "required": True},
        {"name": "exam_type", "label": "Exam Type", "type": "select",
         "options": [f"{body_name} May/June (School Candidate)", f"{body_name} GCE (Private Candidate)"], "required": True},
        {"name": "delivery_preference", "label": "How should we deliver it?", "type": "select",
         "options": ["PIN only (sent by WhatsApp/email)", "PIN + printed result (scan or hard copy)"], "required": True},
        {"name": "phone", "label": "Phone Number", "type": "tel", "required": True},
        {"name": "email", "label": "Email Address", "type": "email", "required": False},
    ]


def institution_payment_fields(purpose_label):
    """Clearance/acceptance or school fees payment made on the student's behalf."""
    return [
        {"name": "student_full_name", "label": "Student's Full Name", "type": "text", "required": True},
        {"name": "institution_name", "label": "Institution Name", "type": "text", "required": True},
        {"name": "faculty_department", "label": "Faculty / Department", "type": "text", "required": False},
        {"name": "matric_or_jamb_number", "label": "Matric Number or JAMB Registration Number", "type": "text", "required": True},
        {"name": "level_session", "label": "Level & Session (e.g. 100L, 2025/2026)", "type": "text", "required": True},
        {"name": "amount_to_pay", "label": f"Exact Amount to Pay for {purpose_label}", "type": "text", "required": True,
         "help": "Check your institution's portal or invoice for the exact figure — we pay this exact amount on your behalf."},
        {"name": "payment_deadline", "label": "Payment Deadline (if any)", "type": "date", "required": False},
        {"name": "phone", "label": "Phone Number", "type": "tel", "required": True},
        {"name": "email", "label": "Email Address", "type": "email", "required": True},
        {"name": "proof_document", "label": "Invoice / Remita / Payment Advice (if you have one)", "type": "file", "required": False},
    ]


def military_form_fields(force_name):
    """Army/Navy/Police recruitment form processing.
    Note: recruitment itself is free from the official portals — this fee
    covers JMC's processing/filing assistance, not the application."""
    return [
        {"name": "surname", "label": "Surname", "type": "text", "required": True},
        {"name": "first_name", "label": "First Name", "type": "text", "required": True},
        {"name": "other_names", "label": "Other Names", "type": "text", "required": False},
        {"name": "nin", "label": "National Identification Number (NIN)", "type": "text", "required": True, "help": "11 digits."},
        {"name": "bvn", "label": "Bank Verification Number (BVN)", "type": "text", "required": True,
         "help": "Name and date of birth on your BVN must match your NIN exactly."},
        {"name": "date_of_birth", "label": "Date of Birth", "type": "date", "required": True},
        {"name": "gender", "label": "Gender", "type": "select", "options": ["Male", "Female"], "required": True},
        {"name": "marital_status", "label": "Marital Status", "type": "select", "options": ["Single", "Married"], "required": True,
         "help": f"Most {force_name} recruit intakes require applicants to be single."},
        {"name": "state_of_origin", "label": "State of Origin", "type": "select", "options": NIGERIA_STATES, "required": True},
        {"name": "lga", "label": "Local Government Area (LGA)", "type": "text", "required": True},
        {"name": "height_cm", "label": "Height (cm)", "type": "text", "required": False},
        {"name": "highest_qualification", "label": "Highest Qualification", "type": "select",
         "options": ["SSCE (WAEC/NECO)", "OND", "NCE", "HND", "Bachelor's Degree", "Other"], "required": True},
        {"name": "phone", "label": "Phone Number", "type": "tel", "required": True},
        {"name": "email", "label": "Email Address", "type": "email", "required": True},
        {"name": "guarantor_name", "label": "Guarantor's Full Name", "type": "text", "required": False},
        {"name": "guarantor_phone", "label": "Guarantor's Phone Number", "type": "tel", "required": False},
        {"name": "passport_photo", "label": "Passport Photograph", "type": "file", "required": True,
         "help": "Recent, plain background, JPG or PNG."},
    ]


# Field schema for services that need a detailed intake form beyond
# name/phone/email/notes. Key = service slug. Each field:
# name, label, type (text/tel/email/date/select/textarea/file), required, options, help
FIELD_DEFS = {
    "jamb-registration": JAMB_REG_FIELDS,

    "jamb-pin-vending": [
        {"name": "full_name", "label": "Full Name", "type": "text", "required": True},
        {"name": "phone", "label": "Phone Number (personal SIM, never used for JAMB before)", "type": "tel", "required": True},
        {"name": "email", "label": "Email Address", "type": "email", "required": True},
        {"name": "pin_type", "label": "ePIN Type", "type": "select",
         "options": ["UTME with Mock", "UTME without Mock", "Direct Entry (DE)"], "required": True},
    ],

    "jamb-slip-reprint": jamb_followup_fields([
        {"name": "reprint_reason", "label": "Reason for Reprint", "type": "select",
         "options": ["Lost original slip", "Slip damaged", "Need extra copy", "Other"], "required": False},
    ]),

    "jamb-original-result": jamb_followup_fields([
        {"name": "exam_year", "label": "UTME Exam Year", "type": "text", "required": True},
        {"name": "purpose", "label": "Purpose (e.g. institution submission, scholarship)", "type": "text", "required": False},
    ]),

    "jamb-olevel-result": jamb_followup_fields([
        {"name": "olevel_exam_type", "label": "Exam Body", "type": "select", "options": ["WAEC", "NECO", "NABTEB"], "required": True},
        {"name": "olevel_exam_number", "label": "Exam Number", "type": "text", "required": True},
        {"name": "olevel_exam_year", "label": "Exam Year", "type": "text", "required": True},
    ]),

    "jamb-admission-letter": jamb_followup_fields([
        {"name": "institution_admitted", "label": "Institution Admitted Into", "type": "text", "required": True},
        {"name": "course_admitted", "label": "Course Admitted Into", "type": "text", "required": True},
        {"name": "admission_session", "label": "Admission Session (e.g. 2025/2026)", "type": "text", "required": True},
    ]),

    "post-utme-registration": jamb_followup_fields([
        {"name": "utme_score", "label": "UTME Score", "type": "text", "required": True},
        {"name": "institution_post_utme", "label": "Institution for Post-UTME", "type": "text", "required": True},
        {"name": "olevel_status", "label": "O'Level Result Status", "type": "select",
         "options": ["Already have result", "Awaiting result"], "required": True},
    ]),

    "change-course-institution": jamb_followup_fields([
        {"name": "current_institution", "label": "Current Institution on JAMB Profile", "type": "text", "required": True},
        {"name": "current_course", "label": "Current Course on JAMB Profile", "type": "text", "required": True},
        {"name": "desired_institution", "label": "Desired Institution", "type": "text", "required": True},
        {"name": "desired_course", "label": "Desired Course", "type": "text", "required": True},
        {"name": "utme_score", "label": "UTME Score", "type": "text", "required": True},
    ]),

    "waec-gce-registration": gce_fields("WAEC"),
    "neco-gce-registration": gce_fields("NECO"),

    "waec-scratch-card": scratch_card_fields("WAEC"),
    "neco-scratch-card": scratch_card_fields("NECO"),

    "clearance-acceptance": institution_payment_fields("Clearance / Acceptance Fee"),
    "school-fees": institution_payment_fields("School Fees"),

    "army-form": military_form_fields("Nigerian Army"),
    "navy-form": military_form_fields("Nigerian Navy"),
    "police-form": military_form_fields("Nigeria Police Force"),

    "epin-printing": [
        {"name": "network", "label": "Network", "type": "select", "options": ["MTN", "Glo", "Airtel", "9mobile"], "required": True},
        {"name": "pin_kind", "label": "PIN Type", "type": "select", "options": ["Airtime Recharge PIN", "Data PIN"], "required": True},
        {"name": "denomination", "label": "Denomination / Amount", "type": "text", "required": True},
        {"name": "quantity", "label": "Quantity", "type": "text", "required": True},
        {"name": "phone", "label": "Phone Number for Delivery", "type": "tel", "required": True},
        {"name": "email", "label": "Email Address", "type": "email", "required": False},
    ],

    # "general-online-service" intentionally has no entry — it keeps the
    # simple generic name/phone/email/notes form, since the request itself
    # defines what's needed.
}


def extract_identity(values):
    """Pull a display name/phone/email out of whatever field names a
    particular form happened to use, so every custom form can share one
    order-creation code path."""
    full_name = None
    for key in ("full_name", "full_name_jamb", "student_full_name"):
        if values.get(key):
            full_name = values[key]
            break
    if not full_name and values.get("surname"):
        full_name = " ".join(
            p for p in [values.get("surname"), values.get("first_name"), values.get("other_names")] if p
        )
    phone = values.get("phone") or values.get("phone_on_nin") or ""
    email = values.get("email") or ""
    return full_name or "Unnamed", phone, email


def notify_admin_new_order(order):
    """Fire-and-forget notifications to the admin. Failures are logged and
    swallowed — a notification going down must never block an order."""
    _send_admin_email(order)
    _send_admin_whatsapp(order)


def _format_amount(order):
    return f"₦{order.price:,}" if order.price else "To be confirmed"


def _build_details_table(order):
    """Turn extra_data / notes into an HTML table for the email body."""
    rows = [
        ("Reference", order.reference),
        ("Service", order.service_name),
        ("Amount", _format_amount(order)),
        ("Customer", order.full_name),
        ("Phone", order.phone),
        ("Email", order.email or "-"),
    ]
    if order.notes:
        rows.append(("Notes", order.notes))
    if order.extra_data:
        try:
            details = json.loads(order.extra_data)
            rows.extend(details.items())
        except (ValueError, TypeError):
            pass

    row_html = "".join(
        f"<tr><td style='padding:4px 12px 4px 0;color:#555;white-space:nowrap;"
        f"vertical-align:top;'><strong>{label}</strong></td>"
        f"<td style='padding:4px 0;'>{value}</td></tr>"
        for label, value in rows
    )
    return f"<table style='border-collapse:collapse;font-family:sans-serif;font-size:14px;'>{row_html}</table>"


def _build_attachments(order):
    """Read any files uploaded for this order and base64-encode them for Brevo."""
    import base64

    attachments = []
    filenames = {}
    if order.passport_photo_filename:
        filenames["passport photo"] = order.passport_photo_filename
    if order.files_json:
        try:
            filenames.update(json.loads(order.files_json))
        except (ValueError, TypeError):
            pass

    for label, fname in filenames.items():
        path = os.path.join(app.config['UPLOAD_FOLDER'], fname)
        try:
            with open(path, 'rb') as fh:
                content = base64.b64encode(fh.read()).decode('ascii')
            attachments.append({"name": f"{label} - {fname}", "content": content})
        except OSError as e:
            app.logger.warning(f"Could not attach {fname} to admin email: {e}")
    return attachments


def _send_admin_email(order):
    if not (BREVO_API_KEY and BREVO_SENDER_EMAIL and ADMIN_EMAIL):
        return
    try:
        payload = {
            "sender": {"email": BREVO_SENDER_EMAIL, "name": "JMC Glamour Concept"},
            "to": [{"email": ADMIN_EMAIL}],
            "subject": f"New order {order.reference} — {order.service_name}",
            "htmlContent": (
                f"<p><strong>New order placed</strong></p>"
                f"{_build_details_table(order)}"
                f"<p style='margin-top:14px;'>Open the admin dashboard to change status or add notes.</p>"
            ),
        }
        attachments = _build_attachments(order)
        if attachments:
            payload["attachment"] = attachments

        requests.post(
            "https://api.brevo.com/v3/smtp/email",
            headers={
                "api-key": BREVO_API_KEY,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            json=payload,
            timeout=15,
        )
    except requests.RequestException as e:
        app.logger.warning(f"Admin email notification failed: {e}")


def _send_admin_whatsapp(order):
    if not (CALLMEBOT_APIKEY and ADMIN_WHATSAPP_NUMBER):
        return
    try:
        message = (
            f"New JMC order {order.reference}\n"
            f"{order.service_name}\n"
            f"{_format_amount(order)}\n"
            f"Customer: {order.full_name} ({order.phone})"
        )
        requests.get(
            "https://api.callmebot.com/whatsapp.php",
            params={"phone": ADMIN_WHATSAPP_NUMBER, "text": message, "apikey": CALLMEBOT_APIKEY},
            timeout=8,
        )
    except requests.RequestException as e:
        app.logger.warning(f"Admin WhatsApp notification failed: {e}")


# ── Models ────────────────────────────────────────────────────────────────
class Admin(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)

    def set_password(self, pw):
        self.password_hash = generate_password_hash(pw)

    def check_password(self, pw):
        return check_password_hash(self.password_hash, pw)


class Order(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    reference = db.Column(db.String(20), unique=True, nullable=False)
    service_slug = db.Column(db.String(80), nullable=False)
    service_name = db.Column(db.String(150), nullable=False)
    price = db.Column(db.Integer, nullable=True)  # None = "contact for price"
    full_name = db.Column(db.String(150), nullable=False)
    phone = db.Column(db.String(30), nullable=False)
    email = db.Column(db.String(150), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    extra_data = db.Column(db.Text, nullable=True)  # JSON string: {label: value} for detailed intake forms
    passport_photo_filename = db.Column(db.String(255), nullable=True)  # kept for backward compat
    files_json = db.Column(db.Text, nullable=True)  # JSON string: {label: stored_filename} for any uploaded files
    status = db.Column(db.String(20), nullable=False, default='pending')
    # pending -> paid -> processing -> completed  (or cancelled)
    admin_notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


@login_manager.user_loader
def load_user(user_id):
    return Admin.query.get(int(user_id))


def generate_reference():
    while True:
        suffix = ''.join(secrets.choice(string.digits) for _ in range(6))
        ref = f"JMC-{suffix}"
        if not Order.query.filter_by(reference=ref).first():
            return ref


STATUS_LABELS = {
    'pending': 'Pending Payment',
    'paid': 'Payment Confirmed',
    'processing': 'Processing',
    'completed': 'Completed',
    'cancelled': 'Cancelled',
}
STATUS_ORDER = ['pending', 'paid', 'processing', 'completed', 'cancelled']


@app.context_processor
def inject_globals():
    return dict(
        whatsapp_number=WHATSAPP_NUMBER,
        status_labels=STATUS_LABELS,
    )


@app.template_filter('fromjson')
def fromjson_filter(s):
    if not s:
        return {}
    try:
        return json.loads(s)
    except (ValueError, TypeError):
        return {}


# ── Public routes ────────────────────────────────────────────────────────
@app.route('/')
def index():
    return render_template('index.html', services=SERVICES)


@app.route('/order/<slug>', methods=['GET', 'POST'])
def order(slug):
    service = SERVICES_BY_SLUG.get(slug)
    if not service:
        abort(404)

    fields = FIELD_DEFS.get(slug)

    if fields:
        # Detailed intake form (JAMB, WAEC/NECO GCE, forces, institution payments, etc.)
        values = {}
        for f in fields:
            if f['type'] not in ('file',):
                values[f['name']] = request.form.get(f['name'], '').strip()

        if request.method == 'POST':
            errors = []
            file_uploads = {}

            for f in fields:
                if f['type'] == 'file':
                    file_obj = request.files.get(f['name'])
                    if file_obj and file_obj.filename:
                        ext = os.path.splitext(file_obj.filename)[1]
                        fname = f"{secrets.token_hex(8)}{ext}"
                        os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
                        file_obj.save(os.path.join(app.config['UPLOAD_FOLDER'], fname))
                        file_uploads[f['label']] = fname
                    elif f.get('required'):
                        errors.append(f"{f['label']} is required.")
                elif f.get('required') and not values.get(f['name']):
                    errors.append(f"{f['label']} is required.")

            nin_val = values.get('nin', '')
            if nin_val and (not nin_val.isdigit() or len(nin_val) != 11):
                errors.append("NIN must be exactly 11 digits.")

            if errors:
                for e in errors:
                    flash(e, 'error')
                return render_template('order_custom.html', service=service, fields=fields, values=values)

            full_name, phone, email = extract_identity(values)
            readable = {
                f['label']: values[f['name']]
                for f in fields
                if f['type'] != 'file' and values.get(f['name'])
            }

            new_order = Order(
                reference=generate_reference(),
                service_slug=service['slug'],
                service_name=service['name'],
                price=service['price'],
                full_name=full_name,
                phone=phone,
                email=email or None,
                notes=None,
                extra_data=json.dumps(readable),
                files_json=json.dumps(file_uploads) if file_uploads else None,
                status='pending',
            )
            db.session.add(new_order)
            db.session.commit()
            notify_admin_new_order(new_order)
            return redirect(url_for('order_success', reference=new_order.reference))

        return render_template('order_custom.html', service=service, fields=fields, values=values)

    # Generic form (all other services)
    if request.method == 'POST':
        full_name = request.form.get('full_name', '').strip()
        phone = request.form.get('phone', '').strip()
        email = request.form.get('email', '').strip()
        notes = request.form.get('notes', '').strip()

        if not full_name or not phone:
            flash('Please fill in your full name and phone number.', 'error')
            return render_template('order.html', service=service)

        new_order = Order(
            reference=generate_reference(),
            service_slug=service['slug'],
            service_name=service['name'],
            price=service['price'],
            full_name=full_name,
            phone=phone,
            email=email or None,
            notes=notes or None,
            status='pending',
        )
        db.session.add(new_order)
        db.session.commit()
        notify_admin_new_order(new_order)
        return redirect(url_for('order_success', reference=new_order.reference))

    return render_template('order.html', service=service)


@app.route('/order-success/<reference>')
def order_success(reference):
    order = Order.query.filter_by(reference=reference).first_or_404()
    bank_details = dict(
        bank_name=BANK_NAME,
        account_name=BANK_ACCOUNT_NAME,
        account_number=BANK_ACCOUNT_NUMBER,
    )
    return render_template('order_success.html', order=order, bank=bank_details)


@app.route('/track', methods=['GET', 'POST'])
def track():
    order = None
    searched = False
    if request.method == 'POST':
        searched = True
        ref = request.form.get('reference', '').strip().upper()
        order = Order.query.filter_by(reference=ref).first()
    return render_template('track.html', order=order, searched=searched)


# ── Admin routes ─────────────────────────────────────────────────────────
@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if current_user.is_authenticated:
        return redirect(url_for('admin_dashboard'))
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        admin = Admin.query.filter_by(username=username).first()
        if admin and admin.check_password(password):
            login_user(admin)
            return redirect(url_for('admin_dashboard'))
        flash('Invalid username or password.', 'error')
    return render_template('admin_login.html')


@app.route('/admin/logout')
@login_required
def admin_logout():
    logout_user()
    return redirect(url_for('admin_login'))


@app.route('/admin')
@login_required
def admin_dashboard():
    status_filter = request.args.get('status', 'all')
    query = Order.query.order_by(Order.created_at.desc())
    if status_filter != 'all':
        query = query.filter_by(status=status_filter)
    orders = query.all()

    counts = {s: Order.query.filter_by(status=s).count() for s in STATUS_ORDER}
    counts['all'] = Order.query.count()

    return render_template(
        'admin_dashboard.html',
        orders=orders,
        counts=counts,
        status_filter=status_filter,
        status_order=STATUS_ORDER,
    )


@app.route('/admin/uploads/<filename>')
@login_required
def admin_view_upload(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)


@app.route('/admin/order/<int:order_id>/status', methods=['POST'])
@login_required
def update_status(order_id):
    order = Order.query.get_or_404(order_id)
    new_status = request.form.get('status')
    if new_status in STATUS_LABELS:
        order.status = new_status
        db.session.commit()
        flash(f'Order {order.reference} marked as {STATUS_LABELS[new_status]}.', 'success')
    return redirect(request.referrer or url_for('admin_dashboard'))


@app.route('/admin/order/<int:order_id>/note', methods=['POST'])
@login_required
def update_note(order_id):
    order = Order.query.get_or_404(order_id)
    order.admin_notes = request.form.get('admin_notes', '').strip() or None
    db.session.commit()
    flash(f'Note saved for {order.reference}.', 'success')
    return redirect(request.referrer or url_for('admin_dashboard'))


# ── Startup: create tables + default admin (runs on import, so gunicorn works too) ──
with app.app_context():
    os.makedirs(os.path.join(basedir, 'instance'), exist_ok=True)
    db.create_all()
    if not Admin.query.first():
        default_admin = Admin(username='admin')
        default_admin.set_password(os.environ.get('ADMIN_DEFAULT_PASSWORD', 'JMC@Admin123'))
        db.session.add(default_admin)
        db.session.commit()
        print("Created default admin -> admin / (see ADMIN_DEFAULT_PASSWORD or JMC@Admin123)")


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    debug_mode = os.environ.get('FLASK_DEBUG', 'true').lower() == 'true'
    app.run(debug=debug_mode, host='0.0.0.0', port=port)
