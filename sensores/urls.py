from django.urls import path
from . import views

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    
    # APIs de dados
    path('api/dados/', views.dados_json, name='dados_json'),
    path('api/receber/', views.receber_dados, name='receber_dados'),
    path('api/receber_bruto/', views.receber_dados_brutos, name='receber_dados_brutos'),
    
    # APIs de análise
    path('api/analise/<int:motor_id>/', views.get_analise_completa, name='analise_completa'),
    path('api/fft/<int:motor_id>/', views.get_fft_data, name='fft_data'),
    
    # APIs de calibração (OFFSETS)
    path('api/salvar_offset/', views.salvar_offset, name='salvar_offset'),
    path('api/carregar_offset/<int:motor_id>/', views.carregar_offset, name='carregar_offset'),
    path('api/listar_offsets/', views.listar_offsets, name='listar_offsets'),  # Opcional - para debug
    
    # APIs de motores
    path('api/motores/', views.motores_listar, name='motores_listar'),
    path('api/motores/criar/', views.motor_criar, name='motor_criar'),
    path('api/motores/<int:motor_id>/', views.motor_obter, name='motor_obter'),
    path('api/motores/<int:motor_id>/atualizar/', views.motor_atualizar, name='motor_atualizar'),
    path('api/motores/<int:motor_id>/excluir/', views.motor_excluir, name='motor_excluir'),
    path('api/ultimo_motor/', views.ultimo_motor, name='ultimo_motor'),
]