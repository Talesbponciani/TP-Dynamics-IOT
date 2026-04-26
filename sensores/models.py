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
    
    # ADICIONE ESTAS DUAS LINHAS ABAIXO:
    limite_alerta = models.FloatField(default=4.5)
    ultimo_alerta_enviado = models.DateTimeField(null=True, blank=True)

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
    rms = models.FloatField()  # Armazena VELOCIDADE em mm/s
    crest = models.FloatField()

    def __str__(self):
        motor_nome = self.motor.nome if self.motor else "Sem motor"
        return f"{self.data.strftime('%d/%m/%Y %H:%M:%S')} - {motor_nome} - Vel: {self.rms:.2f} mm/s"


# =========================
# MODELO DE CALIBRAÇÃO (Offsets persistentes)
# =========================
class MotorCalibration(models.Model):
    motor = models.OneToOneField(Motor, on_delete=models.CASCADE, primary_key=True)
    offset_x = models.FloatField(default=0.0)
    offset_y = models.FloatField(default=0.0)
    offset_z = models.FloatField(default=0.0)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Calibração do Motor {self.motor.id} - {self.motor.nome}"