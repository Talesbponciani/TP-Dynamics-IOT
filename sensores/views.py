from django.http import JsonResponse
from django.shortcuts import render, get_object_or_404
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone
from django.db.models import Avg, Count, Max, Min
from django.db.models.functions import TruncHour
from django.contrib.auth.models import User
from django.http import HttpResponse
import json
import math
import numpy as np
from scipy.fft import fft, fftfreq
from scipy import stats
from collections import deque
from datetime import datetime, timedelta
import csv

from .services import enviar_alerta_whatsapp
from .models import Leitura, Motor, MotorCalibration

# ========== BUFFERS EM MEMÓRIA ==========
buffers = {}
BUFFER_SIZE = 200
vel_buffers = {}
VEL_BUFFER_SIZE = 200
TAXA_AMOSTRAGEM = 100
# ============================================================
# VIEW PRINCIPAL
# ============================================================

def dashboard(request):
    return render(request, 'dashboard.html')

# ============================================================
# RECEBIMENTO DE DADOS DO ESP32 (VERSÃO CORRIGIDA)
# ============================================================

@csrf_exempt
def receber_dados_brutos(request):
    """
    Recebe dados do ESP32, processa vibração/RMS e 
    SALVA no histórico do banco de dados automaticamente.
    VERSÃO CORRIGIDA - RMS com buffer adequado
    """
    if request.method != 'POST':
        return JsonResponse({'erro': 'Metodo negado'}, status=405)

    try:
        data = json.loads(request.body)
        motor_id = data.get('motor_id')
        temperatura = float(data.get('temperatura', 0))
        vibX = float(data.get('vibX', 0))
        vibY = float(data.get('vibY', 0))
        vibZ = float(data.get('vibZ', 0))
        
        # 1. Verifica se o motor existe
        motor = Motor.objects.filter(id=motor_id).first()
        if not motor:
            return JsonResponse({'erro': 'Motor não encontrado'}, status=404)
        
        # 2. Gestão de Buffers (AUMENTADO para 200 amostras)
        motor_id_str = str(motor_id)
        BUFFER_SIZE_RMS = 200  # ← 200 amostras para RMS estável
        
        if motor_id_str not in buffers:
            buffers[motor_id_str] = {
                'x': deque(maxlen=BUFFER_SIZE_RMS),
                'y': deque(maxlen=BUFFER_SIZE_RMS),
                'z': deque(maxlen=BUFFER_SIZE_RMS),
                'tempo': deque(maxlen=BUFFER_SIZE_RMS),
                'todas_amostras': deque(maxlen=BUFFER_SIZE_RMS)  # Para RMS combinado
            }
        
        # Adiciona as 3 novas amostras
        buffers[motor_id_str]['x'].append(vibX)
        buffers[motor_id_str]['y'].append(vibY)
        buffers[motor_id_str]['z'].append(vibZ)
        
        # Cria uma lista com TODAS as amostras dos 3 eixos para RMS robusto
        todas_amostras = []
        todas_amostras.extend(buffers[motor_id_str]['x'])
        todas_amostras.extend(buffers[motor_id_str]['y'])
        todas_amostras.extend(buffers[motor_id_str]['z'])
        buffers[motor_id_str]['todas_amostras'] = deque(todas_amostras, maxlen=BUFFER_SIZE_RMS)
        
        # 3. ✅ CÁLCULO DO RMS CORRETO (com todas as amostras do buffer)
        if len(buffers[motor_id_str]['todas_amostras']) >= 30:  # Mínimo 30 amostras
            # RMS verdadeiro sobre todo o buffer
            rms_aceleracao = np.sqrt(np.mean(np.square(buffers[motor_id_str]['todas_amostras'])))
        else:
            # Fallback para as primeiras leituras
            rms_aceleracao = math.sqrt((vibX**2 + vibY**2 + vibZ**2) / 3)
        
        # 4. Cálculos Técnicos com o RMS correto
        pico = max(abs(vibX), abs(vibY), abs(vibZ))
        crest_factor = pico / rms_aceleracao if rms_aceleracao > 0 else 0
        
        # Kurtosis agora usando o buffer (mais estável)
        if len(buffers[motor_id_str]['todas_amostras']) >= 30:
            amostras_array = np.array(buffers[motor_id_str]['todas_amostras'])
            kurtosis = stats.kurtosis(amostras_array, fisher=True) if np.std(amostras_array) > 0 else 0
        else:
            amostras = [vibX, vibY, vibZ]
            kurtosis = stats.kurtosis(amostras, fisher=True) if np.std(amostras) > 0 else 0
        
        # Severidade (velocidade RMS)
        freq_trabalho = motor.frequencia if motor.frequencia else 60
        vel_rms = rms_aceleracao * 9.81 / (2 * math.pi * freq_trabalho) * 1000
        
        # 5. ✅ LÓGICA DE ALERTA COM HISTERESE (NOVO!)
        score = 0
        
        # Critério 1: Velocidade RMS (com histerese)
        if vel_rms >= 4.5:
            score = 2
        elif vel_rms >= 2.8:
            score = max(score, 1)
        
        # Critério 2: Crest Factor
        if crest_factor > 5.0:
            score = max(score, 2)
        elif crest_factor >= 3.0:
            score = max(score, 1)
        
        # Critério 3: Kurtosis
        if kurtosis > 8.0:
            score = max(score, 2)
        elif kurtosis >= 3.0:
            score = max(score, 1)
        
        # ✅ ADICIONA HISTERESE TEMPORAL (evita oscilação)
        # Armazena o último estado no buffer
        if 'ultimo_score' not in buffers[motor_id_str]:
            buffers[motor_id_str]['ultimo_score'] = 0
            buffers[motor_id_str]['contador_estavel'] = 0
        
        # Só muda o estado se mantiver por 3 leituras consecutivas
        if score == buffers[motor_id_str]['ultimo_score']:
            buffers[motor_id_str]['contador_estavel'] += 1
        else:
            buffers[motor_id_str]['contador_estavel'] = 0
            buffers[motor_id_str]['ultimo_score'] = score
        
        # Aplica o estado apenas após 3 confirmações
        if buffers[motor_id_str]['contador_estavel'] >= 3:
            score_final = score
        else:
            score_final = buffers[motor_id_str]['ultimo_score']
        
        # Atribuir resultados com estado estável
        if score_final >= 2:
            severidade = "Perigosa"
            rec = "PARAR EQUIPAMENTO IMEDIATAMENTE"
        elif score_final >= 1:
            severidade = "Insatisfatória"
            rec = "Planejar manutenção"
        else:
            severidade = "Boa"
            rec = "Operação normal"
        
        # 6. WhatsApp Alerts (com cooldown)
        limite_rms = motor.limite_alerta if hasattr(motor, 'limite_alerta') else 4.5
        limite_kurt = motor.limite_kurtosis if hasattr(motor, 'limite_kurtosis') else 3.5
        
        # Só envia alerta se score_final for consistente (não oscilante)
        if score_final >= 1:  # Alerta ou Crítico consistente
            agora = timezone.now()
            if not motor.ultimo_alerta_enviado or agora > motor.ultimo_alerta_enviado + timedelta(minutes=30):
                if vel_rms > limite_rms:
                    motivo = f"Energia Elevada (RMS: {vel_rms:.2f} mm/s)"
                else:
                    motivo = f"Impacto Detectado (Kurtosis: {kurtosis:.2f})"
                
                enviar_alerta_whatsapp(
                    motor.nome, 
                    f"RMS: {vel_rms:.2f} / Kurt: {kurtosis:.2f}", 
                    motivo
                )
                motor.ultimo_alerta_enviado = agora
                motor.save()
        
        # 7. Salva no Banco (aqui você pode salvar o RMS estável)
        leitura = Leitura.objects.create(
            motor=motor,
            temperatura=round(temperatura, 1),
            vibX=round(vibX, 3),
            vibY=round(vibY, 3),
            vibZ=round(vibZ, 3),
            rms=round(rms_aceleracao, 3),
            crest=round(crest_factor, 2)
        )
        
        return JsonResponse({
            'status': 'ok',
            'id': leitura.id,
            'calculos': {
                'aceleracao_rms': round(rms_aceleracao, 3),
                'velocidade_mm_s': round(vel_rms, 2),
                'kurtosis': round(kurtosis, 2),
                'severidade': severidade,
                'recomendacao': rec,
                'alerta': (score_final >= 1),
                'estado_estavel': score_final  # Para debug
            }
        }, status=201)

    except Exception as e:
        return JsonResponse({'erro': str(e)}, status=500)
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
        
        return JsonResponse({
            'status': 'ok', 
            'mensagem': f'Offsets do motor {m_id} persistidos no banco',
            'atualizado': not created
        }, status=200)
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

