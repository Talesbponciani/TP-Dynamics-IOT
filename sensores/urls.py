from django.urls import path
from . import views

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    
    # APIs de dados e Status Online
    path('api/dados/', views.dados_json, name='dados_json'),
    path('api/receber_bruto/', views.receber_dados_brutos, name='receber_dados_brutos'),
    
    # API de FFT
    path('api/fft/<int:motor_id>/', views.get_fft_data, name='fft_data'),
    
    # APIs de calibração (OFFSETS)
    path('api/salvar_offset/', views.salvar_offset, name='salvar_offset'),
    path('api/carregar_offset/<int:motor_id>/', views.carregar_offset, name='carregar_offset'),
    
    # APIs de motores
    path('api/motores/', views.motores_listar, name='motores_listar'),
    path('api/ultimo_motor/', views.ultimo_motor, name='ultimo_motor'),
]