from django.urls import path
from . import views

urlpatterns = [
    path('', views.alertas, name='home'),  # ← Ahora la raíz es alertas  # ← Dashboard queda en otra ruta
    path('upload/', views.upload_csv, name='upload_csv'),
    path('alertas/', views.alertas, name='alertas'),  # ← Esta sigue funcionando también
]