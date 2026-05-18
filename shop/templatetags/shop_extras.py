from django import template

register = template.Library()

# Неразрывный пробел — разделяет разряды и не разрывается при переносе строки.
_NBSP = ' '


@register.filter
def money(value):
    """Форматирует число с разделением разрядов: 111111 -> '111 111'."""
    try:
        number = int(round(float(value)))
    except (TypeError, ValueError):
        return value
    return '{:,}'.format(number).replace(',', _NBSP)
