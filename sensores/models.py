from django.db import models

# =========================
# MODELO DO MOTOR
# =========================
class Motor(models.Model):
    nome = models.CharField(max_length=100)
    marca = models.CharField(max_length=100)
    rpm = models.IntegerField()
    frequencia = models.FloatField()
    cv = models.FloatField(default=0.0)  # potência em cavalos

    def __str__(self):
        return self.nome


# =========================
# MODELO DE LEITURA
# =========================
class Leitura(models.Model):
    # 🔥 RELAÇÃO COM MOTOR (temporariamente opcional)
    motor = models.ForeignKey(Motor, on_delete=models.CASCADE, null=True, blank=True)

    data = models.DateTimeField(auto_now_add=True)
    temperatura = models.FloatField()
    vibX = models.FloatField()
    vibY = models.FloatField()
    vibZ = models.FloatField()
    rms = models.FloatField()
    crest = models.FloatField()