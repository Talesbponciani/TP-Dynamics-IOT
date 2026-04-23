from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
import json
import math
import numpy as np
from scipy.fft import fft, fftfreq
from scipy import stats
from collections import deque
from datetime import datetime

from .models import Leitura, Motor

# Buffer para armazenar amostras para FFT
buffers = {}
BUFFER_SIZE = 256  # 256 amostras para FFT


# =========================
# DASHBOARD
# =========================
def dashboard(request):
    return render(request, 'dashboard.html')


# =========================
# RECEBER DADOS DO ESP32 (COM CÁLCULOS NO ESP32)
# =========================
@csrf_exempt
def receber_dados(request):
    if request.method != 'POST':
        return JsonResponse({'erro': 'somente POST'}, status=405)

    try:
        data = json.loads(request.body)

        motor_id = data.get('motor_id')
        motor = None

        if motor_id:
            motor = Motor.objects.filter(id=motor_id).first()

        leitura = Leitura.objects.create(
            motor=motor,
            temperatura=float(data.get('temperatura', 0)),
            vibX=float(data.get('vibX', 0)),
            vibY=float(data.get('vibY', 0)),
            vibZ=float(data.get('vibZ', 0)),
            rms=float(data.get('rms', 0)),
            crest=float(data.get('crest', 0))
        )

        return JsonResponse({
            'status': 'ok',
            'id': leitura.id
        }, status=201)

    except json.JSONDecodeError:
        return JsonResponse({'erro': 'JSON inválido'}, status=400)

    except Exception as e:
        return JsonResponse({
            'status': 'erro',
            'msg': str(e)
        }, status=500)


# =========================
# RECEBER DADOS BRUTOS DO ESP32 (CÁLCULOS NO BACKEND)
# =========================
@csrf_exempt
def receber_dados_brutos(request):
    """Recebe dados brutos do ESP32 e calcula RMS, Crest Factor, severidade, etc."""
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
        
        # Inicializar buffer para este motor
        if motor_id not in buffers:
            buffers[motor_id] = {
                'x': deque(maxlen=BUFFER_SIZE),
                'y': deque(maxlen=BUFFER_SIZE),
                'z': deque(maxlen=BUFFER_SIZE),
                'tempo': deque(maxlen=BUFFER_SIZE)
            }
        
        # Adicionar amostra ao buffer
        buffers[motor_id]['x'].append(vibX)
        buffers[motor_id]['y'].append(vibY)
        buffers[motor_id]['z'].append(vibZ)
        buffers[motor_id]['tempo'].append(datetime.now().timestamp())
        
        # ===== CÁLCULOS BÁSICOS =====
        rms_total = math.sqrt((vibX**2 + vibY**2 + vibZ**2) / 3)
        pico = max(abs(vibX), abs(vibY), abs(vibZ))
        crest_factor = pico / rms_total if rms_total > 0 else 0
        
        # Kurtosis para esta amostra (simplificado)
        amostras = [vibX, vibY, vibZ]
        media = np.mean(amostras)
        std = np.std(amostras)
        if std > 0:
            kurtosis = stats.kurtosis(amostras, fisher=True)
        else:
            kurtosis = 0
        
        # Velocidade em mm/s (ISO 10816)
        vel_rms = rms_total * 9.81 / (2 * math.pi * 60) * 1000
        
        # Severidade
        if rms_total < 1.0:
            severidade = "Boa"
            recomendacao = "Operacao normal"
        elif rms_total < 3.5:
            severidade = "Aceitavel"
            recomendacao = "Monitorar tendencia"
        elif rms_total < 7.0:
            severidade = "Insatisfatoria"
            recomendacao = "Planejar manutencao"
        else:
            severidade = "Perigosa"
            recomendacao = "PARAR EQUIPAMENTO IMEDIATAMENTE"
        
        alerta = rms_total > 5.0
        
        # Criar leitura
        leitura = Leitura.objects.create(
            motor=motor,
            temperatura=round(temperatura, 1),
            vibX=round(vibX, 3),
            vibY=round(vibY, 3),
            vibZ=round(vibZ, 3),
            rms=round(rms_total, 3),
            crest=round(crest_factor, 2)
        )
        
        return JsonResponse({
            'status': 'ok',
            'id': leitura.id,
            'calculos': {
                'rms': round(rms_total, 3),
                'crest_factor': round(crest_factor, 2),
                'kurtosis': round(kurtosis, 3),
                'velocidade_mm_s': round(vel_rms, 2),
                'severidade': severidade,
                'recomendacao': recomendacao,
                'alerta': alerta
            }
        }, status=201)

    except Exception as e:
        return JsonResponse({'erro': str(e)}, status=500)


