from django.shortcuts import render, redirect
from django.http import HttpResponse
from django.contrib import messages
from django.db.models import Q, Count
from django.utils import timezone
from django.core.mail import send_mail
from django.conf import settings
from django.core.validators import validate_email
from django.core.exceptions import ValidationError
import requests
import pandas as pd
import re
import threading
from .models import Ticket
from collections import defaultdict

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
    nombre = re.sub(r'\s+(Australia|Singapore|New Zealand|Colombia|Philippines|Hong Kong|Poland|Lithuania|Latvia|Finland|Belgium|Greece|Romania|Bulgaria|Estonia|Barbados|Panama|Chile|Peru|Bolivia|Indonesia|Uruguay|Guam|North Macedonia)\s*$', '', nombre, flags=re.IGNORECASE)
    return nombre.strip()


def es_nz_o_australia(subject):
    return bool(re.search(r'\b(New Zealand|Australia|NZ)\b', subject, re.IGNORECASE))


def calcular_prioridad(padre, dias_abierto, total_hijos, hijos_pendientes):
    tipo_jml = 'Otro'
    if 'Joiner' in padre.subject:
        tipo_jml = 'Joiner'
    elif 'Mover' in padre.subject:
        tipo_jml = 'Mover'
    elif 'Leaver' in padre.subject:
        tipo_jml = 'Leaver'

    es_nz_au = es_nz_o_australia(padre.subject)

    # Si hay hijos y todos están cerrados
    if total_hijos > 0 and hijos_pendientes == 0:
        return {
            'tipo_jml': tipo_jml,
            'tipo_alerta': 'cerrar_manual',
            'severidad': 'cerrar',
            'dias_limite': None,
            'mensaje': 'Todos los hijos cerrados - Cerrar padre manualmente'
        }

    if total_hijos == 0:
        return {
            'tipo_jml': tipo_jml,
            'tipo_alerta': 'sin_hijos',
            'severidad': 'media',
            'dias_limite': None,
            'mensaje': 'Sin tareas asociadas'
        }

    if hijos_pendientes > 0:
        if tipo_jml == 'Leaver':
            if es_nz_au:
                if dias_abierto > 3:
                    return {
                        'tipo_jml': tipo_jml, 'tipo_alerta': 'pendiente', 'severidad': 'alta',
                        'dias_limite': 3, 'mensaje': f'Leaver NZ/AU abierto {dias_abierto} días (límite: 3)'
                    }
            else:
                if dias_abierto >= 1:
                    return {
                        'tipo_jml': tipo_jml, 'tipo_alerta': 'pendiente', 'severidad': 'critica',
                        'dias_limite': 1, 'mensaje': f'Leaver abierto {dias_abierto} días - CRITICO! Max 24h'
                    }
        
        elif tipo_jml == 'Joiner' and dias_abierto > 10:
            return {
                'tipo_jml': tipo_jml, 'tipo_alerta': 'pendiente', 'severidad': 'alta',
                'dias_limite': 10, 'mensaje': f'Joiner abierto {dias_abierto} días (límite: 10)'
            }
            
        elif tipo_jml == 'Mover' and dias_abierto > 10:
            return {
                'tipo_jml': tipo_jml, 'tipo_alerta': 'pendiente', 'severidad': 'media',
                'dias_limite': 10, 'mensaje': f'Mover abierto {dias_abierto} días (límite: 10)'
            }

        return {
            'tipo_jml': tipo_jml,
            'tipo_alerta': 'pendiente',
            'severidad': 'baja',
            'dias_limite': None,
            'mensaje': f'{hijos_pendientes} tareas pendientes'
        }

    return None


