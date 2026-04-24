from django.http import JsonResponse
from django.shortcuts import render, get_object_or_404
from django.views.decorators.csrf import csrf_exempt
# ... (restante dos imports do Django que já estavam lá)

# Esta é a forma correta para o SEU projeto:
API_KEY_PROTECTED = "259319"

def validar_acesso(request):
    token = request.headers.get('X-API-KEY')
    return token == API_KEY_PROTECTED

@app.route('/api/receber_bruto/', methods=['POST'])
def receber_bruto():
    # Verifica a chave enviada pelo ESP32
    if request.headers.get('X-API-KEY') != API_KEY:
        return jsonify({"error": "Chave invalida"}), 403
    
    dados = request.get_json()
    # Lógica para salvar no Postgres...
    return jsonify({"message": "Dados recebidos"}), 201