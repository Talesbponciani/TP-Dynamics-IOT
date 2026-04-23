from django.db import models

# =========================
# MODELO DO MOTOR
# =========================
class Motor(models.Model):
    nome = models.CharField(max_length=100)
    marca = models.CharField(max_length=100)
    rpm = models.IntegerField()
    frequencia = models.FloatField()
    cv = models.FloatField(default=0.0)

    def __str__(self):
        return f"[{self.id}] {self.nome} - {self.marca}"


# =========================
# MODELO DE LEITURA
# =========================
class Leitura(models.Model):
    motor = models.ForeignKey(Motor, on_delete=models.CASCADE, null=True, blank=True)
    data = models.DateTimeField(auto_now_add=True)
    temperatura = models.FloatField()
    vibX = models.FloatField()
    vibY = models.FloatField()
    vibZ = models.FloatField()
    rms = models.FloatField()      # Agora armazena VELOCIDADE em mm/s
    crest = models.FloatField()

    def __str__(self):
        motor_nome = self.motor.nome if self.motor else "Sem motor"
        return f"{self.data.strftime('%d/%m/%Y %H:%M:%S')} - {motor_nome} - Vel: {self.rms:.2f} mm/s"