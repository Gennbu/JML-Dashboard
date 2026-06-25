from collections import defaultdict

from django.db.models import Count, Q
from django.utils import timezone

from ..constants import CLOSED_SEARCH_STATUSES, CLOSED_STATUSES, CLOSED_STATUS_SET
from ..models import Ticket
from ..utils import (
    es_hardware_leaver_subject,
    es_nz_o_australia,
    extraer_nombre,
    normalizar_request_id,
)


def calcular_prioridad(padre, dias_abierto, total_hijos, hijos_pendientes):
    tipo_jml = obtener_tipo_jml(padre.subject)
    es_nz_au = es_nz_o_australia(padre.subject)

    if total_hijos > 0 and hijos_pendientes == 0:
        return {
            'tipo_jml': tipo_jml,
            'tipo_alerta': 'cerrar_manual',
            'severidad': 'cerrar',
            'dias_limite': None,
            'mensaje': 'Todos los hijos cerrados - Cerrar padre manualmente',
        }

    if total_hijos == 0:
        return {
            'tipo_jml': tipo_jml,
            'tipo_alerta': 'sin_hijos',
            'severidad': 'media',
            'dias_limite': None,
            'mensaje': 'Sin tareas asociadas',
        }

    if hijos_pendientes > 0:
        if tipo_jml == 'Leaver':
            if es_nz_au and dias_abierto > 3:
                return {
                    'tipo_jml': tipo_jml,
                    'tipo_alerta': 'pendiente',
                    'severidad': 'alta',
                    'dias_limite': 3,
                    'mensaje': f'Leaver NZ/AU abierto {dias_abierto} días (límite: 3)',
                }

            if not es_nz_au and dias_abierto >= 1:
                return {
                    'tipo_jml': tipo_jml,
                    'tipo_alerta': 'pendiente',
                    'severidad': 'critica',
                    'dias_limite': 1,
                    'mensaje': f'Leaver abierto {dias_abierto} días - CRITICO! Max 24h',
                }

        elif tipo_jml == 'Joiner' and dias_abierto > 10:
            return {
                'tipo_jml': tipo_jml,
                'tipo_alerta': 'pendiente',
                'severidad': 'alta',
                'dias_limite': 10,
                'mensaje': f'Joiner abierto {dias_abierto} días (límite: 10)',
            }

        elif tipo_jml == 'Mover' and dias_abierto > 10:
            return {
                'tipo_jml': tipo_jml,
                'tipo_alerta': 'pendiente',
                'severidad': 'media',
                'dias_limite': 10,
                'mensaje': f'Mover abierto {dias_abierto} días (límite: 10)',
            }

        return {
            'tipo_jml': tipo_jml,
            'tipo_alerta': 'pendiente',
            'severidad': 'baja',
            'dias_limite': None,
            'mensaje': f'{hijos_pendientes} tareas pendientes',
        }

    return None


def obtener_alertas_padre_listos_para_cerrar():
    hoy = timezone.now().date()

    padres_abiertos = Ticket.objects.filter(
        Q(linked_request_id__isnull=True) | Q(linked_request_id='')
    ).exclude(request_status__in=CLOSED_SEARCH_STATUSES)

    hijos_abiertos = Ticket.objects.exclude(
        Q(linked_request_id__isnull=True) | Q(linked_request_id='')
    ).exclude(request_status__in=CLOSED_SEARCH_STATUSES)

    padres_con_hijos_abiertos = {
        normalizar_request_id(linked_id)
        for linked_id in hijos_abiertos.values_list('linked_request_id', flat=True)
        if normalizar_request_id(linked_id)
    }

    todos_los_hijos = Ticket.objects.exclude(
        Q(linked_request_id__isnull=True) | Q(linked_request_id='')
    )
    padres_con_hijos = {
        normalizar_request_id(linked_id)
        for linked_id in todos_los_hijos.values_list('linked_request_id', flat=True)
        if normalizar_request_id(linked_id)
    }

    padres_listos_ids = padres_con_hijos - padres_con_hijos_abiertos
    padres_listos = [
        padre for padre in padres_abiertos if normalizar_request_id(padre.request_id) in padres_listos_ids
    ]

    conteos = (
        Ticket.objects.filter(request_status__in=CLOSED_SEARCH_STATUSES)
        .exclude(Q(linked_request_id__isnull=True) | Q(linked_request_id=''))
        .values('linked_request_id')
        .annotate(total=Count('id'))
    )

    hijos_map = {
        normalizar_request_id(item['linked_request_id']): item['total']
        for item in conteos
        if normalizar_request_id(item['linked_request_id']) in padres_listos_ids
    }

    cerrar_manual_resto = []
    cerrar_manual_nz_au = []

    for padre in padres_listos:
        hijos_cerrados_count = hijos_map.get(normalizar_request_id(padre.request_id), 0)
        dias_abierto = calcular_dias_abierto(padre, hoy)
        region = 'nz_au' if es_nz_o_australia(padre.subject) else 'resto'
        tipo_value = obtener_tipo_jml(padre.subject)

        alerta = {
            'padre': padre,
            'request_id': padre.request_id,
            'nombre': extraer_nombre(padre.subject),
            'subject_completo': padre.subject,
            'tipo_alerta': 'cerrar_manual',
            'severidad': 'cerrar',
            'dias_abierto': dias_abierto,
            'total_hijos': hijos_cerrados_count,
            'hijos_pendientes': 0,
            'hijos': [],
            'hijos_cerrados_count': hijos_cerrados_count,
            'tipo_jml': tipo_value,
            'tipo': tipo_value,
            'mensaje': 'Todos los hijos cerrados - Listo para cierre manual',
            'dias_limite': None,
            'es_nz_au': region == 'nz_au',
            'region': region,
        }

        if region == 'nz_au':
            cerrar_manual_nz_au.append(alerta)
        else:
            cerrar_manual_resto.append(alerta)

    return cerrar_manual_resto, cerrar_manual_nz_au