@csrf_exempt
def listar_offsets(request):
    try:
        calibracoes = MotorCalibration.objects.all()
        offsets = {str(c.motor.id): {
            'offset_x': c.offset_x,
            'offset_y': c.offset_y,
            'offset_z': c.offset_z,
            'timestamp': c.updated_at.isoformat()
        } for c in calibracoes}
        return JsonResponse({'offsets': offsets}, status=200)
    except Exception as e:
        return JsonResponse({'erro': str(e)}, status=500)

# ============================================================
# DADOS PARA DASHBOARD
# ============================================================

def dados_json(request):
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
            "rms": float(d.rms or 0),
            "vibX": float(d.vibX or 0),
            "vibY": float(d.vibY or 0),
            "vibZ": float(d.vibZ or 0)
        })
    return JsonResponse(lista, safe=False)

def dados_historico_hora_json(request):
    motor_id = request.GET.get('motor_id')
    
    if not motor_id:
        return JsonResponse([], safe=False)
    
    dados_agrupados = Leitura.objects.filter(
        motor_id=motor_id
    ).annotate(
        hora=TruncHour('data')
    ).values('hora').annotate(
        temperatura_media=Avg('temperatura'),
        temperatura_max=Max('temperatura'),
        temperatura_min=Min('temperatura'),
        rms_medio=Avg('rms'),
        rms_max=Max('rms'),
        vibX_medio=Avg('vibX'),
        vibY_medio=Avg('vibY'),
        vibZ_medio=Avg('vibZ'),
        total_leituras=Count('id')
    ).order_by('-hora')[:168]
    
    lista = []
    for item in reversed(dados_agrupados):
        if item['hora']:
            lista.append({
                "data": item['hora'].strftime("%d/%m/%Y %H:00"),
                "data_iso": item['hora'].isoformat(),
                "motor_id": int(motor_id),
                "temperatura_media": round(float(item['temperatura_media'] or 0), 1),
                "temperatura_max": round(float(item['temperatura_max'] or 0), 1),
                "temperatura_min": round(float(item['temperatura_min'] or 0), 1),
                "rms_medio": round(float(item['rms_medio'] or 0), 3),
                "rms_max": round(float(item['rms_max'] or 0), 3),
                "vibX_medio": round(float(item['vibX_medio'] or 0), 3),
                "vibY_medio": round(float(item['vibY_medio'] or 0), 3),
                "vibZ_medio": round(float(item['vibZ_medio'] or 0), 3),
                "leituras_hora": item['total_leituras']
            })
    
    return JsonResponse(lista, safe=False)

