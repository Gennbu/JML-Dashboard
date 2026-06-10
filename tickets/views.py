from django.shortcuts import render, redirect
from django.http import HttpResponse
from django.contrib import messages
from django.db.models import Q
from django.utils import timezone
from django.core.mail import send_mail
from django.conf import settings
from django.core.validators import validate_email
from django.core.exceptions import ValidationError
from django.db import connection
import pandas as pd
import re
from .models import Ticket
from collections import defaultdict
from datetime import date

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
    subject_lower = padre.subject.lower()
    if 'joiner' in subject_lower:
        tipo_jml = 'Joiner'
    elif 'mover' in subject_lower:
        tipo_jml = 'Mover'
    elif 'leaver' in subject_lower:
        tipo_jml = 'Leaver'

    es_nz_au = es_nz_o_australia(padre.subject)

    # REGLA ORO: Si hay hijos y todos están cerrados, severidad CERRAR
    if total_hijos > 0 and hijos_pendientes == 0:
        return {
            'tipo_jml': tipo_jml,
            'tipo_alerta': 'cerrar_manual',
            'severidad': 'cerrar',
            'dias_limite': None,
            'mensaje': 'Todos los hijos cerrados - Listo para cierre manual'
        }

    # Si no hay hijos, es una alerta de "Sin tareas"
    if total_hijos == 0:
        return {
            'tipo_jml': tipo_jml,
            'tipo_alerta': 'sin_hijos',
            'severidad': 'media',
            'dias_limite': None,
            'mensaje': 'Ticket padre sin tareas hijas asociadas'
        }

    # Si hay hijos pendientes, aplicamos reglas de tiempo
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
                        'dias_limite': 1, 'mensaje': f'Leaver abierto {dias_abierto} días - ¡CRÍTICO! Max 24h'
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
            'mensaje': f'{hijos_pendientes} tareas pendientes de cerrar'
        }

    return None


