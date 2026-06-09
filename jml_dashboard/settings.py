from django.shortcuts import render, redirect
from django.http import HttpResponse
from django.contrib import messages
from django.db.models import Q, Count, Case, When, Value, IntegerField
from django.utils import timezone
from django.core.mail import send_mail
from django.conf import settings
from django.core.validators import validate_email
from django.core.exceptions import ValidationError
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


# ========== UTILIDADES ==========

def extraer_nombre(subject):
    nombre = re.sub(r'^(Joiner|Mover|Leaver)\s+Notification\s+', '', subject, flags=re.IGNORECASE)
    nombre = re.sub(r'\s+\d{1,2}-\d{1,2}-\d{4}$', '', nombre)
    nombre = re.sub(r'\s+\d{4}-\d{1,2}-\d{1,2}$', '', nombre)
    nombre = re.sub(r'\s+(Australia|Singapore|New Zealand|Colombia|Philippines|Hong Kong|Poland|Lithuania|Latvia|Finland|Belgium|Greece|Romania|Bulgaria|Estonia|Barbados|Panama|Chile|Peru|Bolivia|Indonesia|Uruguay|Guam|North Macedonia)\s*$', '', nombre, flags=re.IGNORECASE)
    return nombre.strip()


def es_nz_o_australia(subject):
    return bool(re.search(r'\b(New Zealand|Australia|NZ)\b', subject, re.IGNORECASE))


def calcular_prioridad(padre, dias_abierto, total_hijos, hijos_pendientes, resolved_time=None):
    tipo_jml = 'Otro'
    if 'Joiner' in padre.subject:
        tipo_jml = 'Joiner'
    elif 'Mover' in padre.subject:
        tipo_jml = 'Mover'
    elif 'Leaver' in padre.subject:
        tipo_jml = 'Leaver'

    es_nz_au = es_nz_o_australia(padre.subject)

    # Primero: verificar si todos los hijos están cerrados (prioridad máxima para cerrar)
    if total_hijos > 0 and hijos_pendientes == 0:
        return {
            'tipo_jml': tipo_jml,
            'tipo_alerta': 'cerrar_manual',
            'severidad': 'cerrar',
            'dias_limite': None,
            'mensaje': 'Todos los hijos cerrados - Cerrar padre manualmente'
        }

    # Segundo: verificar si hay hijos pendientes
    if hijos_pendientes > 0:
        return {
            'tipo_jml': tipo_jml,
            'tipo_alerta': 'pendiente',
            'severidad': 'baja',
            'dias_limite': None,
            'mensaje': f'{hijos_pendientes} tareas pendientes'
        }

    # Tercero: validar por tipo y días
    if tipo_jml == 'Leaver':
        if es_nz_au:
            if dias_abierto > 3:
                return {
                    'tipo_jml': tipo_jml,
                    'tipo_alerta': 'pendiente',
                    'severidad': 'alta',
                    'dias_limite': 3,
                    'mensaje': f'Leaver NZ/AU abierto {dias_abierto} dias (limite: 3)'
                }
        else:
            if dias_abierto >= 1:
                return {
                    'tipo_jml': tipo_jml,
                    'tipo_alerta': 'pendiente',
                    'severidad': 'critica',
                    'dias_limite': 1,
                    'mensaje': f'Leaver abierto {dias_abierto} dias - CRITICO! Max 24h'
                }

    elif tipo_jml == 'Joiner':
        limite = 10
        if dias_abierto > limite:
            return {
                'tipo_jml': tipo_jml,
                'tipo_alerta': 'pendiente',
                'severidad': 'alta',
                'dias_limite': limite,
                'mensaje': f'Joiner abierto {dias_abierto} dias (limite: {limite})'
            }

    elif tipo_jml == 'Mover':
        limite = 10
        if dias_abierto > limite:
            return {
                'tipo_jml': tipo_jml,
                'tipo_alerta': 'pendiente',
                'severidad': 'media',
                'dias_limite': limite,
                'mensaje': f'Mover abierto {dias_abierto} dias (limite: {limite})'
            }

    if total_hijos == 0:
        return {
            'tipo_jml': tipo_jml,
            'tipo_alerta': 'sin_hijos',
            'severidad': 'media',
            'dias_limite': None,
            'mensaje': 'Sin tareas asociadas'
        }

    return None


