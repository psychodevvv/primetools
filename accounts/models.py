from django.contrib.auth.hashers import check_password, make_password
from django.db import models


class Customer(models.Model):
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100, blank=True)
    phone = models.CharField(max_length=30, unique=True)
    password = models.CharField(max_length=128, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Покупатель'
        verbose_name_plural = 'Покупатели'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.full_name()} ({self.phone})'

    def full_name(self):
        return f'{self.first_name} {self.last_name}'.strip()

    def set_password(self, raw):
        self.password = make_password(raw)

    def check_password(self, raw):
        if not self.password:
            return False
        return check_password(raw, self.password)