def obtener_alertas_padre_listos_para_cerrar():
    hoy = timezone.now().date()
    # Definimos estados cerrados de forma estándar
    estados_cerrados = ['closed', 'resolved', 'cerrado', 'completed', 'cancelled', 'cancelado', 'cierre manual']
    
    # 1. Obtener todos los IDs de tickets padre que están abiertos
    padres_abiertos = Ticket.objects.filter(
        Q(linked_request_id__isnull=True) | Q(linked_request_id='')
    ).exclude(
        request_status__in=estados_cerrados
    )
    
    # 2. Obtener todos los hijos que pertenecen a estos padres abiertos
    ids_padres_abiertos = padres_abiertos.values_list('request_id', flat=True)
    hijos_de_padres_abiertos = Ticket.objects.filter(
        linked_request_id__in=ids_padres_abiertos
    )
    
    # Agrupamos hijos por padre para procesar en memoria de forma eficiente
    hijos_por_padre = defaultdict(list)
    for hijo in hijos_de_padres_abiertos:
        hijos_por_padre[hijo.linked_request_id].append(hijo)
    
    cerrar_manual_resto = []
    cerrar_manual_nz_au = []
    
    for padre in padres_abiertos:
        hijos_del_padre = hijos_por_padre.get(padre.request_id, [])
        
        # Un padre está listo para cerrar SI tiene hijos Y todos sus hijos están cerrados
        if not hijos_del_padre:
            continue
            
        hijos_abiertos = [h for h in hijos_del_padre if h.request_status.lower() not in estados_cerrados]
        
        if len(hijos_abiertos) == 0:
            # Todos los hijos están cerrados
            hijos_cerrados_count = len(hijos_del_padre)
            
            dias_abierto = 0
            if padre.created_time:
                dias_abierto = (hoy - padre.created_time).days
            
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
                'mensaje': 'Todos los hijos cerrados - Cerrar padre manualmente',
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
    if not destinatario_email:
        destinatario_email = settings.EMAIL_HOST_USER
    
    # Verificación más robusta de credenciales
    email_user = getattr(settings, 'EMAIL_HOST_USER', None)
    email_pass = getattr(settings, 'EMAIL_HOST_PASSWORD', None)
    
    if not email_user or not email_pass or email_user == 'tu_email@gmail.com' or email_pass == '':
        return False, 'Configuración SMTP incompleta. Por favor, configura GMAIL_EMAIL y GMAIL_PASSWORD en tu archivo .env o variables de entorno.'
    
    try:
        cerrar_manual_resto, cerrar_manual_nz_au = obtener_alertas_padre_listos_para_cerrar()
        tickets_cerrar = cerrar_manual_resto + cerrar_manual_nz_au
        
        html_content = f"""
        <html>
        <head>
        <meta charset="utf-8">
        <style>
        body {{ font-family: Arial, Helvetica, sans-serif; background-color: #f5f5f5; color: #333333; }}
        .container {{ max-width: 800px; margin: 0 auto; background-color: #ffffff; padding: 20px; }}
        .header {{ background-color: #0d1b2a; color: #ffffff; padding: 16px; margin-bottom: 16px; }}
        .header h1 {{ margin: 0; font-size: 20px; font-weight: bold; }}
        .stats {{ width: 100%; margin-bottom: 12px; }}
        .stat-box {{ background-color: #f0f0f0; padding: 12px; text-align: center; }}
        .stat-number {{ font-size: 24px; font-weight: bold; color: #1b263b; }}
        table.data-table {{ width: 100%; border-collapse: collapse; margin-top: 12px; }}
        table.data-table th {{ background-color: #f0f0f0; padding: 10px; text-align: left; font-weight: 600; border-bottom: 2px solid #dddddd; }}
        table.data-table td {{ padding: 10px; border-bottom: 1px solid #eeeeee; }}
        .badge {{ display: inline-block; padding: 4px 10px; border-radius: 20px; font-size: 11px; font-weight: 600; }}
        .badge-joiner {{ background-color: #e6f9f0; color: #10b981; }}
        .badge-mover {{ background-color: #fff7e6; color: #f59e0b; }}
        .badge-leaver {{ background-color: #fde8e8; color: #ef4444; }}
        .footer {{ text-align: center; color: #999999; font-size: 12px; margin-top: 16px; }}
        </style>
        </head>
        <body>
        <div class="container">
        <div class="header"><h1>Reporte de Tickets Listos para Cerrar</h1></div>
        <div class="stat-box"><div class="stat-number">{len(tickets_cerrar)}</div><div>Listos para cerrar</div></div>
        <p style="font-size:12px;color:#666666;margin-top:8px;">Este correo solo incluye tickets padre que tienen todos sus hijos cerrados y estan listos para cierre manual.</p>
        <table class="data-table">
        <thead><tr><th>ID Ticket</th><th>Nombre</th><th>Tipo</th><th>Dias Abierto</th><th>Hijos Cerrados</th></tr></thead>
        <tbody>
        """
        for ticket in tickets_cerrar:
            tipo_value = ticket.get('tipo') or ticket.get('tipo_jml', 'Leaver')
            badge_class = f"badge-{tipo_value.lower()}"
            html_content += f"""
            <tr>
            <td><strong>{ticket['request_id']}</strong></td>
            <td>{ticket['nombre']}</td>
            <td><span class="badge {badge_class}">{tipo_value}</span></td>
            <td>{ticket['dias_abierto']}</td>
            <td>{ticket['hijos_cerrados']}</td>
            </tr>
            """
        
        html_content += f"""
        </tbody>
        </table>
        <div class="footer"><p>Este es un correo automatico generado por JML Dashboard.</p><p>Generado el: {timezone.now().strftime('%d/%m/%Y %H:%M:%S')}</p></div>
        </div>
        </body>
        </html>
        """
        
        destinatarios = parse_destinatarios_email(destinatario_email)
        if not destinatarios:
            return False, 'No se proporciono ningun correo valido.'
        
        send_mail(
            subject=f'JML Dashboard - {len(tickets_cerrar)} tickets listos para cerrar',
            message='Por favor abre este correo en un cliente que soporte HTML.',
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=destinatarios,
            html_message=html_content,
            fail_silently=False,
        )
        return True, None
    except Exception as e:
        return False, str(e)


