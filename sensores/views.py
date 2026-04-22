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
import os

from .models import Leitura, Motor

# ========== BUFFERS GLOBAIS ==========
buffers = {}
BUFFER_SIZE = 256  # 256 amostras para FFT

# Buffer para armazenar dados de velocidade (integração)
vel_buffers = {}
VEL_BUFFER_SIZE = 50  # Tamanho do buffer para média móvel

# Arquivo para armazenar os offsets de calibração
OFFSETS_FILE = 'offsets.json'


# =========================
# DASHBOARD
# =========================
def dashboard(request):
    return render(request, 'dashboard.html')


# =========================
# SALVAR OFFSETS DE CALIBRAÇÃO
# =========================
@csrf_exempt
def salvar_offset(request):
    """Salva os offsets de calibração de um motor no servidor"""
    if request.method != 'POST':
        return JsonResponse({'erro': 'somente POST'}, status=405)

    try:
        data = json.loads(request.body)
        motor_id = data.get('motor_id')
        offset_x = data.get('offset_x', 0)
        offset_y = data.get('offset_y', 0)
        offset_z = data.get('offset_z', 0)
        
        if motor_id is None:
            return JsonResponse({'erro': 'motor_id é obrigatório'}, status=400)
        
        offsets = {}
        if os.path.exists(OFFSETS_FILE):
            try:
                with open(OFFSETS_FILE, 'r') as f:
                    offsets = json.load(f)
            except:
                offsets = {}
        
        offsets[str(motor_id)] = {
            'offset_x': float(offset_x),
            'offset_y': float(offset_y),
            'offset_z': float(offset_z),
            'timestamp': datetime.now().isoformat()
        }
        
        with open(OFFSETS_FILE, 'w') as f:
            json.dump(offsets, f, indent=2)
        
        print(f"✅ Offsets do motor {motor_id} salvos: X={offset_x}, Y={offset_y}, Z={offset_z}")
        
        return JsonResponse({
            'status': 'ok',
            'mensagem': f'Offsets do motor {motor_id} salvos no servidor',
            'offsets': {'offset_x': offset_x, 'offset_y': offset_y, 'offset_z': offset_z}
        }, status=200)
        
    except Exception as e:
        return JsonResponse({'erro': str(e)}, status=500)


# =========================
# CARREGAR OFFSETS DE CALIBRAÇÃO
# =========================
@csrf_exempt
def carregar_offset(request, motor_id):
    """Carrega os offsets de calibração de um motor do servidor"""
    try:
        if not os.path.exists(OFFSETS_FILE):
            return JsonResponse({'erro': 'Nenhum offset salvo no servidor'}, status=404)
        
        with open(OFFSETS_FILE, 'r') as f:
            offsets = json.load(f)
        
        motor_key = str(motor_id)
        if motor_key not in offsets:
            return JsonResponse({'erro': f'Motor {motor_id} não tem offset salvo'}, status=404)
        
        offset_data = offsets[motor_key]
        
        print(f"📦 Offsets do motor {motor_id} carregados: X={offset_data['offset_x']}, Y={offset_data['offset_y']}, Z={offset_data['offset_z']}")
        
        return JsonResponse({
            'status': 'ok',
            'motor_id': motor_id,
            'offset_x': offset_data['offset_x'],
            'offset_y': offset_data['offset_y'],
            'offset_z': offset_data['offset_z'],
            'timestamp': offset_data.get('timestamp', '')
        }, status=200)
        
    except Exception as e:
        return JsonResponse({'erro': str(e)}, status=500)


# =========================
# LISTAR OFFSETS (DEBUG)
# =========================
@csrf_exempt
def listar_offsets(request):
    try:
        if not os.path.exists(OFFSETS_FILE):
            return JsonResponse({'offsets': {}}, status=200)
        with open(OFFSETS_FILE, 'r') as f:
            offsets = json.load(f)
        return JsonResponse({'offsets': offsets}, status=200)
    except Exception as e:
        return JsonResponse({'erro': str(e)}, status=500)


