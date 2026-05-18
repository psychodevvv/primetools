import requests
from django.conf import settings


def send_order_notification(order):
    token = settings.TELEGRAM_BOT_TOKEN
    chat_id = settings.TELEGRAM_ADMIN_CHAT_ID

    if not token or not chat_id:
        return

    items_text = '\n\n'.join(
        f'  • Наименование: {item.product_name}\n'
        f'• Артикул: {item.product_article or "—"}\n'
        f'• Количество: {item.quantity}\n'
        f'• Цена: {item.subtotal():,.0f} тг'
        for item in order.items.all()
    )

    text = (
        f'🛒 <b>Новый заказ #{order.pk}</b>\n\n'
        f'👤 <b>Клиент:</b> {order.customer_name}\n'
        f'📞 <b>Телефон:</b> {order.customer_phone}\n'
        f'💬 <b>Комментарий:</b> {order.comment or "—"}\n\n'
        f'<b>Состав заказа:</b>\n\n{items_text}\n\n'
        f'💰 <b>Итого: {order.total:,.0f} тг</b>'
    )

    try:
        requests.post(
            f'https://api.telegram.org/bot{token}/sendMessage',
            json={'chat_id': chat_id, 'text': text, 'parse_mode': 'HTML'},
            timeout=5,
        )
    except Exception:
        pass