def upload_csv(request):
    if request.method == 'POST' and request.FILES.get('csv_file'):
        csv_file = request.FILES['csv_file']
        
        if request.POST.get('limpiar_bd') == '1':
            Ticket.objects.all().delete()
        
        try:
            # Intentamos leer primero sin saltar filas para detectar el encabezado
            # Muchas exportaciones de ServiceDesk Plus o herramientas similares tienen metadatos al inicio
            # Si el usuario dice que carga 0, es probable que skiprows=5 se esté saltando los datos reales
            
            # Leemos las primeras 10 filas para ver dónde está el encabezado
            preview = pd.read_csv(csv_file, nrows=10, header=None)
            csv_file.seek(0) # Reset pointer
            
            header_row = 0
            for i, row in preview.iterrows():
                row_str = str(row.values).lower()
                if 'requestid' in row_str or 'subject' in row_str:
                    header_row = i
                    break
            
            print(f"Detectado encabezado en fila: {header_row}")
            
            chunks = pd.read_csv(
                csv_file,
                skiprows=header_row,
                chunksize=2000, # Aumentamos el tamaño del chunk para eficiencia
                dtype={
                    'RequestID': str,
                    'Linked Request ID': str,
                },
                low_memory=False,
            )
        except Exception as e:
            return HttpResponse(f"Error al leer el archivo CSV: {e}", status=400)
        
        def safe_date(valor):
            if pd.isna(valor) or str(valor).strip() in ['Not Assigned', '', 'None', 'nan']:
                return None
            try:
                # Intentamos parsear la fecha de forma más robusta
                return pd.to_datetime(valor, errors='coerce').date()
            except:
                return None
        
        total = 0
        for chunk in chunks:
            # Limpiamos nombres de columnas por si tienen espacios
            chunk.columns = [c.strip() for c in chunk.columns]
            
            # Verificar si las columnas necesarias existen
            required_cols = ['RequestID', 'Subject', 'Request Status']
            missing = [c for c in required_cols if c not in chunk.columns]
            if missing:
                print(f"Error: Faltan columnas {missing} en el chunk")
                continue

            tickets_to_create = []
            for row in chunk.itertuples(index=False):
                # Usamos getattr con el nombre de la columna limpia
                request_id = str(getattr(row, 'RequestID', '')).strip()
                if not request_id or request_id.lower() == 'nan':
                    continue
                
                # Mapeo de campos
                try:
                    subject = str(getattr(row, 'Subject', '')).strip()
                    status = str(getattr(row, 'Request Status', '')).strip()
                    
                    # Evitar procesar filas que parecen ser encabezados repetidos o vacías
                    if request_id.lower() == 'requestid' or not subject:
                        continue

                    linked_id = getattr(row, 'Linked_Request_ID', getattr(row, 'Linked Request ID', None))
                    if pd.notna(linked_id):
                        linked_id = str(linked_id).strip()
                        if linked_id.lower() in ['nan', '', 'none']:
                            linked_id = None
                    else:
                        linked_id = None
                    
                    tickets_to_create.append(Ticket(
                        request_id=request_id,
                        subject=subject,
                        request_status=status,
                        technician=str(getattr(row, 'Technician', '')).strip() if pd.notna(getattr(row, 'Technician', None)) else None,
                        created_time=safe_date(getattr(row, 'Created_Time', getattr(row, 'Created Time', None))),
                        last_updated=safe_date(getattr(row, 'Last_Updated_Time', getattr(row, 'Last Updated Time', None))),
                        resolved_time=safe_date(getattr(row, 'Resolved_Time', getattr(row, 'Resolved Time', None))),
                        linked_request_id=linked_id,
                        requester=str(getattr(row, 'Requester', '')).strip() if pd.notna(getattr(row, 'Requester', None)) else None,
                    ))
                except Exception as row_err:
                    print(f"Error procesando fila {request_id}: {row_err}")
                    continue
            
            if tickets_to_create:
                Ticket.objects.bulk_create(tickets_to_create, ignore_conflicts=True)
                total += len(tickets_to_create)
                print(f"Procesados {total} tickets...")
        
        print(f"Total final de tickets insertados: {total}")
        messages.success(request, f'{total} tickets cargados correctamente.')
        return redirect('alertas')
    
    return render(request, 'tickets/upload.html')

def enviar_correo_endpoint(request):
    if request.method == 'POST':
        destinatario = request.POST.get('email_destino', '').strip()
        if not destinatario:
            messages.error(request, 'Debes ingresar un email destino.')
        else:
            exito, error_msg = enviar_correo_tickets_cerrar(destinatario)
            if exito:
                messages.success(request, f'Correo enviado a {destinatario}')
            else:
                messages.error(request, f'Error: {error_msg}')
    return redirect('alertas')


