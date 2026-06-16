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
import warnings
from .models import Ticket
from collections import defaultdict

# Silenciar warnings de Pandas que no son críticos
warnings.filterwarnings("ignore", category=UserWarning, module='pandas')

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
    print("--- Iniciando envio de correo (DEBUG COMPLETO) ---")
    
    # 1. Verificar destinos
    if not destinatario_email:
        destinatario_email = settings.DEFAULT_FROM_EMAIL
    print(f"  → Destinatarios recibidos (raw): '{destinatario_email}'")
    
    # 2. Obtener API Key
    api_key = None
    if hasattr(settings, 'BREVO_API_KEY'):
        api_key = settings.BREVO_API_KEY
        print(f"  → Encontrada BREVO_API_KEY en settings")
    
    if not api_key and hasattr(settings, 'EMAIL_HOST_PASSWORD'):
        api_key = settings.EMAIL_HOST_PASSWORD
        print(f"  → Usando EMAIL_HOST_PASSWORD como API Key")
        
    if not api_key:
        print("  → ERROR: NO HAY API KEY!")
        return False, 'Falta la API Key de Brevo.'
    
    print(f"  → API Key (primeros 10): '{api_key[:10] if len(api_key)>=10 else api_key}...'")
    
    # 3. Verificar remitente
    print(f"  → Remitente configurado: '{settings.DEFAULT_FROM_EMAIL}'")
    
    try:
        print("  → Obteniendo alertas de 'Listos para cerrar'...")
        cerrar_manual_resto, cerrar_manual_nz_au = obtener_alertas_padre_listos_para_cerrar()
        tickets_cerrar_full = cerrar_manual_resto + cerrar_manual_nz_au
        print(f"  → Tickets listos para cerrar: {len(tickets_cerrar_full)}")
        
        limite = 250
        tickets_cerrar = tickets_cerrar_full[:limite]
        print(f"  → Mostrando {len(tickets_cerrar)} tickets en el correo")
        
        # 4. Generar HTML
        print("  → Generando HTML del reporte...")
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
        print("  → HTML generado OK")
        
        # 5. Validar destinatarios
        destinatarios = parse_destinatarios_email(destinatario_email)
        print(f"  → Destinatarios validados: {destinatarios}")
        if not destinatarios:
            return False, 'No se proporcionó ningún correo válido.'
        
        # 6. Preparar llamada a API
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
        
        print("  → Enviando POST a API Brevo...")
        print(f"  → URL: {url}")
        print(f"  → Payload sender: {data['sender']}")
        
        response = requests.post(url, json=data, headers=headers, timeout=60)
        
        print(f"  → Respuesta status code: {response.status_code}")
        print(f"  → Respuesta texto: {response.text}")
        
        if response.status_code in [200, 201, 202]:
            print("  → ✅ ENVÍO EXITOSO!")
            return True, 'Reporte enviado exitosamente'
        else:
            print(f"  → ❌ ERROR EN API!")
            return False, f"Error API: {response.text[:200]}"
            
    except Exception as e:
        print(f"  → ❌ EXCEPCIÓN: {str(e)}")
        import traceback
        print(traceback.format_exc())
        return False, f"Error interno: {str(e)}"


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
            
            # Usamos un chunksize aún más pequeño (500) para no saturar con 25k tickets
            chunks = pd.read_csv(
                csv_file,
                skiprows=header_row,
                chunksize=500,
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
        
        print(f"--- Total de tickets hijos: {hijos_qs.count()} ---")
        
        hijos_por_padre = defaultdict(list)
        for hijo in hijos_qs:
            lid = str(hijo.linked_request_id).strip()
            # EVITAR que un ticket sea hijo de sí mismo (esto rompía la lógica de cierre)
            if lid != str(hijo.request_id).strip():
                hijos_por_padre[lid].append(hijo)
                
        print(f"--- Padres que tienen al menos un hijo: {len(hijos_por_padre)} ---")
        
        hoy = timezone.now().date()
        
        alertas_nz_au = []
        alertas_resto = []
        cerrar_manual_nz_au = []
        cerrar_manual_resto = []
        
        # Contadores de debug
        debug_contador_padres_con_hijos = 0
        debug_contador_padres_sin_hijos = 0
        debug_contador_padres_listos_para_cerrar = 0
        
        for idx, padre in enumerate(padres_qs):
            pid = str(padre.request_id).strip()
            todos_hijos = hijos_por_padre.get(pid, [])
            
            if len(todos_hijos) > 0:
                debug_contador_padres_con_hijos += 1
            else:
                debug_contador_padres_sin_hijos += 1
            
            # Filtramos hijos abiertos/cerrados usando la misma lógica robusta
            hijos_abiertos = []
            for h in todos_hijos:
                st = str(h.request_status or '').strip().lower()
                if st not in estados_base:
                    hijos_abiertos.append(h)
            
            # Si es un candidato a cerrar, imprimir detalles
            if len(todos_hijos) > 0 and len(hijos_abiertos) == 0:
                debug_contador_padres_listos_para_cerrar += 1
                # Imprimir solo los primeros 5 para no saturar
                if debug_contador_padres_listos_para_cerrar <= 5:
                    print(f"--- CANDIDATO # {debug_contador_padres_listos_para_cerrar}: {pid} ---")
                    print(f"    Status padre: {padre.request_status}")
                    print(f"    Total hijos: {len(todos_hijos)}")
                    for h_idx, h in enumerate(todos_hijos):
                        st = str(h.request_status or '').strip().lower()
                        print(f"    Hijo {h_idx}: {h.request_id} - Status: '{h.request_status}' (norm: '{st}')")
            
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
        
        print("--- DEBUG TOTALES ---")
        print(f"Padres abiertos: {padres_qs.count()}")
        print(f"Padres abiertos CON hijos: {debug_contador_padres_con_hijos}")
        print(f"Padres abiertos SIN hijos: {debug_contador_padres_sin_hijos}")
        print(f"Padres abiertos listos para cerrar: {debug_contador_padres_listos_para_cerrar}")
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