# =========================
# RECEBER DADOS COM CÁLCULOS NO ESP32
# =========================
@csrf_exempt
def receber_dados(request):
    if request.method != 'POST':
        return JsonResponse({'erro': 'somente POST'}, status=405)

    try:
        data = json.loads(request.body)
        motor_id = data.get('motor_id')
        motor = Motor.objects.filter(id=motor_id).first() if motor_id else None

        leitura = Leitura.objects.create(
            motor=motor,
            temperatura=float(data.get('temperatura', 0)),
            vibX=float(data.get('vibX', 0)),
            vibY=float(data.get('vibY', 0)),
            vibZ=float(data.get('vibZ', 0)),
            rms=float(data.get('rms', 0)),
            crest=float(data.get('crest', 0))
        )

        return JsonResponse({'status': 'ok', 'id': leitura.id}, status=201)
    except Exception as e:
        return JsonResponse({'status': 'erro', 'msg': str(e)}, status=500)


# =========================
# RECEBER DADOS BRUTOS - CÁLCULO CORRETO DA VELOCIDADE (mm/s)
# =========================
@csrf_exempt
def receber_dados_brutos(request):
    """Recebe dados brutos do ESP32 e calcula VELOCIDADE REAL em mm/s (comparável com SKF)"""
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
        
        # Inicializar buffers para este motor
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
        
        # ===== CÁLCULOS BÁSICOS =====
        # Aceleração RMS (m/s²)
        rms_aceleracao = math.sqrt((vibX**2 + vibY**2 + vibZ**2) / 3)
        pico = max(abs(vibX), abs(vibY), abs(vibZ))
        crest_factor = pico / rms_aceleracao if rms_aceleracao > 0 else 0
        
        # Kurtosis
        amostras = [vibX, vibY, vibZ]
        if np.std(amostras) > 0:
            kurtosis = stats.kurtosis(amostras, fisher=True)
        else:
            kurtosis = 0
        
        # ===== CÁLCULO CORRETO DA VELOCIDADE (mm/s) - INTEGRAÇÃO =====
        if motor_id not in vel_buffers:
            vel_buffers[motor_id] = {
                'vel_x': 0,
                'vel_y': 0,
                'vel_z': 0,
                'last_acc_x': 0,
                'last_acc_y': 0,
                'last_acc_z': 0,
                'last_time': None,
                'filtered_x': 0,
                'filtered_y': 0,
                'filtered_z': 0,
                'prev_x': 0,
                'prev_y': 0,
                'prev_z': 0,
                'vel_history': deque(maxlen=VEL_BUFFER_SIZE)
            }
        
        vel_data = vel_buffers[motor_id]
        now = datetime.now().timestamp()
        
        # Filtro passa-alta (remove gravidade e DC offset)
        alpha = 0.95
        
        vel_data['filtered_x'] = alpha * (vel_data['filtered_x'] + vibX - vel_data['prev_x'])
        vel_data['filtered_y'] = alpha * (vel_data['filtered_y'] + vibY - vel_data['prev_y'])
        vel_data['filtered_z'] = alpha * (vel_data['filtered_z'] + vibZ - vel_data['prev_z'])
        
        vel_data['prev_x'] = vibX
        vel_data['prev_y'] = vibY
        vel_data['prev_z'] = vibZ
        
        # Calcular dt
        if vel_data['last_time'] is None:
            dt = 0.1
        else:
            dt = min(now - vel_data['last_time'], 0.1)
        
        # Converter aceleração de m/s² para mm/s²
        acc_x_mm = vel_data['filtered_x'] * 1000.0
        acc_y_mm = vel_data['filtered_y'] * 1000.0
        acc_z_mm = vel_data['filtered_z'] * 1000.0
        
        # Integração (Regra do Trapézio)
        vel_data['vel_x'] += (acc_x_mm + vel_data['last_acc_x']) / 2.0 * dt
        vel_data['vel_y'] += (acc_y_mm + vel_data['last_acc_y']) / 2.0 * dt
        vel_data['vel_z'] += (acc_z_mm + vel_data['last_acc_z']) / 2.0 * dt
        
        vel_data['last_acc_x'] = acc_x_mm
        vel_data['last_acc_y'] = acc_y_mm
        vel_data['last_acc_z'] = acc_z_mm
        vel_data['last_time'] = now
        
        # Reset automático se motor parado
        if rms_aceleracao < 0.1:
            vel_data['vel_x'] = 0
            vel_data['vel_y'] = 0
            vel_data['vel_z'] = 0
        
        # Velocidade RMS total (mm/s)
        vel_rms = math.sqrt(vel_data['vel_x']**2 + vel_data['vel_y']**2 + vel_data['vel_z']**2)
        
        # Média móvel para suavizar
        vel_data['vel_history'].append(vel_rms)
        if len(vel_data['vel_history']) > 0:
            vel_rms_suavizada = sum(vel_data['vel_history']) / len(vel_data['vel_history'])
        else:
            vel_rms_suavizada = vel_rms
        
        # ===== SEVERIDADE - ISO 10816 (Velocidade em mm/s) =====
        if vel_rms_suavizada < 1.0:
            severidade = "Boa"
            recomendacao = "Operacao normal"
        elif vel_rms_suavizada < 2.8:
            severidade = "Aceitavel"
            recomendacao = "Monitorar tendencia"
        elif vel_rms_suavizada < 4.5:
            severidade = "Insatisfatoria"
            recomendacao = "Planejar manutencao"
        else:
            severidade = "Perigosa"
            recomendacao = "PARAR EQUIPAMENTO IMEDIATAMENTE"
        
        alerta = vel_rms_suavizada > 4.5
        
        # Criar leitura (rms agora é a VELOCIDADE em mm/s)
        leitura = Leitura.objects.create(
            motor=motor,
            temperatura=round(temperatura, 1),
            vibX=round(vibX, 3),
            vibY=round(vibY, 3),
            vibZ=round(vibZ, 3),
            rms=round(vel_rms_suavizada, 3),
            crest=round(crest_factor, 2)
        )
        
        print(f"📊 Motor {motor_id}: Acel RMS={rms_aceleracao:.3f} m/s² | Velocidade={vel_rms_suavizada:.2f} mm/s | {severidade}")
        
        return JsonResponse({
            'status': 'ok',
            'id': leitura.id,
            'calculos': {
                'aceleracao_rms': round(rms_aceleracao, 3),
                'velocidade_mm_s': round(vel_rms_suavizada, 2),
                'velocidade_instantanea': round(vel_rms, 2),
                'crest_factor': round(crest_factor, 2),
                'kurtosis': round(kurtosis, 3),
                'severidade': severidade,
                'recomendacao': recomendacao,
                'alerta': alerta
            }
        }, status=201)

    except Exception as e:
        print(f"❌ Erro: {str(e)}")
        return JsonResponse({'erro': str(e)}, status=500)


