from django.http import JsonResponse
from django.shortcuts import render, get_object_or_404
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone
from datetime import timedelta
import json
import math
import numpy as np
from scipy.fft import fft, fftfreq
from scipy import stats
from collections import deque
from datetime import datetime
import os

from .models import Leitura, Motor, MotorCalibration

# ========== BUFFERS EM MEMÓRIA ==========
buffers = {}
BUFFER_SIZE = 64

def dashboard(request):
    return render(request, 'dashboard.html')

# ============================================================
# GESTÃO DE OFFSETS (BANCO DE DADOS)
# ============================================================

@csrf_exempt
def salvar_offset(request):
    if request.method != 'POST':
        return JsonResponse({'erro': 'somente POST'}, status=405)
    try:
        data = json.loads(request.body)
        m_id = data.get('motor_id')
        motor_instancia = get_object_or_404(Motor, id=m_id)
        
        obj, created = MotorCalibration.objects.update_or_create(
            motor=motor_instancia,
            defaults={
                'offset_x': float(data.get('offset_x', 0)),
                'offset_y': float(data.get('offset_y', 0)),
                'offset_z': float(data.get('offset_z', 0)),
            }
        )
        return JsonResponse({'status': 'ok', 'atualizado': not created}, status=200)
    except Exception as e:
        return JsonResponse({'erro': str(e)}, status=500)

@csrf_exempt
def carregar_offset(request, motor_id):
    try:
        calib = MotorCalibration.objects.get(motor__id=motor_id)
        return JsonResponse({
            'status': 'ok',
            'offset_x': calib.offset_x,
            'offset_y': calib.offset_y,
            'offset_z': calib.offset_z
        }, status=200)
    except MotorCalibration.DoesNotExist:
        return JsonResponse({'erro': 'Não calibrado'}, status=404)

# ============================================================
# PROCESSAMENTO E STATUS ONLINE/OFFLINE
# ============================================================

@csrf_exempt
def receber_dados_brutos(request):
    if request.method != 'POST':
        return JsonResponse({'erro': 'somente POST'}, status=405)
    try:
        data = json.loads(request.body)
        motor_id = data.get('motor_id')
        vibX = float(data.get('vibX', 0))
        vibY = float(data.get('vibY', 0))
        vibZ = float(data.get('vibZ', 0))
        temp = float(data.get('temperatura', 0))
        
        motor = Motor.objects.filter(id=motor_id).first()
        
        # Manutenção de buffers para FFT
        if motor_id not in buffers:
            buffers[motor_id] = {'x': deque(maxlen=BUFFER_SIZE), 'y': deque(maxlen=BUFFER_SIZE), 'z': deque(maxlen=BUFFER_SIZE)}
        
        buffers[motor_id]['x'].append(vibX)
        buffers[motor_id]['y'].append(vibY)
        buffers[motor_id]['z'].append(vibZ)
        
        rms_acel = math.sqrt((vibX**2 + vibY**2 + vibZ**2) / 3)
        
        leitura = Leitura.objects.create(
            motor=motor,
            temperatura=round(temp, 1),
            vibX=round(vibX, 3),
            vibY=round(vibY, 3),
            vibZ=round(vibZ, 3),
            rms=round(rms_acel, 3),
            crest=0 # Calculado se necessário
        )
        return JsonResponse({'status': 'ok', 'id': leitura.id}, status=201)
    except Exception as e:
        return JsonResponse({'erro': str(e)}, status=500)

def dados_json(request):
    """
    Função principal para o Dashboard.
    Retorna se o equipamento está online e os dados para o gráfico.
    """
    motor_id = request.GET.get('motor_id')
    if not motor_id:
        return JsonResponse({'erro': 'motor_id obrigatorio'}, status=400)

    # 1. Verificar se está Online (Timeout de 10 segundos)
    ultima_leitura = Leitura.objects.filter(motor_id=motor_id).order_by('-data').first()
    
    is_online = False
    if ultima_leitura:
        # Compara o tempo atual com o tempo da última leitura no banco
        if ultima_leitura.data > timezone.now() - timedelta(seconds=10):
            is_online = True

    # 2. Buscar dados para o gráfico
    dados = Leitura.objects.filter(motor_id=motor_id).order_by('-id')[:50]
    
    lista_grafico = []
    for d in reversed(dados):
        lista_grafico.append({
            "hora": d.data.strftime("%H:%M:%S"),
            "rms": d.rms,
            "temp": d.temperatura,
            "x": d.vibX,
            "y": d.vibY,
            "z": d.vibZ
        })

    return JsonResponse({
        "status_online": is_online,
        "dados": lista_grafico
    }, safe=False)

# ============================================================
# ANÁLISE FFT
# ============================================================

def get_fft_data(request, motor_id):
    try:
        if motor_id not in buffers or len(buffers[motor_id]['x']) < BUFFER_SIZE:
            return JsonResponse({'erro': 'Aguardando amostras...'}, status=400)
        
        x_data = np.array(buffers[motor_id]['x']) - np.mean(buffers[motor_id]['x'])
        fs = 10 
        freqs = fftfreq(BUFFER_SIZE, 1/fs)[:BUFFER_SIZE//2]
        fft_res = np.abs(fft(x_data * np.hanning(BUFFER_SIZE)))[:BUFFER_SIZE//2]
        
        dados_fft = [{'freq': round(f, 1), 'amp': round(a, 5)} for f, a in zip(freqs, fft_res)]
        return JsonResponse({'fft_data': dados_fft})
    except Exception as e:
        return JsonResponse({'erro': str(e)}, status=500)

# ============================================================
# CRUD MOTORES
# ============================================================

def motores_listar(request):
    motores = Motor.objects.all().order_by('id')
    return JsonResponse([{'id': m.id, 'nome': m.nome} for m in motores], safe=False)

def ultimo_motor(request):
    m = Motor.objects.last()
    return JsonResponse({'id': m.id, 'nome': m.nome} if m else {'erro': 'vazio'})