# JML Dashboard

Dashboard de gestión de tickets para JML.

## 📋 Requisitos previos

- **Python 3.10+** instalado en tu computadora
- **Git** instalado (recomendado para clonar el repositorio)
- **GitHub Desktop** (opcional, para una interfaz gráfica)

---

## 🚀 Instalación desde GitHub Desktop (Recomendado)

### Paso 1: Clonar el repositorio

1. Abre **GitHub Desktop**
2. Haz clic en **File → Clone repository**
3. Ingresa la URL del repositorio:
   ```
   https://github.com/Gennbu/JML-Dashboard.git
   ```
4. Elige la carpeta donde deseas guardar el proyecto
5. Haz clic en **Clone**

### Paso 2: Abrir la terminal en el proyecto

1. En GitHub Desktop, con el proyecto abierto, ve a **Repository → Open in Command Prompt** (o PowerShell)
2. O abre PowerShell manualmente y navega a la carpeta del proyecto:
   ```powershell
   cd "C:\ruta\a\tu\proyecto\JML Dashboard"
   ```

### Paso 3: Crear y activar el entorno virtual

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
```

Si te aparece un error de permisos, ejecuta:
```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

### Paso 4: Instalar las dependencias

```powershell
pip install -r requirements.txt
```

### Paso 5: Crear archivo .env (si es necesario)

En la raíz del proyecto, crea un archivo `.env` con las variables de entorno necesarias:

```env
# Ejemplo de .env
SECRET_KEY=tu-llave-secreta-aqui
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1,192.168.1.9
```

### Paso 6: Aplicar migraciones de base de datos

```powershell
cd jml_dashboard
python manage.py migrate
```

### Paso 7: Crear un superusuario (Admin)

```powershell
python manage.py createsuperuser
```

Ingresa:
- **Username**: tu usuario
- **Email**: tu correo
- **Password**: tu contraseña

### Paso 8: Ejecutar el servidor de desarrollo

```powershell
python manage.py runserver
```

El servidor estará disponible en: `http://127.0.0.1:8000`

---

## 🌐 Instalación desde línea de comandos (Alternativo)

Si prefieres no usar GitHub Desktop:

```powershell
# 1. Clonar el repositorio
git clone https://github.com/Gennbu/JML-Dashboard.git
cd "JML Dashboard"

# 2. Crear y activar el entorno virtual
python -m venv venv
.\venv\Scripts\Activate.ps1

# 3. Instalar dependencias
pip install -r requirements.txt

# 4. Entrar a la carpeta del proyecto
cd jml_dashboard

# 5. Crear migraciones si es necesario
python manage.py migrate

# 6. Crear superusuario
python manage.py createsuperuser

# 7. Ejecutar el servidor
python manage.py runserver
```

---

## 📦 Dependencias principales

Las siguientes dependencias se instalarán automáticamente:

| Paquete | Versión | Descripción |
|---------|---------|-------------|
| Django | 5.2.7 | Framework web |
| asgiref | 3.10.0 | Soporte ASGI |
| python-dotenv | - | Variables de entorno |
| django-anymail | - | Envío de correos |
| pandas | - | Análisis de datos |
| numpy | - | Computación numérica |
| psycopg2-binary | - | Driver PostgreSQL |
| certifi | - | Certificados SSL |

---

## 🔗 URL del repositorio

**GitHub:** [https://github.com/Gennbu/JML-Dashboard](https://github.com/Gennbu/JML-Dashboard)

---

## 📁 Estructura del proyecto

```
JML Dashboard/
├── jml_dashboard/          # Carpeta del proyecto Django
│   ├── manage.py
│   ├── jml_dashboard/      # Configuración del proyecto
│   │   ├── settings.py
│   │   ├── urls.py
│   │   ├── wsgi.py
│   │   └── asgi.py
│   ├── tickets/            # Aplicación de tickets
│   │   ├── models.py
│   │   ├── views.py
│   │   ├── urls.py
│   │   ├── templates/
│   │   └── migrations/
│   └── db.sqlite3          # Base de datos (local)
├── venv/                   # Entorno virtual (no subir a git)
├── requirements.txt        # Dependencias del proyecto
└── .env                    # Variables de entorno (no subir a git)
```

---

## 🛠️ Comandos útiles

| Comando | Descripción |
|---------|-------------|
| `python manage.py check` | Verifica que todo esté configurado correctamente |
| `python manage.py makemigrations` | Crea nuevas migraciones de BD |
| `python manage.py migrate` | Aplica las migraciones a la BD |
| `python manage.py createsuperuser` | Crea un usuario administrador |
| `python manage.py runserver` | Inicia el servidor de desarrollo |
| `deactivate` | Desactiva el entorno virtual |

---

## ⚠️ Notas importantes

- **No subir a GitHub:** Carpeta `venv/`, archivo `.env` y `db.sqlite3`
- **Siempre activar el venv** antes de trabajar: `.\venv\Scripts\Activate.ps1`
- **Usar requirements.txt** para instalar dependencias, no `pip install` individual
- Para usar **PostgreSQL** en producción, modifica `settings.py`

---

## 📞 Soporte

Si tienes problemas con la instalación, verifica:

1. Python está instalado: `python --version`
2. El venv está activado (deberías ver `(venv)` en la terminal)
3. Todas las dependencias instaladas: `pip list`
4. El archivo `.env` tiene las variables necesarias

---

**Última actualización:** 2026-06-05
