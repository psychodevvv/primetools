"""Отправка кодов подтверждения по SMS.

Если SMS-шлюз не настроен в .env (SMS_API_KEY / SMS_API_URL) — работает
демо-режим: код не отправляется, а показывается на экране (для разработки).
Для боевого режима подключите SMS-провайдера (mobizon.kz, smsc.kz и т.п.).
"""
import random

import requests
from django.conf import settings


def generate_code():
    """Случайный 4-значный код."""
    return f'{random.randint(1000, 9999)}'


def send_code(phone, code):
    """Отправляет код на номер. Возвращает True, если SMS реально отправлено."""
    api_key = getattr(settings, 'SMS_API_KEY', '')
    api_url = getattr(settings, 'SMS_API_URL', '')
    if not api_key or not api_url:
        return False  # демо-режим — код покажем на экране
    try:
        requests.post(api_url, timeout=8, data={
            'apiKey': api_key,
            'recipient': phone,
            'text': f'Код подтверждения: {code}',
            'from': getattr(settings, 'SMS_SENDER', ''),
        })
        return True
    except requests.RequestException:
        return False
