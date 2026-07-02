# JML Dashboard

Dashboard para monitoreo de tickets Joiner, Mover y Leaver a partir de archivos CSV exportados manualmente desde ServiceDesk. El sistema identifica tickets padre abiertos, revisa el estado de sus tickets hijos y destaca casos listos para cierre manual, tickets sin padre y categorías especiales como Hardware Leaver.

## Estado Actual

- El flujo principal funciona con carga manual de CSV.
- La aplicacion no depende de API de ServiceDesk para operar.
- El envio de correos se realiza por API HTTP de Brevo.
- La base de datos por defecto es `SQLite`, con soporte opcional para `PostgreSQL` si se define `DATABASE_URL`.

## Stack

- `Django 5.2.7`
- `pandas 3.0.1`
- `requests`
- `openpyxl`
- `python-dotenv`
- `gunicorn`
- `SQLite` por defecto
- `PostgreSQL` opcional via `dj-database-url`

## Funcionamiento General

1. El usuario exporta un CSV desde ServiceDesk.
2. El archivo se carga en la app desde `/upload/`.
3. El sistema normaliza columnas, IDs y fechas.
4. Se guardan tickets padres e hijos en la base de datos local.
5. El dashboard clasifica alertas en:
   - `General`
   - `NZ / Australia`
   - `Hardware Leaver`
   - `Local Apps NZ/AU`
   - `Sin Padre`
6. Se puede:
   - revisar tickets listos para cerrar,
   - exportar Excel,
   - enviar reporte por correo.

## Limitaciones Conocidas

- Si un ticket no viene en el CSV exportado, para el dashboard ese ticket no existe.
- La calidad del resultado depende directamente del filtro y del alcance del reporte exportado desde ServiceDesk.
- El sistema esta pensado para cargas manuales acumulativas por periodo, no para sincronizacion automatica en tiempo real.
- `Hardware Leaver` usa reglas de negocio especiales y no sigue exactamente el mismo flujo de anclaje que otros tickets.

## Estructura del Modulo `tickets`

La app fue reorganizada para separar responsabilidades:

- `tickets/views.py`: endpoints HTTP y respuestas Django.
- `tickets/constants.py`: listas y valores fijos.
- `tickets/utils.py`: helpers reutilizables.
- `tickets/services/alerts.py`: logica de negocio del dashboard.
- `tickets/services/importers.py`: carga y procesamiento del CSV.
- `tickets/services/reports.py`: correo Brevo y exportacion a Excel.

## Requisitos

- Python `3.10+`
- `pip`
- Una cuenta de correo verificada en Brevo si se usara el envio de reportes
- Opcional: cuenta en Render para despliegue externo

## Configuracion Local

1. Clonar el repositorio:

```bash
git clone https://github.com/Gennbu/JML-Dashboard.git
cd "JML Dashboard"
```

2. Crear entorno virtual e instalar dependencias:

```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

3. Crear archivo `.env` en la raiz del proyecto:

```env
DEBUG=True
SECRET_KEY=tu-clave-secreta-local
ALLOWED_HOSTS=localhost,127.0.0.1

# Correo por Brevo
EMAIL_HOST_USER=correo-verificado@dominio.com
EMAIL_HOST_PASSWORD=tu-api-key-de-brevo