# =========================
# DADOS PARA GRÁFICO (com velocidade em mm/s)
# =========================
def dados_json(request):
    motor_id = request.GET.get('motor_id')

    if motor_id:
        dados = Leitura.objects.select_related('motor').filter(motor_id=motor_id).order_by('-id')[:50]
    else:
        dados = Leitura.objects.select_related('motor').all().order_by('-id')[:50]

    lista = []
    for d in reversed(dados):
        # Calcular aceleração RMS a partir dos valores brutos
        acel_rms = math.sqrt((float(d.vibX or 0)**2 + float(d.vibY or 0)**2 + float(d.vibZ or 0)**2) / 3)
        
        lista.append({
            "data": d.data.strftime("%H:%M:%S") if d.data else "",
            "motor_id": d.motor.id if d.motor else None,
            "temperatura": float(d.temperatura or 0),
            "velocidade_mm_s": float(d.rms or 0),  # Velocidade em mm/s (comparável com SKF)
            "aceleracao_rms": round(acel_rms, 3),
            "vibX": float(d.vibX or 0),
            "vibY": float(d.vibY or 0),
            "vibZ": float(d.vibZ or 0)
        })

    return JsonResponse(lista, safe=False)


# =========================
# RESETAR VELOCIDADE (DEBUG)
# =========================
def resetar_velocidade(request, motor_id):
    if motor_id in vel_buffers:
        vel_buffers[motor_id]['vel_x'] = 0
        vel_buffers[motor_id]['vel_y'] = 0
        vel_buffers[motor_id]['vel_z'] = 0
        vel_buffers[motor_id]['vel_history'].clear()
        return JsonResponse({'status': 'ok', 'mensagem': f'Velocidade do motor {motor_id} resetada'})
    return JsonResponse({'erro': 'Motor não encontrado'}, status=404)