def dados_brutos_json(request):
    motor_id = request.GET.get('motor_id')
    dados = Leitura.objects.filter(motor_id=motor_id).order_by('-id')[:100] if motor_id else Leitura.objects.all().order_by('-id')[:100]
    
    lista = [{
        "data": d.data.strftime("%H:%M:%S") if d.data else "",
        "data_completa": d.data.isoformat(),
        "motor_id": d.motor.id if d.motor else None,
        "temperatura": float(d.temperatura or 0),
        "rms": float(d.rms or 0),
        "vibX": float(d.vibX or 0),
        "vibY": float(d.vibY or 0),
        "vibZ": float(d.vibZ or 0)
    } for d in reversed(dados)]
    return JsonResponse(lista, safe=False)

# ============================================================
# ANÁLISE FFT E SKF COMPLETA
# ============================================================

def get_analise_completa(request, motor_id):
    try:
        motor = get_object_or_404(Motor, id=motor_id)
        
        m_id = str(motor_id)
        
        # VERIFICA SE TEM AMOSTRAS SUFICIENTES
        if m_id not in buffers or len(buffers[m_id]['x']) < BUFFER_SIZE:
            return JsonResponse({
                'erro': f'Aguardando {len(buffers[m_id]["x"]) if m_id in buffers else 0}/{BUFFER_SIZE} amostras para FFT...'
            }, status=400)
        
        # Remove DC component (média) e aplica janela Hanning
        x_data = np.array(buffers[m_id]['x']) - np.mean(buffers[m_id]['x'])
        window = np.hanning(BUFFER_SIZE)
        dados_janelados = x_data * window
        
        # CALCULA FFT
        fs = TAXA_AMOSTRAGEM
        freqs = fftfreq(BUFFER_SIZE, 1/fs)[:BUFFER_SIZE//2]
        fft_x = np.abs(fft(dados_janelados))[:BUFFER_SIZE//2]
        
        # 🔥 CORREÇÃO: Encontra frequência dominante (ignorando DC e ruído muito baixo)
        # Ignora frequências abaixo de 1 Hz (evita pegar componente DC)
        indices_validos = np.where(freqs >= 1.0)[0]
        if len(indices_validos) == 0 or len(fft_x) == 0:
            freq_dominante = 0
        else:
            fft_validas = fft_x[indices_validos]
            freq_validas = freqs[indices_validos]
            idx_max = np.argmax(fft_validas)
            freq_dominante = freq_validas[idx_max]
        
        # MÉTRICAS BÁSICAS
        rms_total = np.sqrt(np.mean(x_data**2))
        freq_trabalho = motor.frequencia if motor.frequencia else 60
        vel_rms = rms_total * 9.81 / (2 * math.pi * freq_trabalho) * 1000
        kurtosis_val = stats.kurtosis(x_data, fisher=True)
        pico = np.max(np.abs(x_data))
        crest_factor = pico / rms_total if rms_total > 0 else 0
        
        # DIAGNÓSTICOS
        cond_rolamento = "Falha - Inspecionar" if kurtosis_val > 3.0 else "Normal"
        cond_mancal = "Desalinhamento Provável" if (np.sum(fft_x[1:10]) > 50) else "Normal"
        
        # SEVERIDADE (baseado na velocidade RMS)
        if vel_rms >= 4.5:
            severidade_texto = "CRÍTICO"
            cor = "#e74c3c"
            diagnostico_msg = "⚠️ CRÍTICO - Parar equipamento imediatamente!"
        elif vel_rms >= 2.8:
            severidade_texto = "ALERTA"
            cor = "#f39c12"
            diagnostico_msg = "⚠️ ALERTA - Planejar manutenção"
        else:
            severidade_texto = "NORMAL"
            cor = "#2ecc71"
            diagnostico_msg = "✅ NORMAL - Operação segura"

        return JsonResponse({
            'analise_basica': {
                'rms_total': round(rms_total, 3),
                'rms_mm_s': round(vel_rms, 2),
                'kurtosis': round(kurtosis_val, 3),
                'crest_factor': round(crest_factor, 2),
                'freq_dominante': round(float(freq_dominante), 1) if freq_dominante > 0 else 0
            },
            'diagnostico': {
                'condicao_rolamento': cond_rolamento,
                'condicao_mancal': cond_mancal,
                'alerta': severidade_texto,
                'severidade': severidade_texto,
                'mensagem': diagnostico_msg,
                'cor': cor
            }
        })
    except Exception as e:
        return JsonResponse({'erro': str(e)}, status=500)

def get_fft_data(request, motor_id):
    try:
        m_id = str(motor_id)
        
        # VERIFICA SE TEM AMOSTRAS SUFICIENTES
        if m_id not in buffers or len(buffers[m_id]['x']) < BUFFER_SIZE:
            return JsonResponse({
                'labels': [], 
                'amplitudes': [], 
                'status': 'aguardando',
                'mensagem': f'Aguardando {len(buffers[m_id]["x"]) if m_id in buffers else 0}/{BUFFER_SIZE} amostras para gerar FFT...'
            })
        
        # Remove DC component (média)
        x_data = np.array(buffers[m_id]['x']) - np.mean(buffers[m_id]['x'])
        
        # Aplica janela Hanning para reduzir vazamento espectral
        window = np.hanning(BUFFER_SIZE)
        dados_janelados = x_data * window
        
        # CALCULA FFT
        fft_completa = fft(dados_janelados)
        fft_res = np.abs(fft_completa)[:BUFFER_SIZE//2]  # Pega só metade (simétrica)
        
        # CALCULA FREQUÊNCIAS
        fs = TAXA_AMOSTRAGEM
        freqs = fftfreq(BUFFER_SIZE, 1/fs)[:BUFFER_SIZE//2]
        
        # 🔥 LIMITA PARA FREQUÊNCIAS RELEVANTES (até 50 Hz para motores)
        # Motores típicos operam entre 0-50 Hz (0-3000 RPM)
        limite_freq = 50
        indices = np.where(freqs <= limite_freq)[0]
        
        # Pega apenas os pontos dentro do limite
        labels = [round(freqs[i], 1) for i in indices]
        amplitudes = [round(fft_res[i], 5) for i in indices]
        
        # Encontra a amplitude máxima para debug (opcional)
        max_amplitude = max(amplitudes) if amplitudes else 0
        freq_max = labels[amplitudes.index(max_amplitude)] if amplitudes and max_amplitude > 0 else 0
        
        return JsonResponse({
            'labels': labels,
            'amplitudes': amplitudes,
            'status': 'ok',
            'info': {
                'total_amostras': BUFFER_SIZE,
                'frequencia_max_hz': freq_max,
                'amplitude_max': round(max_amplitude, 5),
                'taxa_amostragem': fs
            }
        })
        
    except Exception as e:
        return JsonResponse({
            'labels': [], 
            'amplitudes': [], 
            'status': 'erro',
            'erro': str(e)
        }, status=500)

# ============================================================
# CRUD DE MOTORES
# ============================================================

def motores_listar(request):
    motores = Motor.objects.all().order_by('id')
    lista = [{'id': m.id, 'nome': m.nome, 'marca': m.marca, 'rpm': m.rpm, 'cv': m.cv, 'frequencia': m.frequencia} for m in motores]
    return JsonResponse(lista, safe=False)

@csrf_exempt
def motor_criar(request):
    if request.method != 'POST': 
        return JsonResponse({'erro': 'metodo negado'}, status=405)
    data = json.loads(request.body)
    motor = Motor.objects.create(
        id=data.get('id_desejado'),
        nome=data.get('nome'), 
        marca=data.get('marca'),
        rpm=int(data.get('rpm', 0)), 
        cv=float(data.get('cv', 0)),
        frequencia=float(data.get('frequencia', 0))
    )
    return JsonResponse({'id': motor.id, 'mensagem': 'Criado'}, status=201)

def motor_obter(request, motor_id):
    m = get_object_or_404(Motor, id=motor_id)
    return JsonResponse({'id': m.id, 'nome': m.nome, 'marca': m.marca, 'rpm': m.rpm, 'frequencia': m.frequencia, 'cv': m.cv})

@csrf_exempt
def motor_excluir(request, motor_id):
    motor = get_object_or_404(Motor, id=motor_id)
    motor.delete()
    return JsonResponse({'mensagem': 'Excluido'})

def ultimo_motor(request):
    m = Motor.objects.last()
    if not m: 
        return JsonResponse({'erro': 'vazio'}, status=404)
    return JsonResponse({'id': m.id, 'nome': m.nome})

@csrf_exempt
def motor_atualizar(request, motor_id):
    if request.method != 'PUT':
        return JsonResponse({'erro': 'Método inválido'}, status=405)

    try:
        data = json.loads(request.body)
        motor = get_object_or_404(Motor, id=motor_id)

        motor.nome = data.get('nome', motor.nome)
        motor.marca = data.get('marca', motor.marca)
        motor.rpm = int(data.get('rpm', motor.rpm))
        motor.cv = float(data.get('cv', motor.cv))
        motor.frequencia = float(data.get('frequencia', motor.frequencia))

        motor.save()
        return JsonResponse({'status': 'ok', 'mensagem': 'Motor atualizado'})

    except Exception as e:
        return JsonResponse({'erro': str(e)}, status=500)

# ============================================================
# UTILITÁRIOS
# ============================================================

def resetar_tudo_emergencia(request):
    u, created = User.objects.get_or_create(username='admin')
    u.set_password('admin123')
    u.is_superuser = True
    u.is_staff = True
    u.save()
    
    Motor.objects.all().update(ultimo_alerta_enviado=None)
    
    return HttpResponse("<h1>Sucesso!</h1><p>Usuário 'admin' resetado para senha 'admin123' e WhatsApp destravado.</p>")

def exportar_dados_csv(request):
    try:
        motor_id = request.GET.get('motor_id')
        vinte_quatro_horas_atras = timezone.now() - timedelta(hours=24)
        
        response = HttpResponse(content_type='text/csv; charset=utf-8-sig')
        filename = f"historico_grafico_24h_motor_{motor_id}.csv"
        response['Content-Disposition'] = f'attachment; filename="{filename}"'

        writer = csv.writer(response, delimiter=';')
        
        dados_agrupados = Leitura.objects.filter(
            motor_id=motor_id,
            data__gte=vinte_quatro_horas_atras
        ).annotate(
            hora=TruncHour('data')
        ).values('hora').annotate(
            temp_media=Avg('temperatura'),
            rms_medio=Avg('rms'),
            vibX_media=Avg('vibX'),
            vibY_media=Avg('vibY'),
            vibZ_media=Avg('vibZ')
        ).order_by('hora')

        writer.writerow(['--- TEMPERATURA MÉDIA POR HORA (24H) ---'])
        writer.writerow(['Horário', 'Média (°C)'])
        for ponto in dados_agrupados:
            writer.writerow([
                ponto['hora'].strftime('%d/%m/%Y %H:00'), 
                str(round(ponto['temp_media'], 2)).replace('.', ',')
            ])
        
        writer.writerow([])
        
        writer.writerow(['--- RMS MÉDIO POR HORA (24H) ---'])
        writer.writerow(['Horário', 'Média (m/s²)'])
        for ponto in dados_agrupados:
            writer.writerow([
                ponto['hora'].strftime('%d/%m/%Y %H:00'), 
                str(round(ponto['rms_medio'], 2)).replace('.', ',')
            ])

        return response

    except Exception as e:
        return HttpResponse(f"Erro ao gerar dados do gráfico: {e}", status=500)
    

from django.shortcuts import render
from .models import Motor

def status_motores(request):
    motores = Motor.objects.all()
    return render(request, 'status_motores.html', {'motores': motores})

from django.shortcuts import render
from .models import Motor, Leitura

def status_motores(request):
    motores = Motor.objects.all()

    motores_com_dados = []

    for motor in motores:
        ultima_leitura = Leitura.objects.filter(motor=motor).order_by('-data').first()

        motores_com_dados.append({
            'motor': motor,
            'leitura': ultima_leitura
        })

    return render(request, 'status_motores.html', {
        'motores': motores_com_dados
    })

from django.shortcuts import render
from .models import Motor

def status_motores(request):
    motores = Motor.objects.all()
    return render(request, 'status_motores.html', {'motores': motores})

def verificar_status_motor(request, motor_id):
    """
    Verifica se o motor está enviando dados ativamente
    Retorna status baseado na última leitura recebida
    """
    try:
        motor = get_object_or_404(Motor, id=motor_id)
        
        # Busca a última leitura
        ultima_leitura = Leitura.objects.filter(motor=motor).order_by('-data').first()
        
        if not ultima_leitura:
            return JsonResponse({
                'status': 'sem_dados',
                'online': False,
                'conectado': False,
                'ultima_leitura': None,
                'segundos_desde_ultima': None,
                'mensagem': 'Nenhuma leitura recebida ainda'
            })
        
        # Calcula o tempo desde a última leitura
        agora = timezone.now()
        tempo_desde_ultima = (agora - ultima_leitura.data).total_seconds()
        
        # Define 60 segundos como timeout para considerar desconectado
        TIMEOUT_SEGUNDOS = 15
        
        if tempo_desde_ultima > TIMEOUT_SEGUNDOS:
            return JsonResponse({
                'status': 'desconectado',
                'online': False,
                'conectado': False,
                'ultima_leitura': ultima_leitura.data.isoformat(),
                'segundos_desde_ultima': int(tempo_desde_ultima),
                'mensagem': f'ESP desconectado há {int(tempo_desde_ultima)} segundos'
            })
        else:
            return JsonResponse({
                'status': 'conectado',
                'online': True,
                'conectado': True,
                'ultima_leitura': ultima_leitura.data.isoformat(),
                'segundos_desde_ultima': int(tempo_desde_ultima),
                'mensagem': f'ESP conectado - última leitura há {int(tempo_desde_ultima)}s'
            })
            
    except Exception as e:
        return JsonResponse({'erro': str(e)}, status=500)