def obtener_alertas_padre_listos_para_cerrar():
    hoy = timezone.now().date()
    estados_cerrados = ['closed', 'resolved', 'cerrado', 'completed', 'cancelled', 'cancelado', 'cierre manual']
    estados_busqueda = estados_cerrados + [s.capitalize() for s in estados_cerrados] + [s.upper() for s in estados_cerrados]
    
    # Padres abiertos
    padres_abiertos = Ticket.objects.filter(
        Q(linked_request_id__isnull=True) | Q(linked_request_id='')
    ).exclude(request_status__in=estados_busqueda)
    
    # Obtener IDs de padres con hijos abiertos
    hijos_abiertos = Ticket.objects.exclude(
        Q(linked_request_id__isnull=True) | Q(linked_request_id='')
    ).exclude(request_status__in=estados_busqueda)
    
    # Limpiamos los IDs para el match
    padres_con_hijos_abiertos = set(str(lid).strip() for lid in hijos_abiertos.values_list('linked_request_id', flat=True) if lid)
    
    # Padres con al menos un hijo
    todos_los_hijos = Ticket.objects.exclude(
        Q(linked_request_id__isnull=True) | Q(linked_request_id='')
    )
    padres_con_hijos = set(str(lid).strip() for lid in todos_los_hijos.values_list('linked_request_id', flat=True) if lid)
    
    # Padres listos = tienen hijos pero ninguno abierto
    padres_listos_ids = padres_con_hijos - padres_con_hijos_abiertos
    padres_listos = padres_abiertos.filter(request_id__in=padres_listos_ids)
    
    # Conteo de hijos cerrados por padre
    conteos = Ticket.objects.filter(
        linked_request_id__in=padres_listos_ids,
        request_status__in=estados_busqueda
    ).values('linked_request_id').annotate(total=Count('id'))
    
    hijos_map = {str(item['linked_request_id']).strip(): item['total'] for item in conteos}
    
    cerrar_manual_resto = []
    cerrar_manual_nz_au = []
    
    for padre in padres_listos:
        pid = str(padre.request_id).strip()
        hijos_cerrados_count = hijos_map.get(pid, 0)
        
        dias_abierto = 0
        if padre.created_time:
            fecha_creacion = padre.created_time.date() if hasattr(padre.created_time, 'date') else padre.created_time
            dias_abierto = (hoy - fecha_creacion).days
        
        region = 'nz_au' if es_nz_o_australia(padre.subject) else 'resto'
        tipo_value = 'Joiner' if 'Joiner' in padre.subject else ('Mover' if 'Mover' in padre.subject else 'Leaver')
        
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


def enviar_correo_tickets_cerrar(destinatario_email=None):
    print("--- Iniciando envio de correo ---")
    
    if not destinatario_email:
        destinatario_email = settings.DEFAULT_FROM_EMAIL
    
    api_key = getattr(settings, 'BREVO_API_KEY', None) or settings.EMAIL_HOST_PASSWORD
    
    if not api_key:
        return False, 'Falta la API Key de Brevo.'
    
    try:
        cerrar_manual_resto, cerrar_manual_nz_au = obtener_alertas_padre_listos_para_cerrar()
        tickets_cerrar_full = cerrar_manual_resto + cerrar_manual_nz_au
        
        limite = 250
        tickets_cerrar = tickets_cerrar_full[:limite]
        
        html_content = f"""
        <html>
        <head><meta charset="utf-8">
        <style>
        body {{ font-family: Arial, sans-serif; }}
        .container {{ max-width: 800px; margin: 0 auto; background: #fff; padding: 20px; }}
        .header {{ background: #0d1b2a; color: #fff; padding: 16px; }}
        .stat-box {{ background: #f0f0f0; padding: 12px; text-align: center; }}
        .stat-number {{ font-size: 24px; font-weight: bold; }}
        table.data-table {{ width: 100%; border-collapse: collapse; }}
        th, td {{ padding: 10px; text-align: left; border-bottom: 1px solid #ddd; }}
        th {{ background: #f0f0f0; }}
        .badge-joiner {{ background: #e6f9f0; color: #10b981; }}
        .badge-mover {{ background: #fff7e6; color: #f59e0b; }}
        .badge-leaver {{ background: #fde8e8; color: #ef4444; }}
        </style>
        </head>
        <body>
        <div class="container">
        <div class="header"><h1>Reporte de Tickets Listos para Cerrar</h1></div>
        <div class="stat-box"><div class="stat-number">{len(tickets_cerrar_full)}</div><div>Listos para cerrar</div></div>
        <table class="data-table">
        <thead><tr><th>ID</th><th>Nombre</th><th>Tipo</th><th>Dias</th><th>Hijos</th></tr></thead>
        <tbody>
        """
        for ticket in tickets_cerrar:
            tipo_value = ticket.get('tipo', 'Leaver')
            html_content += f"""
            <tr>
            <td><strong>{ticket['request_id']}</strong></td>
            <td>{ticket['nombre']}</td>
            <td><span class="badge-{tipo_value.lower()}">{tipo_value}</span></td>
            <td>{ticket['dias_abierto']}</td>
            <td>{ticket['hijos_cerrados_count']}</td>
            </tr>
            """
        
        html_content += f"""
        </tbody>
        </table>
        <div class="footer"><p>Generado: {timezone.now().strftime('%d/%m/%Y %H:%M:%S')}</p></div>
        </div>
        </body>
        </html>
        """
        
        destinatarios = parse_destinatarios_email(destinatario_email)
        if not destinatarios:
            return False, 'No se proporcionó ningún correo válido.'
        
        url = "https://api.brevo.com/v3/smtp/email"
        headers = {
            "accept": "application/json",
            "api-key": api_key,
            "content-type": "application/json"
        }
        
        to_list = [{"email": email} for email in destinatarios]
        data = {
            "sender": {"email": settings.DEFAULT_FROM_EMAIL, "name": "JML Dashboard"},
            "to": to_list,
            "subject": f"JML Dashboard - {len(tickets_cerrar_full)} tickets listos para cerrar",
            "htmlContent": html_content
        }
        
        response = requests.post(url, json=data, headers=headers, timeout=60)
        
        if response.status_code in [200, 201, 202]:
            return True, 'Reporte enviado exitosamente'
        else:
            return False, f"Error API: {response.text[:100]}"
            
    except Exception as e:
        return False, str(e)


