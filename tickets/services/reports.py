from io import BytesIO

import pandas as pd
import requests
from django.conf import settings
from django.utils import timezone

from ..utils import parse_destinatarios_email
from .alerts import obtener_alertas_padre_listos_para_cerrar


def enviar_correo_tickets_cerrar(destinatario_email=None):
    print("--- Iniciando envio de correo (DEBUG COMPLETO) ---")

    if not destinatario_email:
        destinatario_email = settings.DEFAULT_FROM_EMAIL

    api_key = obtener_brevo_api_key()
    if not api_key:
        print("  → ERROR: NO HAY API KEY!")
        return False, 'Falta la API Key de Brevo.'

    print(f"  → Remitente configurado: '{settings.DEFAULT_FROM_EMAIL}'")

    try:
        print("  → Obteniendo alertas de 'Listos para cerrar'...")
        cerrar_manual_resto, cerrar_manual_nz_au = obtener_alertas_padre_listos_para_cerrar()
        tickets_cerrar_full = cerrar_manual_resto + cerrar_manual_nz_au
        print(f"  → Tickets listos para cerrar: {len(tickets_cerrar_full)}")

        tickets_cerrar = tickets_cerrar_full[:250]
        print(f"  → Mostrando {len(tickets_cerrar)} tickets en el correo")

        destinatarios = parse_destinatarios_email(destinatario_email)
        print(f"  → Destinatarios validados: {len(destinatarios)}")
        if not destinatarios:
            return False, 'No se proporcionó ningún correo válido.'

        payload = construir_payload_brevo(
            destinatarios=destinatarios,
            tickets_cerrar=tickets_cerrar,
            tickets_cerrar_full=tickets_cerrar_full,
        )

        print("  → Enviando POST a API Brevo...")
        print("  → URL: https://api.brevo.com/v3/smtp/email")
        print(f"  → Payload sender: {payload['sender']}")

        response = requests.post(
            "https://api.brevo.com/v3/smtp/email",
            json=payload,
            headers={
                "accept": "application/json",
                "api-key": api_key,
                "content-type": "application/json",
            },
            timeout=60,
        )

        print(f"  → Respuesta status code: {response.status_code}")
        print(f"  → Respuesta texto: {response.text}")

        if response.status_code in [200, 201, 202]:
            print("  → ✅ ENVÍO EXITOSO!")
            return True, 'Reporte enviado exitosamente'

        print("  → ❌ ERROR EN API!")
        return False, f"Error API: {response.text[:200]}"
    except Exception as exc:
        print(f"  → ❌ EXCEPCIÓN: {str(exc)}")
        import traceback

        print(traceback.format_exc())
        return False, f"Error interno: {str(exc)}"


def generar_excel_listos_cerrar():
    cerrar_manual_resto, cerrar_manual_nz_au = obtener_alertas_padre_listos_para_cerrar()

    columnas = [
        'Request ID',
        'Nombre',
        'Subject completo',
        'Tipo JML',
        'Estado padre',
        'Fecha creacion',
        'Dias abierto',
        'Total hijos',
        'Hijos cerrados',
        'Hijos pendientes',
        'Region',
        'Mensaje',
    ]
    filas_resto = construir_filas_excel(cerrar_manual_resto, 'General')
    filas_nz_au = construir_filas_excel(cerrar_manual_nz_au, 'NZ_AU')

    output = BytesIO()
    nombre_archivo = f"tickets_listos_cerrar_{timezone.now().strftime('%Y%m%d_%H%M%S')}.xlsx"

    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df_resto = pd.DataFrame(filas_resto, columns=columnas)
        df_nz_au = pd.DataFrame(filas_nz_au, columns=columnas)
        df_total = pd.DataFrame(filas_resto + filas_nz_au, columns=columnas)

        df_total.to_excel(writer, index=False, sheet_name='Listos_Cerrar')
        df_resto.to_excel(writer, index=False, sheet_name='General')
        df_nz_au.to_excel(writer, index=False, sheet_name='NZ_AU')

        ajustar_ancho_columnas(
            writer,
            {
                'Listos_Cerrar': df_total,
                'General': df_resto,
                'NZ_AU': df_nz_au,
            },
        )

    return output.getvalue(), nombre_archivo


def obtener_brevo_api_key():
    if hasattr(settings, 'BREVO_API_KEY') and settings.BREVO_API_KEY:
        return settings.BREVO_API_KEY

    if hasattr(settings, 'EMAIL_HOST_PASSWORD') and settings.EMAIL_HOST_PASSWORD:
        return settings.EMAIL_HOST_PASSWORD

    return None


def construir_payload_brevo(destinatarios, tickets_cerrar, tickets_cerrar_full):
    return {
        "sender": {"email": settings.DEFAULT_FROM_EMAIL, "name": "JML Dashboard"},
        "to": [{"email": email} for email in destinatarios],
        "subject": f"JML Dashboard - {len(tickets_cerrar_full)} tickets listos para cerrar",
        "htmlContent": construir_html_correo(tickets_cerrar, tickets_cerrar_full),
    }


def construir_html_correo(tickets_cerrar, tickets_cerrar_full):
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
    return html_content


def construir_filas_excel(alertas, region_label):
    filas = []
    for ticket in alertas:
        padre = ticket['padre']
        fecha_creacion = ''
        if padre.created_time:
            if hasattr(padre.created_time, 'strftime'):
                fecha_creacion = padre.created_time.strftime('%Y-%m-%d %H:%M')
            else:
                fecha_creacion = str(padre.created_time)

        filas.append(
            {
                'Request ID': ticket['request_id'],
                'Nombre': ticket['nombre'],
                'Subject completo': ticket['subject_completo'],
                'Tipo JML': ticket['tipo_jml'],
                'Estado padre': padre.request_status,
                'Fecha creacion': fecha_creacion,
                'Dias abierto': ticket['dias_abierto'],
                'Total hijos': ticket['total_hijos'],
                'Hijos cerrados': ticket['hijos_cerrados_count'],
                'Hijos pendientes': ticket['hijos_pendientes'],
                'Region': region_label,
                'Mensaje': ticket['mensaje'],
            }
        )
    return filas


def ajustar_ancho_columnas(writer, hojas):
    for sheet_name, dataframe in hojas.items():
        worksheet = writer.sheets[sheet_name]
        for idx, column in enumerate(dataframe.columns, 1):
            if dataframe.empty:
                max_len = len(str(column))
            else:
                max_len = max([len(str(column))] + [len(str(value)) for value in dataframe[column].fillna('').tolist()])
            worksheet.column_dimensions[chr(64 + idx)].width = min(max(max_len + 2, 14), 60)
