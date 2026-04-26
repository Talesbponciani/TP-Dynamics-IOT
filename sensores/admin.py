from django.contrib import admin
from .models import Motor  # Importe seu modelo aqui

@admin.register(Motor)
class MotorAdmin(admin.ModelAdmin):
    # Isso ajuda a ver as informações importantes direto na lista
    list_display = ('nome', 'limite_alerta', 'ultimo_alerta_enviado')