def upload_csv(request):
    if request.method == 'POST' and request.FILES.get('csv_file'):
        csv_file = request.FILES['csv_file']
        
        # 1. Limpieza rápida si se solicita
        if request.POST.get('limpiar_bd') == '1':
            Ticket.objects.all().delete()
        
        try:
            # Detectar encabezado rápidamente
            preview = pd.read_csv(csv_file, nrows=10, header=None)
            csv_file.seek(0)
            header_row = 0
            for i, row in preview.iterrows():
                row_str = str(row.values).lower()
                if 'requestid' in row_str or 'subject' in row_str:
                    header_row = i
                    break
            
            # Usamos un chunksize más pequeño (1000) para no saturar la RAM de Render
            chunks = pd.read_csv(
                csv_file,
                skiprows=header_row,
                chunksize=1000,
                dtype=str, # Leemos todo como string primero para velocidad
                low_memory=False,
            )
        except Exception as e:
            return HttpResponse(f"Error al abrir CSV: {e}", status=400)
        
        total_creados = 0
        try:
            from django.db import transaction
            
            for chunk in chunks:
                # Normalización ultra-rápida de columnas
                chunk.columns = [c.strip().lower().replace(' ', '_').replace('-', '_') for c in chunk.columns]
                
                # Mapeo de columnas detectadas
                col_id = 'requestid' if 'requestid' in chunk.columns else ('request_id' if 'request_id' in chunk.columns else None)
                col_sub = 'subject' if 'subject' in chunk.columns else None
                col_status = 'request_status' if 'request_status' in chunk.columns else ('status' if 'status' in chunk.columns else None)
                col_linked = 'linked_request_id' if 'linked_request_id' in chunk.columns else ('linked_id' if 'linked_id' in chunk.columns else None)
                
                if not col_id or not col_sub:
                    continue

                # Procesamiento vectorizado de fechas (MUCHO más rápido que hacerlo en el loop)
                date_cols = ['created_time', 'last_updated_time', 'resolved_time', 'created_at', 'last_updated', 'resolved_at']
                for dc in date_cols:
                    actual_col = next((c for c in chunk.columns if c == dc), None)
                    if actual_col:
                        chunk[actual_col] = pd.to_datetime(chunk[actual_col], errors='coerce').dt.date
                
                tickets_to_create = []
                # El loop ahora solo crea objetos, no procesa datos pesados
                for row in chunk.itertuples(index=False):
                    rid = str(getattr(row, col_id, '')).strip()
                    if not rid or rid.lower() in ['nan', 'requestid', '']:
                        continue
                        
                    sub = str(getattr(row, col_sub, '')).strip()
                    if not sub:
                        continue
                        
                    # Extraer datos con defaults
                    status = str(getattr(row, col_status, 'Open')).strip()
                    
                    lid = getattr(row, col_linked, None)
                    if pd.isna(lid) or str(lid).lower() in ['nan', '', 'none']:
                        lid = None
                    else:
                        lid = str(lid).strip()
                        if lid == rid: lid = None # Evitar auto-vinculación
                    
                    tickets_to_create.append(Ticket(
                        request_id=rid,
                        subject=sub,
                        request_status=status,
                        technician=str(getattr(row, 'technician', '')).strip() if pd.notna(getattr(row, 'technician', None)) else None,
                        created_time=getattr(row, 'created_time', getattr(row, 'created_at', None)),
                        last_updated=getattr(row, 'last_updated_time', getattr(row, 'last_updated', None)),
                        resolved_time=getattr(row, 'resolved_time', getattr(row, 'resolved_at', None)),
                        linked_request_id=lid,
                        requester=str(getattr(row, 'requester', '')).strip() if pd.notna(getattr(row, 'requester', None)) else None,
                    ))
                
                if tickets_to_create:
                    with transaction.atomic():
                        Ticket.objects.bulk_create(tickets_to_create, ignore_conflicts=True)
                    total_creados += len(tickets_to_create)
                    
        except Exception as e:
            print(f"Error procesando chunks: {e}")
            return HttpResponse(f"Error procesando datos: {e}", status=500)
        
        messages.success(request, f'{total_creados} tickets cargados correctamente.')
        return redirect('alertas')
    
    return render(request, 'tickets/upload.html')