def obtener_alertas_padre_listos_para_cerrar():
    """Optimizado: usa consultas directas de Django"""
    hoy = timezone.now().date()
    
    # Estados que consideramos cerrados
    estados_cerrados = ['closed', 'resolved', 'cerrado', 'completed', 'cancelled', 'cancelado']
    
    # Obtener padres abiertos (excluyendo cerrados)
    padres = Ticket.objects.filter(
        Q(linked_request_id__isnull=True) | Q(linked_request_id='')
    ).exclude(
        request_status__in=estados_cerrados
    )
    
    # Obtener todos los hijos con sus padres
    hijos = Ticket.objects.exclude(
        Q(linked_request_id__isnull=True) | Q(linked_request_id='')
    ).exclude(
        request_status__in=estados_cerrados
    )
    
    # Crear diccionario de hijos por padre
    hijos_por_padre = defaultdict(list)
    for hijo in hijos:
        if hijo.linked_request_id:
            hijos_por_padre[hijo.linked_request_id].append(hijo)
    
    cerrar_manual_resto = []
    cerrar_manual_nz_au = []
    
    for padre in padres:
        todos_hijos = hijos_por_padre.get(padre.request_id, [])
        if not todos_hijos:
            continue
        
        # Contar hijos cerrados (que no están en la lista de hijos abiertos)
        # Como ya filtramos hijos cerrados, todos los que están aquí son abiertos
        hijos_cerrados_count = Ticket.objects.filter(
            linked_request_id=padre.request_id,
            request_status__in=estados_cerrados
        ).count()
        
        hijos_abiertos_count = len(todos_hijos)
        
        if hijos_abiertos_count == 0 and hijos_cerrados_count > 0:
            # Calcular días abierto
            if hasattr(padre.created_time, 'date'):
                dias_abierto = (hoy - padre.created_time.date()).days
            else:
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
                'hijos_cerrados': hijos_cerrados_count,
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
    """Envía correo con lista de tickets listos para cerrar"""
    if not destinatario_email:
        destinatario_email = settings.EMAIL_HOST_USER
    
    if not settings.EMAIL_HOST_USER or not settings.EMAIL_HOST_PASSWORD:
        return False, 'Faltan credenciales SMTP en settings (EMAIL_HOST_USER o EMAIL_HOST_PASSWORD).'
    
    try:
        cerrar_manual_resto, cerrar_manual_nz_au = obtener_alertas_padre_listos_para_cerrar()
        tickets_cerrar = cerrar_manual_resto + cerrar_manual_nz_au
        
        # Generar contenido HTML (igual que antes)
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
        <p style="font-size:12px;color:#666666;margin-top:8px;">Este correo solo incluye tickets padre que tienen todos sus hijos cerrados y están listos para cierre manual.</p>
        <table class="data-table">
        <thead><tr><th>ID Ticket</th><th>Nombre</th><th>Tipo</th><th>Días Abierto</th><th>Hijos Cerrados</th></tr></thead>
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
        <div class="footer"><p>Este es un correo automático generado por JML Dashboard.</p><p>Generado el: {timezone.now().strftime('%d/%m/%Y %H:%M:%S')}</p></div>
        </div>
        </body>
        </html>
        """
        
        destinatarios = parse_destinatarios_email(destinatario_email)
        if not destinatarios:
            return False, 'No se proporcionó ningún correo válido.'
        
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


# ========== VISTAS ==========

def upload_csv(request):
    if request.method == 'POST' and request.FILES.get('csv_file'):
        csv_file = request.FILES['csv_file']
        
        if request.POST.get('limpiar_bd') == '1':
            Ticket.objects.all().delete()
        
        try:
            chunks = pd.read_csv(
                csv_file,
                skiprows=5,
                chunksize=2000,
                dtype={
                    'RequestID': str,
                    'Linked Request ID': str,
                },
                low_memory=False,
            )
        except Exception as e:
            return HttpResponse(f"Error al leer el archivo CSV: {e}", status=400)
        
        def safe_date(valor):
            if pd.notna(valor) and str(valor).strip() not in ['Not Assigned', '']:
                try:
                    return pd.to_datetime(valor, errors='coerce').date()
                except:
                    return None
            return None
        
        total = 0
        for chunk in chunks:
            tickets = []
            for _, row in chunk.iterrows():
                request_id = str(row.get('RequestID', '')).strip()
                if not request_id:
                    continue
                
                linked_id = row.get('Linked Request ID')
                if pd.notna(linked_id):
                    linked_id = str(linked_id).strip() or None
                else:
                    linked_id = None
                
                created_time = safe_date(row.get('Created Time'))
                if created_time is None:
                    continue
                
                last_updated = safe_date(row.get('Last Updated Time'))
                resolved_time = safe_date(row.get('Resolved Time'))
                
                tickets.append(Ticket(
                    request_id=request_id,
                    subject=str(row.get('Subject', '')).strip(),
                    request_status=str(row.get('Request Status', '')).strip(),
                    technician=str(row.get('Technician', '')).strip() if pd.notna(row.get('Technician')) else None,
                    created_time=created_time,
                    last_updated=last_updated,
                    resolved_time=resolved_time,
                    linked_request_id=linked_id,
                    requester=str(row.get('Requester', '')).strip() if pd.notna(row.get('Requester')) else None,
                ))
                total += 1
            
            if tickets:
                Ticket.objects.bulk_create(tickets, ignore_conflicts=True)
        
        # Enviar correo con tickets listos para cerrar solo si se solicitó
        if request.POST.get('enviar_correo') == '1':
            destinatario = request.POST.get('email_destino', '').strip()
            if not destinatario:
                messages.error(request, 'Debes ingresar un email destino para enviar el reporte.')
            else:
                exito, error_msg = enviar_correo_tickets_cerrar(destinatario)
                if exito:
                    messages.success(request, f'Correo enviado exitosamente a {destinatario}')
                else:
                    messages.error(request, f'No se pudo enviar el correo. {error_msg}')
        else:
            messages.info(request, 'Archivo cargado sin envío de correo.')
        
        return redirect('alertas')
    
    return render(request, 'tickets/upload.html')


def alertas(request):
    # Obtener estadísticas con consultas directas (optimizado)
    total_tickets = Ticket.objects.count()
    
    # Contar por tipo usando filtros directos (MUCHO más rápido)
    joiners = Ticket.objects.filter(subject__icontains='Joiner').count()
    movers = Ticket.objects.filter(subject__icontains='Mover').count()
    leavers = Ticket.objects.filter(subject__icontains='Leaver').count()
    
    # Obtener padres e hijos con una sola consulta y agrupar en Python
    estados_cerrados = ['closed', 'resolved', 'cerrado', 'completed', 'cancelled', 'cancelado']
    estados_excluir_padre = estados_cerrados
    
    # Obtener todos los padres y precalcular datos
    padres = Ticket.objects.filter(
        Q(linked_request_id__isnull=True) | Q(linked_request_id='')
    ).exclude(request_status__in=estados_excluir_padre)
    
    total_padres = padres.count()
    
    # Obtener hijos agrupados por padre usando un diccionario
    hijos = Ticket.objects.exclude(
        Q(linked_request_id__isnull=True) | Q(linked_request_id='')
    )
    
    hijos_por_padre = defaultdict(list)
    for hijo in hijos:
        if hijo.linked_request_id:
            hijos_por_padre[hijo.linked_request_id].append(hijo)
    
    hoy = timezone.now().date()
    
    alertas_nz_au = []
    alertas_resto = []
    cerrar_manual_nz_au = []
    cerrar_manual_resto = []
    
    for padre in padres:
        todos_hijos = hijos_por_padre.get(padre.request_id, [])
        
        # Separar hijos abiertos y cerrados
        hijos_abiertos = []
        hijos_cerrados = []
        for h in todos_hijos:
            estado = str(h.request_status or '').strip().lower()
            if estado in estados_cerrados:
                hijos_cerrados.append(h)
            else:
                hijos_abiertos.append(h)
        
        hijos_cerrados_count = len(hijos_cerrados)
        total_hijos = len(todos_hijos)
        hijos_pendientes = len(hijos_abiertos)
        
        # Calcular días abierto
        if hasattr(padre.created_time, 'date'):
            fecha_padre = padre.created_time.date()
        else:
            fecha_padre = padre.created_time
        dias_abierto = (hoy - fecha_padre).days if fecha_padre else 0
        
        resolved_time = getattr(padre, 'resolved_time', None)
        region = 'nz_au' if es_nz_o_australia(padre.subject) else 'resto'
        
        prioridad = calcular_prioridad(padre, dias_abierto, total_hijos, hijos_pendientes, resolved_time)
        
        if prioridad:
            alerta = {
                'padre': padre,
                'nombre': extraer_nombre(padre.subject),
                'subject_completo': padre.subject,
                'tipo_alerta': prioridad['tipo_alerta'],
                'severidad': prioridad['severidad'],
                'dias_abierto': dias_abierto,
                'total_hijos': total_hijos,
                'hijos_pendientes': hijos_pendientes,
                'hijos': hijos_abiertos,
                'hijos_cerrados_count': hijos_cerrados_count,
                'tipo_jml': prioridad['tipo_jml'],
                'mensaje': prioridad['mensaje'],
                'dias_limite': prioridad['dias_limite'],
                'es_nz_au': region == 'nz_au',
                'region': region,
            }
            
            if prioridad['tipo_alerta'] == 'cerrar_manual':
                if region == 'nz_au':
                    cerrar_manual_nz_au.append(alerta)
                else:
                    cerrar_manual_resto.append(alerta)
            else:
                if region == 'nz_au':
                    alertas_nz_au.append(alerta)
                else:
                    alertas_resto.append(alerta)
    
    # Ordenar por severidad
    severidad_orden = {'critica': 0, 'alta': 1, 'media': 2, 'baja': 3, 'cerrar': 4}
    alertas_nz_au.sort(key=lambda x: (severidad_orden.get(x['severidad'], 4), -x['dias_abierto']))
    alertas_resto.sort(key=lambda x: (severidad_orden.get(x['severidad'], 4), -x['dias_abierto']))
    
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