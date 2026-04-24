from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
import json

@csrf_exempt  # Necessário para permitir que o ESP32 envie dados sem erro de segurança CSRF
def receber_bruto(request):
    if request.method == 'POST':
        try:
            # Pega os dados enviados (JSON)
            dados = json.loads(request.body)
            
            # --- SUA LÓGICA PARA SALVAR NO POSTGRES AQUI ---
            # Exemplo: RegistroVibracao.objects.create(valor=dados['valor'])
            
            return JsonResponse({"message": "Dados recebidos"}, status=201)
        except Exception as e:
            return JsonResponse({"error": str(e)}, status=400)
            
    return JsonResponse({"error": "Metodo nao permitido"}, status=405)