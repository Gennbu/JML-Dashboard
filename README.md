
# JML Dashboard - Sistema de Gestión de Tickets

Un dashboard para monitoreo y cierre manual de tickets de Joiners, Movers y Leavers, con integración a Brevo para envío de reportes y despliegue automático en Render.

---

## Tecnologías

- **Backend**: Django 6.0+
- **Base de Datos**: SQLite 
- **Procesamiento de Datos**: Pandas (para CSVs grandes)
- **Envío de Correos**: Brevo API
- **Despliegue**: Render (gratuita)

---

## Requisitos Previos

- IDE como VS Code, Cursor, Trae, Etc.
- Python 3.10+
- Pip (gestor de paquetes de Python)
- Cuenta en [Render](https://render.com/)
- Cuenta en [Brevo](https://brevo.com/)

---

## Configuración Local (para correr en tu PC)

1. **Clonar el repositorio
```bash
git clone <https://github.com/Gennbu/JML-Dashboard.git>  
cd "JML Dashboard"
```

2. **Crear entorno virtual e instalar dependencias
```bash
# En Windows:
python -m venv venv
venv\Scripts\activate 
pip install -r requirements.txt
```

3. **Variables de Entorno
Crea un archivo `.env` en la raíz del proyecto con esto:
```env
# Django (seguridad)
SECRET_KEY=tu-clave-secreta-aqui

# Brevo (Envío de Correos)
EMAIL_HOST_USER=tu-correo-verificado-aqui@empresa.com
EMAIL_HOST_PASSWORD=tu-api-key-brevo-aqui

# Para desarrollo local (SÓLO)
DEBUG=True
```

4. **Ejecutar migraciones
```bash
python manage.py migrate
```

5. **Correr el servidor
```bash
python manage.py runserver
```

¡Listo! Abre tu navegador y visita [http://localhost:8000](http://localhost:8000).

---

## Despliegue en Render

### Paso 1: Crea tu servicio web
1.  Inicia sesión en el [Dashboard de Render](https://dashboard.render.com/)
2.  Haz clic en **New** > **Web Service**
3.  Conecta tu repositorio de GitHub/GitLab
4.  Configura el servicio:
    - **Name**: `jml-dashboard (o lo que quieras)
    - **Build Command**: `pip install -r requirements.txt
    - **Start Command**: `gunicorn jml_dashboard.wsgi
    - **Runtime**: Python 3.14 (o la versión que uses localmente)

### Paso 2: Añade Variables de Entorno
En la sección **Environment** del servicio:
- `EMAIL_HOST_USER`: Tu correo verificado en Brevo
- `EMAIL_HOST_PASSWORD`: Tu API Key de Brevo
- `SECRET_KEY`: Una clave secreta aleatoria 

---

## Configuración de Brevo (¡Obligatoria para correos!)

1.  **Verifica el remitente del correo:
    - En Brevo, ve a **Remitentes
    - Añade el correo que usarás (ej: `jmlnotificaciones@gmail.com`)
    - Valídalo (te llegará un email de confirmación).

2.  **Genera la API Key:
    - Ve a **SMTP & API** (arriba a la derecha)
    - Ve a la pestaña **Claves API y MCP
    - Haz clic en **Generar una nueva clave API** y guárdala en un lugar seguro.
    - ¡Esa clave es tu `EMAIL_HOST_PASSWORD`.

3.  **Quitar restricción de IP (Recomendado para Render):
    - En Brevo, ve a **Configuración > Seguridad > Direcciones IP autorizadas
    - Desactiva la opción de filtrado o autoriza la IP que sale como "No autorizada".

---

## Checklist de Handover (Entrega del Proyecto)

Para dejarlo listo para quien quede al cargo:

### 1. Credenciales y Accesos
Guarda esto en un lugar seguro y compártelo solo con la persona designada:
- **Render**: Añade el correo del nuevo compañero como **Collaborator** en el servicio de Render (en Settings > Collaborators).
- **Brevo**: Compártelo si es necesario o crea una nueva API Key para ellos.
- **Repositorio**: Añade al nuevo usuario como **Colaborador** en GitHub/GitLab.

### 2. Recomendaciones de Mantenimiento
- **Workflow Diario**: Sube el CSV desde la plataforma → Ver alertas → Enviar reportes a quien corresponda
- **Seguridad**: Si la empresa tiene un correo dedicado, cambia el remitente en Brevo para usar el de la empresa
- **Costos**: Render Free Tier tiene 750 horas mensuales, Brevo Free 300 correos/día sin pagar nada.
- **Persistencia**: Si Render reinicia la app, los datos se borran. Usa la opción "Limpiar Base de Datos" antes de subir un nuevo CSV para empezar de nuevo.

### 3. Para el nuevo usuario
- Debe saber que el filtro de IP está **desactivado** en Brevo (para no tener que autorizar IPs cada vez que Render cambie de dirección).

---

## Solución de Problemas Frecuentes

1.  **No carga tickets**:
    - Asegúrate de que el CSV tenga columnas parecidas a `RequestID`, `Subject`
    - Prueba subirlo marcando **Limpiar Base de Datos primero.

2.  **No envían correos:
    - Revisa en Render Logs (Monitoring > Logs en Render)
    - Asegúrate que la API Key es de la sección **Claves API y MCP** (no la de SMTP!).

3.  **Se cae Render (Timeout:
    - El chunksize ya está configurado a 1000 tickets para no saturar, no hay problema con CSVs grandes.

