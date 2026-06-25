import re

from django.core.exceptions import ValidationError
from django.core.validators import validate_email

from .constants import HARDWARE_LEAVER_TERMS, REGION_SUFFIXES


def parse_destinatarios_email(destinatario_email):
    if not destinatario_email:
        return []

    if isinstance(destinatario_email, str):
        destinatarios = [email.strip() for email in destinatario_email.split(',') if email.strip()]
    elif isinstance(destinatario_email, (list, tuple)):
        destinatarios = [str(email).strip() for email in destinatario_email if email and str(email).strip()]
    else:
        return []

    emails_validos = []
    for email in destinatarios:
        try:
            validate_email(email)
            emails_validos.append(email)
        except ValidationError:
            continue
    return emails_validos


def extraer_nombre(subject):
    nombre = re.sub(r'^(Joiner|Mover|Leaver)\s+Notification\s+', '', subject, flags=re.IGNORECASE)
    nombre = re.sub(r'\s+\d{1,2}-\d{1,2}-\d{4}$', '', nombre)
    nombre = re.sub(r'\s+\d{4}-\d{1,2}-\d{1,2}$', '', nombre)
    sufijos = '|'.join(re.escape(region) for region in REGION_SUFFIXES)
    nombre = re.sub(rf'\s+({sufijos})\s*$', '', nombre, flags=re.IGNORECASE)
    return nombre.strip()


def es_nz_o_australia(subject):
    return bool(re.search(r'\b(New Zealand|Australia|NZ)\b', subject, re.IGNORECASE))


def normalizar_subject(subject):
    if not subject:
        return ''

    normalized = str(subject).lower()
    normalized = normalized.replace('–', '-').replace('—', '-')
    normalized = re.sub(r'[^a-z0-9]+', ' ', normalized)
    return re.sub(r'\s+', ' ', normalized).strip()


def normalizar_request_id(value):
    if value is None:
        return ''

    normalized = str(value).replace('\xa0', ' ').strip()
    normalized = re.sub(r'\s+', '', normalized)
    if normalized.lower().endswith('.0'):
        normalized = normalized[:-2]
    return normalized.upper()


def es_hardware_leaver_subject(subject):
    subject_normalizado = normalizar_subject(subject)
    if 'joiner' in subject_normalizado or 'mover' in subject_normalizado:
        return False

    return any(patron in subject_normalizado for patron in HARDWARE_LEAVER_TERMS)
