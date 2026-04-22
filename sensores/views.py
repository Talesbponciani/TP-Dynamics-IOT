from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
import json

from .models import Leitura, Motor


# =========================
# DASHBOARD
# =========================
def dashboard(request):
    return render(request, 'dashboard.html')


# =========================
# RECEBER DADOS DO ESP32
# =========================
@csrf_exempt
def receber_dados(request):
    if request.method != 'POST':
        return JsonResponse({'erro': 'somente POST'}, status=405)

    try:
        data = json.loads(request.body)

        # 🔥 pega motor_id
        motor_id = data.get('motor_id')
        motor = None

        if motor_id:
            motor = Motor.objects.filter(id=motor_id).first()

        # 🔥 cria leitura
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
# LISTAR MOTORES
# =========================
def motores_listar(request):
    motores = Motor.objects.all().order_by('id')  # Mudado para order_by('id')

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
# CRIAR MOTOR (CORRIGIDO PARA REUTILIZAR IDs)
# =========================
@csrf_exempt
def motor_criar(request):
    if request.method != 'POST':
        return JsonResponse({'erro': 'método não permitido'}, status=405)

    try:
        data = json.loads(request.body)
        
        # Verificar se o frontend enviou um ID desejado
        id_desejado = data.get('id_desejado', None)
        
        if id_desejado:
            # Verificar se o ID já existe
            if Motor.objects.filter(id=id_desejado).exists():
                return JsonResponse({
                    'erro': f'O ID {id_desejado} já está em uso. IDs são reutilizados automaticamente.'
                }, status=400)
            
            # Criar motor com o ID específico (reutilizando ID deletado)
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
                'mensagem': f'Motor criado com sucesso com ID {motor.id} (ID reutilizado)'
            }, status=201)
        else:
            # Criar motor com ID automático (sem especificar)
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