def build_empty_alertas_context():
    return {
        'todas_las_alertas': [],
        'alertas_resto': [],
        'alertas_nz_au': [],
        'cerrar_manual_resto': [],
        'cerrar_manual_nz_au': [],
        'total_tickets': 0,
        'total_padres': 0,
        'joiners': 0,
        'movers': 0,
        'leavers': 0,
        'total_cerrar': 0,
        'alertas_hardware_leaver': [],
        'alertas_local_apps_nz_au': [],
        'alertas_local_apps': [],
        'alertas_sin_padre': [],
        'alertas_hardware_leaver_count': 0,
        'alertas_local_apps_count': 0,
        'alertas_sin_padre_count': 0,
        'alertas_resto_count': 0,
        'alertas_nz_au_count': 0,
    }


def build_alertas_context():
    total_tickets = Ticket.objects.count()
    print(f"--- Dashboard Alertas: {total_tickets} tickets en total ---")

    if total_tickets == 0:
        return build_empty_alertas_context()

    joiners = Ticket.objects.filter(subject__icontains='Joiner').count()
    movers = Ticket.objects.filter(subject__icontains='Mover').count()
    leavers = Ticket.objects.filter(subject__icontains='Leaver').count()

    padres_qs = Ticket.objects.filter(
        Q(linked_request_id__isnull=True)
        | Q(linked_request_id='')
        | Q(linked_request_id='None')
        | Q(linked_request_id='nan')
    ).exclude(request_status__in=CLOSED_SEARCH_STATUSES)

    hijos_qs = Ticket.objects.exclude(
        Q(linked_request_id__isnull=True)
        | Q(linked_request_id='')
        | Q(linked_request_id='None')
        | Q(linked_request_id='nan')
    )

    hijos_por_padre = defaultdict(list)
    for hijo in hijos_qs:
        linked_id = normalizar_request_id(hijo.linked_request_id)
        if linked_id and linked_id != normalizar_request_id(hijo.request_id):
            hijos_por_padre[linked_id].append(hijo)

    todos_los_request_ids = {
        normalizar_request_id(request_id)
        for request_id in Ticket.objects.values_list('request_id', flat=True)
        if normalizar_request_id(request_id)
    }
    hoy = timezone.now().date()

    alertas_nz_au = []
    alertas_resto = []
    cerrar_manual_resto = []
    cerrar_manual_nz_au = []
    alertas_hardware_leaver = []
    alertas_local_apps_nz_au = []
    alertas_sin_padre = []

    for hijo in hijos_qs:
        linked_id_normalizado = normalizar_request_id(hijo.linked_request_id)
        if not linked_id_normalizado or linked_id_normalizado in todos_los_request_ids:
            continue

        alerta_huerfana = {
            'padre': hijo,
            'request_id': hijo.request_id,
            'nombre': extraer_nombre(hijo.subject),
            'subject_completo': hijo.subject,
            'tipo_alerta': 'sin_padre',
            'severidad': 'media',
            'dias_abierto': calcular_dias_abierto(hijo, hoy),
            'total_hijos': 0,
            'hijos_pendientes': 0,
            'hijos': [],
            'hijos_cerrados_count': 0,
            'tipo_jml': 'Leaver' if 'leaver' in str(hijo.subject).lower() else 'Otro',
            'mensaje': 'Ticket huerfano - sin padre linkeado',
            'dias_limite': None,
            'es_nz_au': es_nz_o_australia(hijo.subject),
            'region': 'nz_au' if es_nz_o_australia(hijo.subject) else 'resto',
        }

        if es_hardware_leaver_subject(hijo.subject):
            alerta_huerfana['tipo_alerta'] = 'hardware_leaver'
            alerta_huerfana['mensaje'] = 'Hardware Leaver - ticket no anclado por logica de negocio'
            alertas_hardware_leaver.append(alerta_huerfana)
        else:
            alertas_sin_padre.append(alerta_huerfana)

    for padre in padres_qs:
        todos_hijos = hijos_por_padre.get(normalizar_request_id(padre.request_id), [])
        hijos_abiertos = [
            hijo
            for hijo in todos_hijos
            if str(hijo.request_status or '').strip().lower() not in CLOSED_STATUS_SET
        ]

        subject_lower = padre.subject.lower()
        es_hardware_leaver = es_hardware_leaver_subject(padre.subject)
        es_local_apps_nz_au = 'local apps' in subject_lower and es_nz_o_australia(padre.subject)
        es_nz_au = es_nz_o_australia(padre.subject)

        prioridad = calcular_prioridad(
            padre=padre,
            dias_abierto=calcular_dias_abierto(padre, hoy),
            total_hijos=len(todos_hijos),
            hijos_pendientes=len(hijos_abiertos),
        )

        if not prioridad:
            continue

        alerta = {
            'padre': padre,
            'request_id': padre.request_id,
            'nombre': extraer_nombre(padre.subject),
            'subject_completo': padre.subject,
            'tipo_alerta': prioridad['tipo_alerta'],
            'severidad': prioridad['severidad'],
            'dias_abierto': calcular_dias_abierto(padre, hoy),
            'total_hijos': len(todos_hijos),
            'hijos_pendientes': len(hijos_abiertos),
            'hijos': hijos_abiertos[:10],
            'hijos_cerrados_count': len(todos_hijos) - len(hijos_abiertos),
            'tipo_jml': prioridad['tipo_jml'],
            'mensaje': prioridad['mensaje'],
            'dias_limite': prioridad['dias_limite'],
            'es_nz_au': es_nz_au,
            'region': 'nz_au' if es_nz_au else 'resto',
        }

        if prioridad['tipo_alerta'] == 'cerrar_manual':
            if alerta['region'] == 'nz_au':
                cerrar_manual_nz_au.append(alerta)
            else:
                cerrar_manual_resto.append(alerta)
        elif es_hardware_leaver:
            alertas_hardware_leaver.append(alerta)
        elif es_local_apps_nz_au:
            alertas_local_apps_nz_au.append(alerta)
        elif alerta['region'] == 'nz_au':
            alertas_nz_au.append(alerta)
        else:
            alertas_resto.append(alerta)

    sev_map = {'critica': 0, 'alta': 1, 'media': 2, 'baja': 3, 'cerrar': 4}
    sort_alertas = lambda items: items.sort(key=lambda item: (sev_map.get(item['severidad'], 4), -item['dias_abierto']))

    sort_alertas(alertas_nz_au)
    sort_alertas(alertas_resto)
    sort_alertas(alertas_hardware_leaver)
    sort_alertas(alertas_local_apps_nz_au)
    sort_alertas(alertas_sin_padre)

    return {
        'todas_las_alertas': alertas_resto + alertas_nz_au + cerrar_manual_resto + cerrar_manual_nz_au,
        'alertas_resto': alertas_resto,
        'alertas_nz_au': alertas_nz_au,
        'cerrar_manual_resto': cerrar_manual_resto,
        'cerrar_manual_nz_au': cerrar_manual_nz_au,
        'total_tickets': total_tickets,
        'total_padres': padres_qs.count(),
        'joiners': joiners,
        'movers': movers,
        'leavers': leavers,
        'total_cerrar': len(cerrar_manual_resto) + len(cerrar_manual_nz_au),
        'alertas_hardware_leaver': alertas_hardware_leaver,
        'alertas_local_apps_nz_au': alertas_local_apps_nz_au,
        'alertas_local_apps': alertas_local_apps_nz_au,
        'alertas_sin_padre': alertas_sin_padre,
        'alertas_hardware_leaver_count': len(alertas_hardware_leaver),
        'alertas_local_apps_count': len(alertas_local_apps_nz_au),
        'alertas_sin_padre_count': len(alertas_sin_padre),
        'alertas_resto_count': len(alertas_resto),
        'alertas_nz_au_count': len(alertas_nz_au),
    }


def calcular_dias_abierto(ticket, hoy):
    if not ticket.created_time:
        return 0

    fecha_creacion = ticket.created_time.date() if hasattr(ticket.created_time, 'date') else ticket.created_time
    return (hoy - fecha_creacion).days


def obtener_tipo_jml(subject):
    if 'Joiner' in subject:
        return 'Joiner'
    if 'Mover' in subject:
        return 'Mover'
    if 'Leaver' in subject:
        return 'Leaver'
    return 'Otro'