# =========================
# DADOS PARA GRÁFICO
# =========================
def dados_json(request):
    motor_id = request.GET.get('motor_id')

    if motor_id:
        dados = Leitura.objects.select_related('motor').filter(motor_id=motor_id).order_by('-id')[:30]
    else:
        dados = Leitura.objects.select_related('motor').all().order_by('-id')[:30]

    lista = []
    for d in reversed(dados):
        lista.append({
            "data": d.data.strftime("%H:%M:%S") if d.data else "",
            "motor_id": d.motor.id if d.motor else None,
            "temperatura": float(d.temperatura or 0),
            "rms": float(d.rms or 0),
            "vibX": float(d.vibX or 0),
            "vibY": float(d.vibY or 0),
            "vibZ": float(d.vibZ or 0)
        })

    return JsonResponse(lista, safe=False)


# =========================
# ANÁLISE COMPLETA ESTILO SKF
# =========================
def get_analise_completa(request, motor_id):
    """Retorna análise completa estilo SKF para o frontend"""
    try:
        if motor_id not in buffers or len(buffers[motor_id]['x']) < BUFFER_SIZE:
            return JsonResponse({'erro': 'Amostras insuficientes para analise'}, status=400)
        
        # Converter para arrays numpy
        x_data = np.array(buffers[motor_id]['x'])
        y_data = np.array(buffers[motor_id]['y'])
        z_data = np.array(buffers[motor_id]['z'])
        
        # Remover tendencia linear
        x_data = x_data - np.mean(x_data)
        y_data = y_data - np.mean(y_data)
        z_data = z_data - np.mean(z_data)
        
        # Aplicar janela de Hann
        window = np.hanning(BUFFER_SIZE)
        x_windowed = x_data * window
        
        # Calcular FFT
        fs = 100  # Frequencia de amostragem (100 Hz do ADXL345)
        freq = fftfreq(BUFFER_SIZE, 1/fs)[:BUFFER_SIZE//2]
        fft_x = np.abs(fft(x_windowed))[:BUFFER_SIZE//2]
        
        # Calcular métricas
        rms_total = np.sqrt(np.mean(x_data**2))
        pico = np.max(np.abs(x_data))
        crest_factor = pico / rms_total if rms_total > 0 else 0
        kurtosis_val = stats.kurtosis(x_data, fisher=True)
        
        # Velocidade em mm/s
        vel_rms = rms_total * 9.81 / (2 * math.pi * 60) * 1000
        
        # Frequência dominante
        freq_dominante = freq[np.argmax(fft_x[1:]) + 1] if len(fft_x) > 1 else 0
        
        # Energia em altas frequencias (acima de 10 Hz)
        alta_freq_inicio = int(10 * BUFFER_SIZE / fs)
        energia_alta_freq = np.sum(fft_x[alta_freq_inicio:]) if alta_freq_inicio < len(fft_x) else 0
        
        # Razão harmônica (2a harmônica / fundamental)
        freq_fundamental = 60
        idx_fund = int(freq_fundamental * BUFFER_SIZE / fs)
        if idx_fund < len(fft_x):
            amp_fund = fft_x[idx_fund]
            amp_2harm = fft_x[min(2*idx_fund, len(fft_x)-1)] if 2*idx_fund < len(fft_x) else 0
            razao_harmonico = amp_2harm / amp_fund if amp_fund > 0 else 0
        else:
            razao_harmonico = 0
        
        # Severidade
        if rms_total < 1.0:
            severidade = "Boa"
            recomendacao = "Operacao normal"
        elif rms_total < 3.5:
            severidade = "Aceitavel"
            recomendacao = "Monitorar tendencia"
        elif rms_total < 7.0:
            severidade = "Insatisfatoria"
            recomendacao = "Planejar manutencao"
        else:
            severidade = "Perigosa"
            recomendacao = "PARAR EQUIPAMENTO IMEDIATAMENTE"
        
        # Condição de rolamento (baseado em kurtosis e energia alta freq)
        if kurtosis_val > 3 or energia_alta_freq > 50:
            condicao_rolamento = "Falha detectada - Inspecionar"
        elif kurtosis_val > 2:
            condicao_rolamento = "Atencao - Monitorar"
        else:
            condicao_rolamento = "Normal"
        
        # Condição de mancal/desalinhamento
        if razao_harmonico > 0.5:
            condicao_mancal = "Possivel desalinhamento - Verificar"
        elif razao_harmonico > 0.3:
            condicao_mancal = "Atencao - Monitorar"
        else:
            condicao_mancal = "Normal"
        
        # Nível de alerta
        if severidade == "Perigosa":
            nivel_alerta = "CRITICO"
        elif severidade == "Insatisfatoria" or energia_alta_freq > 50:
            nivel_alerta = "ALERTA"
        else:
            nivel_alerta = "NORMAL"
        
        return JsonResponse({
            'analise_basica': {
                'rms_total': round(rms_total, 3),
                'rms_mm_s': round(vel_rms, 2),
                'crest_factor': round(crest_factor, 2),
                'kurtosis': round(kurtosis_val, 3),
                'severidade': severidade,
                'recomendacao': recomendacao,
                'frequencia_dominante_x': round(freq_dominante, 1),
                'energia_alta_freq': round(energia_alta_freq, 2),
                'razao_harmonico': round(razao_harmonico, 3)
            },
            'analise_avancada': {
                'energia_alta_freq': round(energia_alta_freq, 2),
                'razao_harmonico': round(razao_harmonico, 3),
                'condicao_rolamento': condicao_rolamento,
                'condicao_mancal': condicao_mancal
            },
            'diagnostico': {
                'recomendacao': recomendacao,
                'condicao_rolamento': condicao_rolamento,
                'condicao_mancal': condicao_mancal,
                'nivel_alerta': nivel_alerta
            }
        })
        
    except Exception as e:
        return JsonResponse({'erro': str(e)}, status=500)


# =========================
# DADOS FFT PARA GRÁFICO
# =========================
def get_fft_data(request, motor_id):
    """Retorna dados FFT para gerar grafico no frontend"""
    try:
        if motor_id not in buffers or len(buffers[motor_id]['x']) < BUFFER_SIZE:
            return JsonResponse({'erro': 'Amostras insuficientes para FFT'}, status=400)
        
        # Calcular FFT
        x_data = np.array(buffers[motor_id]['x']) - np.mean(buffers[motor_id]['x'])
        window = np.hanning(len(x_data))
        x_windowed = x_data * window
        
        fs = 100
        freq = fftfreq(BUFFER_SIZE, 1/fs)[:BUFFER_SIZE//2]
        fft_x = np.abs(fft(x_windowed))[:BUFFER_SIZE//2]
        
        # Retornar dados para grafico
        dados_fft = [
            {'freq': round(freq[i], 1), 'amp': round(fft_x[i], 5)}
            for i in range(len(freq))
            if i > 0 and i < 100  # ate 100 Hz
        ]
        
        return JsonResponse({
            'fft_data': dados_fft,
            'freq_max': round(freq[np.argmax(fft_x[1:]) + 1], 1) if len(fft_x) > 1 else 0,
            'amp_max': round(np.max(fft_x[1:]), 5) if len(fft_x) > 1 else 0
        })
        
    except Exception as e:
        return JsonResponse({'erro': str(e)}, status=500)


# =========================
# LISTAR MOTORES
# =========================
def motores_listar(request):
    motores = Motor.objects.all().order_by('id')

    lista = []
    for m in motores:
        lista.append({
            'id': m.id,
            'nome': m.nome,
            'marca': m.marca,
            'rpm': m.rpm,
            'frequencia': m.frequencia,
            'cv': m.cv
        })

    return JsonResponse(lista, safe=False)


# =========================
# CRIAR MOTOR
# =========================
@csrf_exempt
def motor_criar(request):
    if request.method != 'POST':
        return JsonResponse({'erro': 'método não permitido'}, status=405)

    try:
        data = json.loads(request.body)
        
        id_desejado = data.get('id_desejado', None)
        
        if id_desejado:
            if Motor.objects.filter(id=id_desejado).exists():
                return JsonResponse({
                    'erro': f'O ID {id_desejado} já está em uso.'
                }, status=400)
            
            motor = Motor(
                id=id_desejado,
                nome=data.get('nome', ''),
                marca=data.get('marca', ''),
                rpm=int(data.get('rpm', 0)),
                frequencia=float(data.get('frequencia', 0)),
                cv=float(data.get('cv', 0))
            )
            motor.save()
            
            return JsonResponse({
                'id': motor.id,
                'mensagem': f'Motor criado com sucesso com ID {motor.id}'
            }, status=201)
        else:
            motor = Motor.objects.create(
                nome=data.get('nome', ''),
                marca=data.get('marca', ''),
                rpm=int(data.get('rpm', 0)),
                frequencia=float(data.get('frequencia', 0)),
                cv=float(data.get('cv', 0))
            )
            
            return JsonResponse({
                'id': motor.id,
                'mensagem': 'Motor criado com sucesso'
            }, status=201)

    except Exception as e:
        return JsonResponse({'erro': str(e)}, status=400)


# =========================
# OBTER MOTOR
# =========================
def motor_obter(request, motor_id):
    try:
        motor = Motor.objects.get(id=motor_id)

        return JsonResponse({
            'id': motor.id,
            'nome': motor.nome,
            'marca': motor.marca,
            'rpm': motor.rpm,
            'frequencia': motor.frequencia,
            'cv': motor.cv
        })

    except Motor.DoesNotExist:
        return JsonResponse({'erro': 'Motor não encontrado'}, status=404)


# =========================
# ATUALIZAR MOTOR
# =========================
@csrf_exempt
def motor_atualizar(request, motor_id):
    if request.method != 'PUT':
        return JsonResponse({'erro': 'método não permitido'}, status=405)

    try:
        motor = Motor.objects.get(id=motor_id)
        data = json.loads(request.body)

        motor.nome = data.get('nome', motor.nome)
        motor.marca = data.get('marca', motor.marca)
        motor.rpm = int(data.get('rpm', motor.rpm))
        motor.frequencia = float(data.get('frequencia', motor.frequencia))
        motor.cv = float(data.get('cv', motor.cv))
        motor.save()

        return JsonResponse({'mensagem': 'Motor atualizado com sucesso'})

    except Motor.DoesNotExist:
        return JsonResponse({'erro': 'Motor não encontrado'}, status=404)

    except Exception as e:
        return JsonResponse({'erro': str(e)}, status=400)


# =========================
# EXCLUIR MOTOR
# =========================
@csrf_exempt
def motor_excluir(request, motor_id):
    if request.method != 'DELETE':
        return JsonResponse({'erro': 'método não permitido'}, status=405)

    try:
        motor = Motor.objects.get(id=motor_id)
        motor.delete()

        return JsonResponse({'mensagem': 'Motor excluído com sucesso'})

    except Motor.DoesNotExist:
        return JsonResponse({'erro': 'Motor não encontrado'}, status=404)


# =========================
# PEGAR ÚLTIMO MOTOR
# =========================
def ultimo_motor(request):
    motor = Motor.objects.last()

    if not motor:
        return JsonResponse({'erro': 'nenhum motor cadastrado'}, status=404)

    return JsonResponse({
        'id': motor.id,
        'nome': motor.nome,
        'marca': motor.marca,
        'rpm': motor.rpm,
        'frequencia': motor.frequencia,
        'cv': motor.cv
    })