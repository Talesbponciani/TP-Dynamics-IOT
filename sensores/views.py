from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
import json
import math
import os
from collections import deque
from datetime import datetime
from pathlib import Path

# Tentar importar numpy e scipy
try:
    import numpy as np
    from scipy.fft import fft, fftfreq
    from scipy import stats
    SCIPY_AVAILABLE = True
except ImportError:
    SCIPY_AVAILABLE = False
    np = None
    stats = None

from .models import Leitura, Motor

# ========== BUFFERS ==========
buffers = {}
BUFFER_SIZE = 50

# Arquivo para offsets
BASE_DIR = Path(__file__).resolve().parent.parent
OFFSETS_FILE = BASE_DIR / 'offsets.json'


# ========== VIEWS ==========
def dashboard(request):
    """View principal que renderiza o dashboard HTML"""
    return render(request, 'dashboard.html')


def calcular_estatisticas_sem_scipy(amostras):
    """Fallback para quando scipy não está disponível"""
    if not amostras or len(amostras) == 0:
        return {'rms': 0, 'kurtosis': 0}
    
    n = len(amostras)
    media = sum(amostras) / n
    variancia = sum((x - media) ** 2 for x in amostras) / n
    rms = math.sqrt(variancia)
    
    # Kurtosis simplificado
    if variancia > 0:
        momento4 = sum((x - media) ** 4 for x in amostras) / n
        kurtosis = momento4 / (variancia ** 2) - 3
    else:
        kurtosis = 0
    
    return {'rms': rms, 'kurtosis': kurtosis}


# =========================
# DADOS PARA GRÁFICO
# =========================
def dados_json(request):
    """Retorna dados para os gráficos"""
    motor_id = request.GET.get('motor_id')
    if motor_id:
        dados = Leitura.objects.filter(motor_id=motor_id).order_by('-id')[:50]
    else:
        dados = Leitura.objects.all().order_by('-id')[:50]
    
    lista = []
    for d in reversed(dados):
        lista.append({
            "data": d.data.strftime("%H:%M:%S") if d.data else "",
            "motor_id": d.motor.id if d.motor else None,
            "temperatura": float(d.temperatura or 0),
            "velocidade_mm_s": float(d.rms or 0),
            "vibX": float(d.vibX or 0),
            "vibY": float(d.vibY or 0),
            "vibZ": float(d.vibZ or 0)
        })
    return JsonResponse(lista, safe=False)


# =========================
# CRUD DE MOTORES
# =========================
def motores_listar(request):
    """Lista todos os motores"""
    motores = Motor.objects.all().order_by('id')
    lista = [{'id': m.id, 'nome': m.nome, 'marca': m.marca, 'rpm': m.rpm, 'frequencia': m.frequencia, 'cv': m.cv} for m in motores]
    return JsonResponse(lista, safe=False)


@csrf_exempt
def motor_criar(request):
    """Cria um novo motor"""
    if request.method != 'POST':
        return JsonResponse({'erro': 'método não permitido'}, status=405)
    try:
        data = json.loads(request.body)
        id_desejado = data.get('id_desejado')
        if id_desejado and Motor.objects.filter(id=id_desejado).exists():
            return JsonResponse({'erro': f'ID {id_desejado} já em uso'}, status=400)
        
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
            return JsonResponse({'id': motor.id, 'mensagem': 'Motor criado'}, status=201)
    except Exception as e:
        return JsonResponse({'erro': str(e)}, status=400)


def motor_obter(request, motor_id):
    """Obtém um motor específico"""
    try:
        motor = Motor.objects.get(id=motor_id)
        return JsonResponse({'id': motor.id, 'nome': motor.nome, 'marca': motor.marca,
                            'rpm': motor.rpm, 'frequencia': motor.frequencia, 'cv': motor.cv})
    except Motor.DoesNotExist:
        return JsonResponse({'erro': 'Motor não encontrado'}, status=404)


@csrf_exempt
def motor_atualizar(request, motor_id):
    """Atualiza um motor"""
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
        return JsonResponse({'mensagem': 'Motor atualizado'})
    except Motor.DoesNotExist:
        return JsonResponse({'erro': 'Motor não encontrado'}, status=404)
    except Exception as e:
        return JsonResponse({'erro': str(e)}, status=400)


