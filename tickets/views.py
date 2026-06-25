import threading
import traceback

from django.contrib import messages
from django.http import HttpResponse
from django.shortcuts import redirect, render

from .services import (
    build_alertas_context,
    cargar_tickets_desde_csv,
    enviar_correo_tickets_cerrar,
    generar_excel_listos_cerrar,
)


def exportar_excel_listos_cerrar(request):
    contenido, nombre_archivo = generar_excel_listos_cerrar()
    response = HttpResponse(
        contenido,
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
    response['Content-Disposition'] = f'attachment; filename="{nombre_archivo}"'
    return response


def upload_csv(request):
    if request.method == 'POST' and request.FILES.get('csv_file'):
        csv_file = request.FILES['csv_file']
        limpiar_bd = request.POST.get('limpiar_bd') == '1'

        try:
            total_creados = cargar_tickets_desde_csv(csv_file, limpiar_bd=limpiar_bd)
        except ValueError as exc:
            status_code = 400 if str(exc).startswith('Error al abrir CSV:') else 500
            return HttpResponse(str(exc), status=status_code)

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
        return render(request, 'tickets/alertas.html', build_alertas_context())
    except Exception as exc:
        print(f"ERROR EN ALERTAS: {str(exc)}")
        print(traceback.format_exc())
        return HttpResponse(f"Error en el servidor: {exc}", status=500)
