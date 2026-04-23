# =========================
# ANÁLISE COMPLETA ESTILO SKF (CORRIGIDA)
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
# DADOS FFT PARA GRÁFICO (CORRIGIDA)
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
                }, status=200)  # Retorna 200 mas sem dados
            
            # Retornar dados parciais
            return JsonResponse({
                'erro': f'Aguardando mais {BUFFER_SIZE - amostras_atual} amostras para FFT',
                'fft_data': [],
                'freq_max': 0,
                'amp_max': 0,
                'amostras_atual': amostras_atual,
                'amostras_necessarias': BUFFER_SIZE
            }, status=200)  # Retorna 200 em vez de 400
        
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
