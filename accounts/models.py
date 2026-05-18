from django.db import models


class Customer(models.Model):
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100, blank=True)
    phone = models.CharField(max_length=30, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Покупатель'
        verbose_name_plural = 'Покупатели'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.full_name()} ({self.phone})'

    def full_name(self):
        return f'{self.first_name} {self.last_name}'.strip()
