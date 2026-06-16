from django.apps import AppConfig
from django.db.backends.signals import connection_created


def _register_unicode_case(sender, connection, **kwargs):
    """SQLite по умолчанию умеет lower()/upper() только для ASCII.
    Регистрируем Python-функции, чтобы Lower('name') и LIKE … COLLATE NOCASE
    работали для кириллицы (умный поиск, регистронезависимое сравнение)."""
    if connection.vendor != 'sqlite':
        return
    raw = connection.connection
    raw.create_function('lower', 1,
        lambda s: s.lower() if isinstance(s, str) else s, deterministic=True)
    raw.create_function('upper', 1,
        lambda s: s.upper() if isinstance(s, str) else s, deterministic=True)


class ShopConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'shop'

    def ready(self):
        connection_created.connect(_register_unicode_case)