# Opcional: solo si quieres PostgreSQL
DATABASE_URL=
```

4. Ejecutar migraciones:

```bash
python manage.py migrate
```

5. Levantar el servidor:

```bash
python manage.py runserver
```

6. Abrir en navegador:

- [http://localhost:8000](http://localhost:8000)

## Variables de Entorno

### Obligatorias para cualquier ambiente serio

- `SECRET_KEY`: clave secreta de Django.
- `DEBUG`: `True` en local, `False` en ambientes de entrega.
- `ALLOWED_HOSTS`: hosts permitidos separados por comas.

### Requeridas si se usa envio de correos

- `EMAIL_HOST_USER`: remitente verificado en Brevo.
- `EMAIL_HOST_PASSWORD`: API key de Brevo.

### Opcionales

- `DATABASE_URL`: habilita PostgreSQL si se quiere evitar SQLite.

## Base de Datos

### Modo actual

- El proyecto usa `SQLite` por defecto.
- La base local vive en `db.sqlite3`.

### Cuándo sirve

- Desarrollo local
- Demo
- Cargas manuales
- Uso por una sola persona o pruebas controladas

### Cuándo conviene migrar

- Si la empresa la va a dejar en un servidor interno
- Si varias personas la van a usar
- Si se requiere persistencia mas estable
- Si IT ya provee una instancia de PostgreSQL

### Soporte ya preparado

- Si existe `DATABASE_URL`, el proyecto intenta usar `PostgreSQL`.
- Si no existe, sigue funcionando con `SQLite`.

## Configuracion de Brevo

El sistema usa la API HTTP de Brevo, no SMTP clasico.

### Requisitos

1. Verificar un remitente en Brevo.
2. Generar una API key desde el panel de Brevo.
3. Configurar el remitente en `EMAIL_HOST_USER`.
4. Configurar la API key en `EMAIL_HOST_PASSWORD`.

### Nota importante para entrega

- La cuenta de Brevo no deberia quedar asociada a una cuenta personal del practicante como solucion final.
- Lo ideal es que la empresa defina:
  - cuenta propietaria,
  - remitente oficial,
  - y nueva API key para operacion futura.

## Despliegue en Render

### Configuracion recomendada

- `Build Command`: `pip install -r requirements.txt`
- `Start Command`: `gunicorn jml_dashboard.wsgi:application`

### Variables sugeridas en Render

```env
DEBUG=False
SECRET_KEY=clave-secreta-produccion
ALLOWED_HOSTS=.onrender.com,tu-dominio-interno
EMAIL_HOST_USER=correo-verificado@dominio.com
EMAIL_HOST_PASSWORD=api-key-brevo
DATABASE_URL=
```

### Nota sobre persistencia

- Si se usa solo `SQLite` en Render free, la persistencia no es confiable ante reinicios o nuevos deploys.
- Para uso serio o compartido, conviene usar `PostgreSQL`.

## Uso Diario

1. Entrar al modulo de carga.
2. Subir CSV.
3. Revisar pestañas y alertas generadas.
4. Exportar Excel si se necesita.
5. Enviar correo si el flujo de Brevo esta configurado.

### 1. Conetenido tecnico

- Readme sobre la instalación del proyecto.

### 2. Documento de handover

Contiene:

- objetivo del proyecto,
- flujo funcional,
- limitaciones del CSV,
- dependencias externas,
- pasos para levantarlo,
- y responsables de accesos.

### 3. Documento operativo corto

- como subir CSV,
- como interpretar pestañas,
- como exportar Excel,
- como enviar correos,
- que hacer si no aparecen tickets esperados.

### 4. Documento de accesos

Separado del README por seguridad:

- repositorio,
- servicio en Render o servidor interno,
- cuenta Brevo,
- variables de entorno,
- base de datos,
- responsables de soporte.

### 5. Lista de pendientes o mejoras futuras

Ejemplos:

- integracion por API con ServiceDesk,
- migracion definitiva a PostgreSQL,
- mover correo a infraestructura de la empresa,
- pruebas automatizadas,
- despliegue interno.

## Recomendacion para Correos

La configuracion final de correos deberia quedar del lado de la empresa o del area encargada de infraestructura/comunicaciones.

## Solucion de Problemas

### No carga tickets

- Verificar que el CSV tenga columnas tipo `RequestID`, `Subject`, `Status`.
- Probar con `Limpiar Base de Datos` si se necesita recargar desde cero.

### No aparecen tickets esperados

- Revisar si realmente vienen en el CSV exportado.
- Validar que el filtro del reporte de ServiceDesk no los este excluyendo.

### No se envian correos

- Confirmar que `EMAIL_HOST_USER` sea un remitente verificado en Brevo.
- Confirmar que `EMAIL_HOST_PASSWORD` sea una API key valida.
- Revisar logs del servidor y restricciones de IP si aplica.

### La base se pierde o queda vacia

- Si se usa `SQLite` en Render o ambientes efimeros, esto puede pasar tras redeploys o reinicios.
- Para persistencia real, usar `PostgreSQL`.

### Cargas grandes de CSV

- El sistema procesa por chunks de `500` filas para reducir carga de memoria.


