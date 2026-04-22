from django.urls import path
from . import views

urlpatterns = [
    # ==================== PÁGINAS PRINCIPAIS ====================
    path('', views.dashboard, name='dashboard'),
    
    # ==================== API DE LEITURAS (Sensores) ====================
    path('api/dados/', views.dados_json, name='dados_json'),
    path('api/receber/', views.receber_dados, name='receber_dados'),
    
    # ==================== API DE MOTORES (CRUD completo) ====================
    path('api/motores/', views.motores_listar, name='motores_listar'),                    # GET - listar todos
    path('api/motores/criar/', views.motor_criar, name='motor_criar'),                    # POST - criar novo
    path('api/motores/ultimo/', views.ultimo_motor, name='ultimo_motor'),                 # GET - último motor
    path('api/motores/<int:motor_id>/', views.motor_obter, name='motor_obter'),           # GET - obter um
    path('api/motores/<int:motor_id>/atualizar/', views.motor_atualizar, name='motor_atualizar'),  # PUT - atualizar
    path('api/motores/<int:motor_id>/excluir/', views.motor_excluir, name='motor_excluir'),        # DELETE - excluir
]