@csrf_exempt
def motor_excluir(request, motor_id):
    """Exclui um motor"""
    if request.method != 'DELETE':
        return JsonResponse({'erro': 'método não permitido'}, status=405)
    try:
        motor = Motor.objects.get(id=motor_id)
        if motor_id in buffers:
            del buffers[motor_id]
        motor.delete()
        return JsonResponse({'mensagem': 'Motor excluído'})
    except Motor.DoesNotExist:
        return JsonResponse({'erro': 'Motor não encontrado'}, status=404)


def ultimo_motor(request):
    """Retorna o último motor cadastrado"""
    motor = Motor.objects.last()
    if not motor:
        return JsonResponse({'erro': 'nenhum motor cadastrado'}, status=404)
    return JsonResponse({'id': motor.id, 'nome': motor.nome, 'marca': motor.marca,
                        'rpm': motor.rpm, 'frequencia': motor.frequencia, 'cv': motor.cv})


# =========================
# SALVAR OFFSETS
# =========================
@csrf_exempt
def salvar_offset(request):
    """Salva offsets de calibração"""
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
            with open(OFFSETS_FILE, 'r') as f:
                offsets = json.load(f)
        
        offsets[str(motor_id)] = {
            'offset_x': float(offset_x),
            'offset_y': float(offset_y),
            'offset_z': float(offset_z),
            'timestamp': datetime.now().isoformat()
        }
        
        with open(OFFSETS_FILE, 'w') as f:
            json.dump(offsets, f, indent=2)
        
        return JsonResponse({'status': 'ok', 'mensagem': f'Offsets do motor {motor_id} salvos'}, status=200)
    except Exception as e:
        return JsonResponse({'erro': str(e)}, status=500)


@csrf_exempt
def carregar_offset(request, motor_id):
    """Carrega offsets salvos"""
    try:
        if not os.path.exists(OFFSETS_FILE):
            return JsonResponse({'erro': 'Nenhum offset salvo'}, status=404)
        with open(OFFSETS_FILE, 'r') as f:
            offsets = json.load(f)
        motor_key = str(motor_id)
        if motor_key not in offsets:
            return JsonResponse({'erro': f'Motor {motor_id} não tem offset'}, status=404)
        offset_data = offsets[motor_key]
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


@csrf_exempt
def listar_offsets(request):
    """Lista todos os offsets"""
    try:
        if not os.path.exists(OFFSETS_FILE):
            return JsonResponse({'offsets': {}}, status=200)
        with open(OFFSETS_FILE, 'r') as f:
            offsets = json.load(f)
        return JsonResponse({'offsets': offsets}, status=200)
    except Exception as e:
        return JsonResponse({'erro': str(e)}, status=500)


# =========================
# RECEBER DADOS
# =========================
@csrf_exempt
def receber_dados(request):
    """Recebe dados do ESP32"""
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


@csrf_exempt
def receber_dados_brutos(request):
    """Recebe dados brutos do ESP32 e calcula métricas"""
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
        
        # Cálculos básicos
        rms_total = math.sqrt((vibX**2 + vibY**2 + vibZ**2) / 3)
        pico = max(abs(vibX), abs(vibY), abs(vibZ))
        crest_factor = pico / rms_total if rms_total > 0 else 0
        vel_rms = rms_total * 9.81 / (2 * math.pi * 60) * 1000
        
        leitura = Leitura.objects.create(
            motor=motor,
            temperatura=round(temperatura, 1),
            vibX=round(vibX, 3),
            vibY=round(vibY, 3),
            vibZ=round(vibZ, 3),
            rms=round(vel_rms, 3),
            crest=round(crest_factor, 2)
        )
        
        return JsonResponse({'status': 'ok', 'id': leitura.id}, status=201)
    except Exception as e:
        return JsonResponse({'erro': str(e)}, status=500)


