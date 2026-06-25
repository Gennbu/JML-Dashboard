import warnings

import pandas as pd
from django.db import transaction

from ..constants import DATE_COLUMNS
from ..models import Ticket
from ..utils import es_hardware_leaver_subject, normalizar_request_id

# Silenciar warnings de Pandas que no son críticos durante la carga.
warnings.filterwarnings("ignore", category=UserWarning, module='pandas')


def cargar_tickets_desde_csv(csv_file, limpiar_bd=False):
    if limpiar_bd:
        Ticket.objects.all().delete()

    try:
        preview = pd.read_csv(csv_file, nrows=10, header=None)
        csv_file.seek(0)
        header_row = detectar_header_row(preview)
        chunks = pd.read_csv(
            csv_file,
            skiprows=header_row,
            chunksize=500,
            dtype=str,
            low_memory=False,
        )
    except Exception as exc:
        raise ValueError(f'Error al abrir CSV: {exc}') from exc

    total_creados = 0

    try:
        for chunk in chunks:
            chunk = preparar_chunk(chunk)
            col_id, col_sub, col_status, col_linked = detectar_columnas(chunk)
            if not col_id or not col_sub:
                continue

            tickets_to_create = construir_tickets_chunk(
                chunk=chunk,
                col_id=col_id,
                col_sub=col_sub,
                col_status=col_status,
                col_linked=col_linked,
            )
            if not tickets_to_create:
                continue

            with transaction.atomic():
                Ticket.objects.bulk_create(tickets_to_create, ignore_conflicts=True)
            total_creados += len(tickets_to_create)
    except Exception as exc:
        print(f"Error procesando chunks: {exc}")
        raise ValueError(f'Error procesando datos: {exc}') from exc

    return total_creados


def detectar_header_row(preview):
    header_row = 0
    for index, row in preview.iterrows():
        row_str = str(row.values).lower()
        if 'requestid' in row_str or 'subject' in row_str:
            header_row = index
            break
    return header_row


def preparar_chunk(chunk):
    chunk.columns = [col.strip().lower().replace(' ', '_').replace('-', '_') for col in chunk.columns]
    for date_column in DATE_COLUMNS:
        actual_col = next((col for col in chunk.columns if col == date_column), None)
        if actual_col:
            chunk[actual_col] = pd.to_datetime(chunk[actual_col], errors='coerce').dt.date
    return chunk


def detectar_columnas(chunk):
    col_id = 'requestid' if 'requestid' in chunk.columns else ('request_id' if 'request_id' in chunk.columns else None)
    col_sub = 'subject' if 'subject' in chunk.columns else None
    col_status = 'request_status' if 'request_status' in chunk.columns else ('status' if 'status' in chunk.columns else None)
    col_linked = 'linked_request_id' if 'linked_request_id' in chunk.columns else ('linked_id' if 'linked_id' in chunk.columns else None)
    return col_id, col_sub, col_status, col_linked


def construir_tickets_chunk(chunk, col_id, col_sub, col_status, col_linked):
    tickets_to_create = []

    for row in chunk.itertuples(index=False):
        request_id = normalizar_request_id(getattr(row, col_id, ''))
        if not request_id or request_id.lower() in ['nan', 'requestid', '']:
            continue

        subject = str(getattr(row, col_sub, '')).strip()
        if not subject or es_hardware_leaver_subject(subject):
            continue

        status = str(getattr(row, col_status, 'Open')).strip()
        linked_request_id = normalizar_linked_request_id(getattr(row, col_linked, None), request_id)

        tickets_to_create.append(
            Ticket(
                request_id=request_id,
                subject=subject,
                request_status=status,
                technician=limpiar_valor(getattr(row, 'technician', None)),
                created_time=getattr(row, 'created_time', getattr(row, 'created_at', None)),
                last_updated=getattr(row, 'last_updated_time', getattr(row, 'last_updated', None)),
                resolved_time=getattr(row, 'resolved_time', getattr(row, 'resolved_at', None)),
                linked_request_id=linked_request_id,
                requester=limpiar_valor(getattr(row, 'requester', None)),
            )
        )

    return tickets_to_create


def normalizar_linked_request_id(linked_request_id, request_id):
    if pd.isna(linked_request_id) or str(linked_request_id).lower() in ['nan', '', 'none']:
        return None

    normalized = normalizar_request_id(linked_request_id)
    return None if normalized == request_id else normalized


def limpiar_valor(value):
    if pd.isna(value) or value is None:
        return None
    return str(value).strip()
