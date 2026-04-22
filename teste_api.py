import requests

url = "http://127.0.0.1:8000/api/dados/"

dados = {
    "temperatura": 33.5,
    "vibX": 1.1,
    "vibY": 0.9,
    "vibZ": 0.7,
    "rms": 1.8,
    "crest": 2.3
}

resposta = requests.post(url, json=dados)

print("Status:", resposta.status_code)
print("Resposta:", resposta.text)