# =========================
# ANÁLISE COMPLETA ESTILO SKF
# =========================
def get_analise_completa(request, motor_id):
    try:
        # Verificar se tem amostras suficientes
        if motor_id not in buffers or len(buffers[motor_id]['x']) < BUFFER_SIZE:
            # Retornar análise simplificada com os dados disponíveis
            amostras_atual = len(buffers.get(motor_id, {}).get('x', []))
            
            # Se não tem nenhum dado, retornar erro amigável
            if amostras_atual == 0:
                return JsonResponse({
                    'erro': 'Aguardando primeiras leituras do sensor...',
                    'amostras_atual': 0,
                    'amostras_necessarias': BUFFER_SIZE
                }, status=400)
            
            # Calcular com os dados disponíveis (análise simplificada)
            x_data_list = list(buffers[motor_id]['x'])
            rms_total = math.sqrt(sum(v**2 for v in x_data_list) / len(x_data_list))
            vel_rms = rms_total * 9.81 / (2 * math.pi * 60) * 1000
            
            # Severidade
            if vel_rms < 1.0:
                severidade = "Boa"
                recomendacao = "Operacao normal"
            elif vel_rms < 2.8:
                severidade = "Aceitavel"
                recomendacao = "Monitorar tendencia"
            elif vel_rms < 4.5:
                severidade = "Insatisfatoria"
                recomendacao = "Planejar manutencao"
            else:
                severidade = "Perigosa"
                recomendacao = "PARAR EQUIPAMENTO IMEDIATAMENTE"
            
            return JsonResponse({
                'analise_basica': {
                    'rms_total': round(rms_total, 3),
                    'rms_mm_s': round(vel_rms, 2),
                    'severidade': severidade,
                    'recomendacao': recomendacao,
                    'frequencia_dominante_x': 0,
                    'energia_alta_freq': 0,
                    'razao_harmonico': 0
                },
                'analise_avancada': {
                    'condicao_rolamento': 'Aguardando dados',
                    'condicao_mancal': 'Aguardando dados'
                },
                'diagnostico': {
                    'recomendacao': f'Aguardando mais {BUFFER_SIZE - amostras_atual} amostras para análise completa',
                    'nivel_alerta': 'INFO'
                },
                'status': 'parcial',
                'amostras_atual': amostras_atual,
                'amostras_necessarias': BUFFER_SIZE
            })
        
        # Verificar se scipy está disponível
        if not SCIPY_AVAILABLE or np is None:
            # Retornar análise simplificada sem FFT
            x_data_list = list(buffers[motor_id]['x'])
            rms_total = math.sqrt(sum(v**2 for v in x_data_list) / len(x_data_list))
            vel_rms = rms_total * 9.81 / (2 * math.pi * 60) * 1000
            
            if vel_rms < 1.0:
                severidade = "Boa"
                recomendacao = "Operacao normal"
            elif vel_rms < 2.8:
                severidade = "Aceitavel"
                recomendacao = "Monitorar tendencia"
            elif vel_rms < 4.5:
                severidade = "Insatisfatoria"
                recomendacao = "Planejar manutencao"
            else:
                severidade = "Perigosa"
                recomendacao = "PARAR EQUIPAMENTO IMEDIATAMENTE"
            
            return JsonResponse({
                'analise_basica': {
                    'rms_total': round(rms_total, 3),
                    'rms_mm_s': round(vel_rms, 2),
                    'severidade': severidade,
                    'recomendacao': recomendacao,
                },
                'diagnostico': {
                    'recomendacao': recomendacao,
                    'nivel_alerta': 'ALERTA' if vel_rms > 4.5 else 'NORMAL'
                }
            })
        
        # Converter para arrays numpy
        x_data = np.array(buffers[motor_id]['x'])
        y_data = np.array(buffers[motor_id]['y'])
        z_data = np.array(buffers[motor_id]['z'])
        
        # Remover média (DC offset)
        x_data = x_data - np.mean(x_data)
        y_data = y_data - np.mean(y_data)
        z_data = z_data - np.mean(z_data)
        
        # Aplicar janela de Hann
        window = np.hanning(BUFFER_SIZE)
        x_windowed = x_data * window
        
        # Calcular FFT
        fs = 10  # Taxa de amostragem (Hz)
        freq = fftfreq(BUFFER_SIZE, 1/fs)[:BUFFER_SIZE//2]
        fft_x = np.abs(fft(x_windowed))[:BUFFER_SIZE//2]
        
        # Métricas
        rms_total = np.sqrt(np.mean(x_data**2))
        pico = np.max(np.abs(x_data))
        crest_factor = pico / rms_total if rms_total > 0 else 0
        kurtosis_val = stats.kurtosis(x_data, fisher=True)
        
        # Velocidade em mm/s
        vel_rms = rms_total * 9.81 / (2 * math.pi * 60) * 1000
        
        # Frequência dominante
        if len(fft_x) > 1:
            idx_max = np.argmax(fft_x[1:]) + 1
            freq_dominante = freq[idx_max] if idx_max < len(freq) else 0
        else:
            freq_dominante = 0
        
        # Energia em altas frequências
        alta_freq_inicio = int(10 * BUFFER_SIZE / fs)
        energia_alta_freq = np.sum(fft_x[alta_freq_inicio:]) if alta_freq_inicio < len(fft_x) else 0
        
        # Razão harmônica
        freq_fundamental = 60
        idx_fund = int(freq_fundamental * BUFFER_SIZE / fs)
        if idx_fund < len(fft_x) and idx_fund > 0:
            amp_fund = fft_x[idx_fund]
            amp_2harm = fft_x[min(2*idx_fund, len(fft_x)-1)] if 2*idx_fund < len(fft_x) else 0
            razao_harmonico = amp_2harm / amp_fund if amp_fund > 0 else 0
        else:
            razao_harmonico = 0
        
        # Severidade
        if vel_rms < 1.0:
            severidade = "Boa"
            recomendacao = "Operacao normal"
        elif vel_rms < 2.8:
            severidade = "Aceitavel"
            recomendacao = "Monitorar tendencia"
        elif vel_rms < 4.5:
            severidade = "Insatisfatoria"
            recomendacao = "Planejar manutencao"
        else:
            severidade = "Perigosa"
            recomendacao = "PARAR EQUIPAMENTO IMEDIATAMENTE"
        
        # Condição de rolamento
        if kurtosis_val > 3 or energia_alta_freq > 50:
            condicao_rolamento = "Falha detectada - Inspecionar"
        elif kurtosis_val > 2:
            condicao_rolamento = "Atencao - Monitorar"
        else:
            condicao_rolamento = "Normal"
        
        # Condição de desalinhamento
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
            },
            'status': 'completo'
        })
    except Exception as e:
        return JsonResponse({'erro': str(e), 'status': 'erro'}, status=500)