def alertas(request):
    total_tickets = Ticket.objects.count()
    if total_tickets == 0:
        return render(request, 'tickets/alertas.html', {
            'todas_las_alertas': [],
            'total_tickets': 0,
            'total_padres': 0,
            'joiners': 0, 'movers': 0, 'leavers': 0, 'total_cerrar': 0
        })

    # Optimizamos conteos
    joiners = Ticket.objects.filter(subject__icontains='Joiner').count()
    movers = Ticket.objects.filter(subject__icontains='Mover').count()
    leavers = Ticket.objects.filter(subject__icontains='Leaver').count()
    
    # Estados cerrados estándar
    estados_cerrados = ['closed', 'resolved', 'cerrado', 'completed', 'cancelled', 'cancelado', 'cierre manual']
    
    # Padres abiertos
    padres = Ticket.objects.filter(
        Q(linked_request_id__isnull=True) | Q(linked_request_id='')
    ).exclude(request_status__in=estados_cerrados)
    
    total_padres = padres.count()
    
    # Obtenemos solo los hijos de los padres que están abiertos (para ahorrar memoria)
    ids_padres_abiertos = padres.values_list('request_id', flat=True)
    hijos_relacionados = Ticket.objects.filter(linked_request_id__in=ids_padres_abiertos)
    
    hijos_por_padre = defaultdict(list)
    for hijo in hijos_relacionados:
        hijos_por_padre[hijo.linked_request_id].append(hijo)
    
    hoy = timezone.now().date()
    
    alertas_nz_au = []
    alertas_resto = []
    cerrar_manual_nz_au = []
    cerrar_manual_resto = []
    
    for padre in padres:
        todos_hijos = hijos_por_padre.get(padre.request_id, [])
        
        hijos_abiertos = [h for h in todos_hijos if h.request_status.lower() not in estados_cerrados]
        hijos_cerrados_count = len(todos_hijos) - len(hijos_abiertos)
        
        dias_abierto = 0
        if padre.created_time:
            dias_abierto = (hoy - padre.created_time).days
            
        region = 'nz_au' if es_nz_o_australia(padre.subject) else 'resto'
        
        prioridad = calcular_prioridad(padre, dias_abierto, len(todos_hijos), len(hijos_abiertos))
        
        if prioridad:
            alerta = {
                'padre': padre,
                'nombre': extraer_nombre(padre.subject),
                'subject_completo': padre.subject,
                'tipo_alerta': prioridad['tipo_alerta'],
                'severidad': prioridad['severidad'],
                'dias_abierto': dias_abierto,
                'total_hijos': len(todos_hijos),
                'hijos_pendientes': len(hijos_abiertos),
                'hijos': hijos_abiertos[:10], # Limitamos hijos mostrados para no saturar el HTML
                'hijos_cerrados_count': hijos_cerrados_count,
                'tipo_jml': prioridad['tipo_jml'],
                'mensaje': prioridad['mensaje'],
                'dias_limite': prioridad['dias_limite'],
                'es_nz_au': region == 'nz_au',
                'region': region,
            }
            
            if prioridad['tipo_alerta'] == 'cerrar_manual':
                if region == 'nz_au': cerrar_manual_nz_au.append(alerta)
                else: cerrar_manual_resto.append(alerta)
            else:
                if region == 'nz_au': alertas_nz_au.append(alerta)
                else: alertas_resto.append(alerta)
    
    # Ordenamiento
    sev_map = {'critica': 0, 'alta': 1, 'media': 2, 'baja': 3, 'cerrar': 4}
    alertas_nz_au.sort(key=lambda x: (sev_map.get(x['severidad'], 4), -x['dias_abierto']))
    alertas_resto.sort(key=lambda x: (sev_map.get(x['severidad'], 4), -x['dias_abierto']))
    
    todas_las_alertas = alertas_resto + alertas_nz_au + cerrar_manual_resto + cerrar_manual_nz_au
    
    context = {
        'todas_las_alertas': todas_las_alertas,
        'alertas_resto': alertas_resto,
        'alertas_nz_au': alertas_nz_au,
        'cerrar_manual_resto': cerrar_manual_resto,
        'total_tickets': total_tickets,
        'total_padres': total_padres,
        'joiners': joiners,
        'movers': movers,
        'leavers': leavers,
        'total_cerrar': len(cerrar_manual_resto) + len(cerrar_manual_nz_au),
    }
    
    return render(request, 'tickets/alertas.html', context)