def enviar_correo_endpoint(request):
    if request.method == 'POST':
        destinatario = request.POST.get('email_destino', '').strip()
        if not destinatario:
            messages.error(request, 'Debes ingresar un email destino.')
        else:
            thread = threading.Thread(target=enviar_correo_tickets_cerrar, args=(destinatario,))
            thread.start()
            messages.success(request, f'Procesando envio a {destinatario}.')
    return redirect('alertas')


def alertas(request):
    try:
        total_tickets = Ticket.objects.count()
        print(f"--- Dashboard Alertas: {total_tickets} tickets en total ---")
        
        if total_tickets == 0:
            return render(request, 'tickets/alertas.html', {
                'todas_las_alertas': [],
                'total_tickets': 0,
                'total_padres': 0,
                'joiners': 0, 'movers': 0, 'leavers': 0, 'total_cerrar': 0
            })

        # Estadísticas robustas (case-insensitive para el subject)
        joiners = Ticket.objects.filter(subject__icontains='Joiner').count()
        movers = Ticket.objects.filter(subject__icontains='Mover').count()
        leavers = Ticket.objects.filter(subject__icontains='Leaver').count()
        
        # Estados cerrados (Normalizados y ampliados)
        estados_base = ['closed', 'resolved', 'cerrado', 'completed', 'cancelled', 'cancelado', 'cierre manual']
        estados_busqueda = []
        for s in estados_base:
            estados_busqueda.extend([s, s.capitalize(), s.upper()])
        
        # 1. Obtenemos padres abiertos
        # Un padre es aquel que NO tiene linked_request_id
        padres_qs = Ticket.objects.filter(
            Q(linked_request_id__isnull=True) | Q(linked_request_id='') | Q(linked_request_id='None') | Q(linked_request_id='nan')
        ).exclude(request_status__in=estados_busqueda)
        
        print(f"Padres abiertos detectados: {padres_qs.count()}")
        
        # 2. Obtenemos TODOS los hijos para mapear correctamente
        # Traemos todos los que TENGAN linked_request_id
        hijos_qs = Ticket.objects.exclude(
            Q(linked_request_id__isnull=True) | Q(linked_request_id='') | Q(linked_request_id='None') | Q(linked_request_id='nan')
        )
        
        hijos_por_padre = defaultdict(list)
        for hijo in hijos_qs:
            lid = str(hijo.linked_request_id).strip()
            # EVITAR que un ticket sea hijo de sí mismo (esto rompía la lógica de cierre)
            if lid != str(hijo.request_id).strip():
                hijos_por_padre[lid].append(hijo)
        
        hoy = timezone.now().date()
        
        alertas_nz_au = []
        alertas_resto = []
        cerrar_manual_nz_au = []
        cerrar_manual_resto = []
        
        for padre in padres_qs:
            pid = str(padre.request_id).strip()
            todos_hijos = hijos_por_padre.get(pid, [])
            
            # Filtramos hijos abiertos/cerrados usando la misma lógica robusta
            hijos_abiertos = []
            for h in todos_hijos:
                st = str(h.request_status or '').strip().lower()
                if st not in estados_base:
                    hijos_abiertos.append(h)
            
            hijos_cerrados_count = len(todos_hijos) - len(hijos_abiertos)
            
            # Cálculo de días abierto
            dias_abierto = 0
            if padre.created_time:
                # Manejo seguro de DateTime vs Date
                fecha_p = padre.created_time.date() if hasattr(padre.created_time, 'date') else padre.created_time
                dias_abierto = (hoy - fecha_p).days
            
            region = 'nz_au' if es_nz_o_australia(padre.subject) else 'resto'
            
            # Calculamos prioridad
            prioridad = calcular_prioridad(padre, dias_abierto, len(todos_hijos), len(hijos_abiertos))
            
            if prioridad:
                alerta = {
                    'padre': padre,
                    'request_id': padre.request_id,
                    'nombre': extraer_nombre(padre.subject),
                    'subject_completo': padre.subject,
                    'tipo_alerta': prioridad['tipo_alerta'],
                    'severidad': prioridad['severidad'],
                    'dias_abierto': dias_abierto,
                    'total_hijos': len(todos_hijos),
                    'hijos_pendientes': len(hijos_abiertos),
                    'hijos': hijos_abiertos[:10], # Solo mostramos los primeros 10 abiertos
                    'hijos_cerrados_count': hijos_cerrados_count,
                    'tipo_jml': prioridad['tipo_jml'],
                    'mensaje': prioridad['mensaje'],
                    'dias_limite': prioridad['dias_limite'],
                    'es_nz_au': region == 'nz_au',
                    'region': region,
                }
                
                # Clasificación por tipo y región
                if prioridad['tipo_alerta'] == 'cerrar_manual':
                    if region == 'nz_au': cerrar_manual_nz_au.append(alerta)
                    else: cerrar_manual_resto.append(alerta)
                else:
                    if region == 'nz_au': alertas_nz_au.append(alerta)
                    else: alertas_resto.append(alerta)
        
        # Ordenamiento final
        sev_map = {'critica': 0, 'alta': 1, 'media': 2, 'baja': 3, 'cerrar': 4}
        alertas_nz_au.sort(key=lambda x: (sev_map.get(x['severidad'], 4), -x['dias_abierto']))
        alertas_resto.sort(key=lambda x: (sev_map.get(x['severidad'], 4), -x['dias_abierto']))
        
        todas_las_alertas = alertas_resto + alertas_nz_au + cerrar_manual_resto + cerrar_manual_nz_au
        
        print(f"Total alertas generadas: {len(todas_las_alertas)}")
        
        context = {
            'todas_las_alertas': todas_las_alertas,
            'alertas_resto': alertas_resto,
            'alertas_nz_au': alertas_nz_au,
            'cerrar_manual_resto': cerrar_manual_resto,
            'total_tickets': total_tickets,
            'total_padres': padres_qs.count(),
            'joiners': joiners,
            'movers': movers,
            'leavers': leavers,
            'total_cerrar': len(cerrar_manual_resto) + len(cerrar_manual_nz_au),
        }
        
        return render(request, 'tickets/alertas.html', context)
    except Exception as e:
        import traceback
        print(f"ERROR EN ALERTAS: {str(e)}")
        print(traceback.format_exc())
        return HttpResponse(f"Error en el servidor: {e}", status=500)