# =========================
# DADOS FFT PARA GRÁFICO
# =========================
def get_fft_data(request, motor_id):
    try:
        # Verificar se tem amostras suficientes
        if motor_id not in buffers or len(buffers[motor_id]['x']) < BUFFER_SIZE:
            amostras_atual = len(buffers.get(motor_id, {}).get('x', []))
            
            # Se não tem nenhum dado, retornar vazio
            if amostras_atual == 0:
                return JsonResponse({
                    'erro': 'Aguardando primeiras leituras...',
                    'fft_data': [],
                    'freq_max': 0,
                    'amp_max': 0,
                    'amostras_atual': 0
                }, status=200)
            
            # Retornar dados parciais
            return JsonResponse({
                'erro': f'Aguardando mais {BUFFER_SIZE - amostras_atual} amostras para FFT',
                'fft_data': [],
                'freq_max': 0,
                'amp_max': 0,
                'amostras_atual': amostras_atual,
                'amostras_necessarias': BUFFER_SIZE
            }, status=200)
        
        if not SCIPY_AVAILABLE or np is None:
            return JsonResponse({
                'erro': 'FFT não disponível - bibliotecas não instaladas',
                'fft_data': [],
                'freq_max': 0,
                'amp_max': 0
            })
        
        # Calcular FFT
        x_data = np.array(buffers[motor_id]['x']) - np.mean(buffers[motor_id]['x'])
        window = np.hanning(len(x_data))
        x_windowed = x_data * window
        
        fs = 10  # Taxa de amostragem (Hz)
        freq = fftfreq(BUFFER_SIZE, 1/fs)[:BUFFER_SIZE//2]
        fft_x = np.abs(fft(x_windowed))[:BUFFER_SIZE//2]
        
        # Retornar dados para gráfico
        dados_fft = []
        for i in range(1, len(freq)):
            if freq[i] <= 50:
                dados_fft.append({'freq': round(freq[i], 1), 'amp': round(float(fft_x[i]), 5)})
        
        # Encontrar frequência dominante
        if len(fft_x) > 1:
            idx_max = np.argmax(fft_x[1:]) + 1
            freq_max = freq[idx_max] if idx_max < len(freq) else 0
            amp_max = float(fft_x[idx_max]) if idx_max < len(fft_x) else 0
        else:
            freq_max = 0
            amp_max = 0
        
        return JsonResponse({
            'fft_data': dados_fft,
            'freq_max': round(freq_max, 1),
            'amp_max': round(amp_max, 5),
            'status': 'completo'
        })
    except Exception as e:
        return JsonResponse({
            'erro': str(e),
            'fft_data': [],
            'freq_max': 0,
            'amp_max': 0
        }, status=200)