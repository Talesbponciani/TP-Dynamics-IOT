from django.contrib import admin
from .models import Motor, Leitura  # Adicione Leitura aqui

@admin.register(Motor)
class MotorAdmin(admin.ModelAdmin):
    list_display = ('nome', 'limite_alerta', 'ultimo_alerta_enviado')

@admin.register(Leitura) # Adicione este bloco para ver o histórico
class LeituraAdmin(admin.ModelAdmin):
    list_display = ('data', 'motor', 'rms', 'temperatura')
    list_filter = ('motor', 'data') # Filtros laterais úteis