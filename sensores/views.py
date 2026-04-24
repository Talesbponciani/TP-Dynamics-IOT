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
from .models import Leitura, Motor, MotorCalibration

# ========== BUFFERS EM MEMÓRIA ==========
buffers = {}
BUFFER_SIZE = 64

def dashboard(request):
    return render(request, 'dashboard.html')

# ============================================================
# GESTÃO DE OFFSETS (PERSISTÊNCIA NO BANCO DE DADOS)
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
            'motor_id': motor_id,
            'offset_x': calib.offset_x,
            'offset_y': calib.offset_y,
            'offset_z': calib.offset_z,
            'timestamp': calib.updated_at.isoformat()
        }, status=200)
    except MotorCalibration.DoesNotExist:
        return JsonResponse({'erro': 'Nenhum offset no banco para este motor'}, status=404)
    except Exception as e:
        return JsonResponse({'erro': str(e)}, status=500)

# ============================================================
# PROCESSAMENTO DE DADOS VIBRATÓRIOS E STATUS ONLINE
# ============================================================
@csrf_exempt
def receber_dados_brutos(request):
    if request.method != 'POST':
        return JsonResponse({'erro': 'somente POST'}, status=405)
    try:
        data = json.loads(request.body)
        motor_id = data.get('motor_id')
        temperatura = float(data.get('temperatura', 0))
        vibX = float(data.get('vibX', 0))
        vibY = float(data.get('vibY', 0))
        vibZ = float(data.get('vibZ', 0))

        motor = Motor.objects.filter(id=motor_id).first()

        if motor_id not in buffers:
            buffers[motor_id] = {
                'x': deque(maxlen=BUFFER_SIZE),
                'y': deque(maxlen=BUFFER_SIZE),
                'z': deque(maxlen=BUFFER_SIZE),
                'tempo': deque(maxlen=BUFFER_SIZE)
            }

        buffers[motor_id]['x'].append(vibX)
        buffers[motor_id]['y'].append(vibY)
        buffers[motor_id]['z'].append(vibZ)
        buffers[motor_id]['tempo'].append(datetime.now().timestamp())

        rms_aceleracao = math.sqrt((vibX**2 + vibY**2 + vibZ**2) / 3)
        pico = max(abs(vibX), abs(vibY), abs(vibZ))
        crest_factor = pico / rms_aceleracao if rms_aceleracao > 0 else 0
        vel_rms = rms_aceleracao * 9.81 / (2 * math.pi * 60) * 1000

        leitura = Leitura.objects.create(
            motor=motor,
            temperatura=round(temperatura, 1),
            vibX=round(vibX, 3),
            vibY=round(vibY, 3),
            vibZ=round(vibZ, 3),
            rms=round(rms_aceleracao, 3),
            crest=round(crest_factor, 2)
        )

        return JsonResponse({'status': 'ok', 'id': leitura.id}, status=201)
    except Exception as e:
        return JsonResponse({'erro': str(e)}, status=500)

def dados_json(request):
    motor_id = request.GET.get('motor_id')
    
    # 1. Busca a última leitura deste motor
    ultima_leitura = Leitura.objects.filter(motor_id=motor_id).order_by('-data').first()
    
    # 2. Lógica de Status Online (Timeout de 10 segundos)
    is_online = False
    if ultima_leitura:
        agora = timezone.now()
        if ultima_leitura.data > agora - timedelta(seconds=10):
            is_online = True

    # 3. Busca histórico para o gráfico
    dados = Leitura.objects.filter(motor_id=motor_id).order_by('-id')[:50] if motor_id else Leitura.objects.all().order_by('-id')[:50]
    
    lista = [{
        "data": d.data.strftime("%H:%M:%S") if d.data else "",
        "motor_id": d.motor.id if d.motor else None,
        "temperatura": float(d.temperatura or 0),
        "rms": float(d.rms or 0),
        "vibX": float(d.vibX or 0),
        "vibY": float(d.vibY or 0),
        "vibZ": float(d.vibZ or 0)
    } for d in reversed(dados)]
    
    # Retorna o status online e a lista de dados
    return JsonResponse({
        "status_online": is_online,
        "leituras": lista
    }, safe=False)

# ============================================================
# ANÁLISE FFT E CRUD DE MOTORES
# ============================================================
def get_fft_data(request, motor_id):
    try:
        if motor_id not in buffers or len(buffers[motor_id]['x']) < BUFFER_SIZE:
            return JsonResponse({'erro': 'Dados insuficientes'}, status=400)
        x_data = np.array(buffers[motor_id]['x']) - np.mean(buffers[motor_id]['x'])
        fft_res = np.abs(fft(x_data * np.hanning(len(x_data))))[:BUFFER_SIZE//2]
        freqs = fftfreq(BUFFER_SIZE, 1/10)[:BUFFER_SIZE//2]
        dados_fft = [{'freq': round(f, 1), 'amp': round(a, 5)} for f, a in zip(freqs, fft_res) if f <= 50]
        return JsonResponse({'fft_data': dados_fft})
    except Exception as e:
        return JsonResponse({'erro': str(e)}, status=500)

def motores_listar(request):
    motores = Motor.objects.all().order_by('id')
    lista = [{'id': m.id, 'nome': m.nome, 'marca': m.marca, 'rpm': m.rpm, 'cv': m.cv} for m in motores]
    return JsonResponse(lista, safe=False)

def ultimo_motor(request):
    m = Motor.objects.last()
    if not m: return JsonResponse({'erro': 'vazio'}, status=404)
    return JsonResponse({'id': m.id, 'nome': m.nome})