# =========================
# ANÁLISE COMPLETA ESTILO SKF
# =========================
def get_analise_completa(request, motor_id):
    try:
        if motor_id not in buffers or len(buffers[motor_id]['x']) < BUFFER_SIZE:
            return JsonResponse({'erro': 'Amostras insuficientes para analise'}, status=400)
        
        x_data = np.array(buffers[motor_id]['x']) - np.mean(buffers[motor_id]['x'])
        y_data = np.array(buffers[motor_id]['y']) - np.mean(buffers[motor_id]['y'])
        z_data = np.array(buffers[motor_id]['z']) - np.mean(buffers[motor_id]['z'])
        
        # FFT
        fs = 100
        freq = fftfreq(BUFFER_SIZE, 1/fs)[:BUFFER_SIZE//2]
        
        window = np.hanning(BUFFER_SIZE)
        x_windowed = x_data * window
        fft_x = np.abs(fft(x_windowed))[:BUFFER_SIZE//2]
        
        # Métricas
        rms_total = np.sqrt(np.mean(x_data**2))
        pico = np.max(np.abs(x_data))
        crest_factor = pico / rms_total if rms_total > 0 else 0
        kurtosis_val = stats.kurtosis(x_data, fisher=True)
        
        # Frequência dominante
        freq_dominante = freq[np.argmax(fft_x[1:]) + 1] if len(fft_x) > 1 else 0
        
        # Energia em altas frequências
        alta_freq_inicio = int(10 * BUFFER_SIZE / fs)
        energia_alta_freq = np.sum(fft_x[alta_freq_inicio:]) if alta_freq_inicio < len(fft_x) else 0
        
        # Razão harmônica
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
        
        # Condições
        if kurtosis_val > 3 or energia_alta_freq > 50:
            condicao_rolamento = "Falha detectada - Inspecionar"
        elif kurtosis_val > 2:
            condicao_rolamento = "Atencao - Monitorar"
        else:
            condicao_rolamento = "Normal"
        
        if razao_harmonico > 0.5:
            condicao_mancal = "Possivel desalinhamento - Verificar"
        elif razao_harmonico > 0.3:
            condicao_mancal = "Atencao - Monitorar"
        else:
            condicao_mancal = "Normal"
        
        return JsonResponse({
            'analise_basica': {
                'rms_total': round(rms_total, 3),
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
                'nivel_alerta': "CRITICO" if severidade == "Perigosa" else ("ALERTA" if severidade == "Insatisfatoria" else "NORMAL")
            }
        })
        
    except Exception as e:
        return JsonResponse({'erro': str(e)}, status=500)


# =========================
# DADOS FFT PARA GRÁFICO
# =========================
def get_fft_data(request, motor_id):
    try:
        if motor_id not in buffers or len(buffers[motor_id]['x']) < BUFFER_SIZE:
            return JsonResponse({'erro': 'Amostras insuficientes para FFT'}, status=400)
        
        x_data = np.array(buffers[motor_id]['x']) - np.mean(buffers[motor_id]['x'])
        window = np.hanning(len(x_data))
        x_windowed = x_data * window
        
        fs = 100
        freq = fftfreq(BUFFER_SIZE, 1/fs)[:BUFFER_SIZE//2]
        fft_x = np.abs(fft(x_windowed))[:BUFFER_SIZE//2]
        
        dados_fft = [
            {'freq': round(freq[i], 1), 'amp': round(fft_x[i], 5)}
            for i in range(len(freq)) if i > 0 and i < 100
        ]
        
        return JsonResponse({
            'fft_data': dados_fft,
            'freq_max': round(freq[np.argmax(fft_x[1:]) + 1], 1) if len(fft_x) > 1 else 0,
            'amp_max': round(np.max(fft_x[1:]), 5) if len(fft_x) > 1 else 0
        })
        
    except Exception as e:
        return JsonResponse({'erro': str(e)}, status=500)


# =========================
# CRUD DE MOTORES
# =========================
def motores_listar(request):
    motores = Motor.objects.all().order_by('id')
    lista = [{'id': m.id, 'nome': m.nome, 'marca': m.marca, 'rpm': m.rpm, 'frequencia': m.frequencia, 'cv': m.cv} for m in motores]
    return JsonResponse(lista, safe=False)


@csrf_exempt
def motor_criar(request):
    if request.method != 'POST':
        return JsonResponse({'erro': 'método não permitido'}, status=405)
    try:
        data = json.loads(request.body)
        id_desejado = data.get('id_desejado', None)
        
        if id_desejado and Motor.objects.filter(id=id_desejado).exists():
            return JsonResponse({'erro': f'O ID {id_desejado} já está em uso.'}, status=400)
        
        if id_desejado:
            motor = Motor(id=id_desejado, nome=data.get('nome', ''), marca=data.get('marca', ''),
                         rpm=int(data.get('rpm', 0)), frequencia=float(data.get('frequencia', 0)),
                         cv=float(data.get('cv', 0)))
            motor.save()
            return JsonResponse({'id': motor.id, 'mensagem': f'Motor criado com ID {motor.id}'}, status=201)
        else:
            motor = Motor.objects.create(nome=data.get('nome', ''), marca=data.get('marca', ''),
                                        rpm=int(data.get('rpm', 0)), frequencia=float(data.get('frequencia', 0)),
                                        cv=float(data.get('cv', 0)))
            return JsonResponse({'id': motor.id, 'mensagem': 'Motor criado com sucesso'}, status=201)
    except Exception as e:
        return JsonResponse({'erro': str(e)}, status=400)


def motor_obter(request, motor_id):
    try:
        motor = Motor.objects.get(id=motor_id)
        return JsonResponse({'id': motor.id, 'nome': motor.nome, 'marca': motor.marca,
                            'rpm': motor.rpm, 'frequencia': motor.frequencia, 'cv': motor.cv})
    except Motor.DoesNotExist:
        return JsonResponse({'erro': 'Motor não encontrado'}, status=404)


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


@csrf_exempt
def motor_excluir(request, motor_id):
    if request.method != 'DELETE':
        return JsonResponse({'erro': 'método não permitido'}, status=405)
    try:
        motor = Motor.objects.get(id=motor_id)
        if motor_id in buffers:
            del buffers[motor_id]
        if motor_id in vel_buffers:
            del vel_buffers[motor_id]
        motor.delete()
        return JsonResponse({'mensagem': 'Motor excluído com sucesso'})
    except Motor.DoesNotExist:
        return JsonResponse({'erro': 'Motor não encontrado'}, status=404)


def ultimo_motor(request):
    motor = Motor.objects.last()
    if not motor:
        return JsonResponse({'erro': 'nenhum motor cadastrado'}, status=404)
    return JsonResponse({'id': motor.id, 'nome': motor.nome, 'marca': motor.marca,
                        'rpm': motor.rpm, 'frequencia': motor.frequencia, 'cv': motor.cv})