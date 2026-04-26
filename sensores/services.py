import os
from twilio.rest import Client

def enviar_alerta_whatsapp(motor_nome, valor_vibracao, severidade):
    # O Render vai ler estas chaves que você configurou lá
    account_sid = os.getenv('TWILIO_ACCOUNT_SID')
    auth_token = os.getenv('TWILIO_AUTH_TOKEN')
    from_whatsapp_number = os.getenv('TWILIO_FROM_NUMBER')
    # Pode ser um número ou vários separados por vírgula
    to_numbers = os.getenv('MY_WHATSAPP_NUMBERS', '').split(',')

    client = Client(account_sid, auth_token)

    mensagem = (
        f"\n⚠️ *ALERTA DE VIBRAÇÃO* ⚠️\n\n"
        f"📌 *Equipamento:* {motor_nome}\n"
        f"📊 *Valor:* {valor_vibracao} mm/s\n"
        f"🚨 *Status:* {severidade}\n\n"
        f"Verifique o painel de monitoramento imediatamente."
    )

    for number in to_numbers:
        if number.strip():
            client.messages.create(
                body=mensagem,
                from_=from_whatsapp_number,
                to=number.strip()
            )