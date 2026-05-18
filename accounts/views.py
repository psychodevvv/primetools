import time

from django.contrib import messages
from django.shortcuts import redirect, render

from .models import Customer
from .sms import generate_code, send_code

CODE_TTL = 600  # код действует 10 минут


def _norm_phone(raw):
    """Приводит номер к виду 7XXXXXXXXXX (11 цифр) или '' если некорректен."""
    digits = ''.join(c for c in (raw or '') if c.isdigit())
    if digits.startswith('8'):
        digits = '7' + digits[1:]
    if len(digits) == 10:
        digits = '7' + digits
    return digits if len(digits) == 11 and digits.startswith('7') else ''


def _login_customer(request, customer):
    request.session['customer_id'] = customer.pk
    request.session['customer_name'] = customer.full_name()
    request.session['customer_phone'] = customer.phone


def _send_verification(request, phone, mode, first_name='', last_name=''):
    """Создаёт код, кладёт в сессию, отправляет. Возвращает (отправлено_sms, код)."""
    code = generate_code()
    request.session['verify'] = {
        'phone': phone, 'code': code, 'mode': mode,
        'first_name': first_name, 'last_name': last_name,
        'expires': time.time() + CODE_TTL,
    }
    return send_code(phone, code), code


def _flash_code(request, sent, code):
    if sent:
        messages.success(request, 'Код подтверждения отправлен на ваш номер.')
    else:
        messages.warning(request, f'Демо-режим (SMS не настроены). Ваш код: {code}')


def _verify(request, expect_mode, template):
    """Проверка введённого кода. Общая для входа и регистрации."""
    data = request.session.get('verify')
    code = (request.POST.get('code') or '').strip()
    redirect_name = 'register' if expect_mode == 'register' else 'login'

    if not data or data.get('mode') != expect_mode:
        messages.error(request, 'Сессия истекла — начните заново.')
        return redirect(redirect_name)
    if time.time() > data.get('expires', 0):
        request.session.pop('verify', None)
        messages.error(request, 'Срок действия кода истёк — запросите новый.')
        return redirect(redirect_name)
    if code != data['code']:
        messages.error(request, 'Неверный код. Попробуйте ещё раз.')
        return render(request, template, {'stage': 'code', 'phone': data['phone']})

    if expect_mode == 'register':
        customer, _ = Customer.objects.get_or_create(
            phone=data['phone'],
            defaults={'first_name': data['first_name'], 'last_name': data['last_name']},
        )
    else:
        customer = Customer.objects.filter(phone=data['phone']).first()
        if customer is None:
            messages.error(request, 'Аккаунт не найден.')
            return redirect('register')

    request.session.pop('verify', None)
    _login_customer(request, customer)
    messages.success(request, f'Добро пожаловать, {customer.first_name}!')
    return redirect('index')


def register(request):
    if request.session.get('customer_id'):
        return redirect('index')

    stage, phone = 'phone', ''
    if request.method == 'POST':
        if 'code' in request.POST:
            return _verify(request, 'register', 'accounts/register.html')

        first_name = request.POST.get('first_name', '').strip()
        last_name = request.POST.get('last_name', '').strip()
        phone = _norm_phone(request.POST.get('phone', ''))

        if not first_name or not phone:
            messages.error(request, 'Укажите имя и корректный номер телефона.')
        elif Customer.objects.filter(phone=phone).exists():
            messages.error(request, 'Этот номер уже зарегистрирован — войдите.')
        else:
            sent, code = _send_verification(request, phone, 'register',
                                            first_name, last_name)
            _flash_code(request, sent, code)
            stage = 'code'

    return render(request, 'accounts/register.html', {'stage': stage, 'phone': phone})


def login_view(request):
    if request.session.get('customer_id'):
        return redirect('index')

    stage, phone = 'phone', ''
    if request.method == 'POST':
        if 'code' in request.POST:
            return _verify(request, 'login', 'accounts/login.html')

        phone = _norm_phone(request.POST.get('phone', ''))
        if not phone:
            messages.error(request, 'Укажите корректный номер телефона.')
        elif not Customer.objects.filter(phone=phone).exists():
            messages.error(request, 'Аккаунт с таким номером не найден — зарегистрируйтесь.')
        else:
            sent, code = _send_verification(request, phone, 'login')
            _flash_code(request, sent, code)
            stage = 'code'

    return render(request, 'accounts/login.html', {'stage': stage, 'phone': phone})


def logout_view(request):
    for key in ('customer_id', 'customer_name', 'customer_phone', 'verify'):
        request.session.pop(key, None)
    return redirect('index')


def profile(request):
    customer_id = request.session.get('customer_id')
    if not customer_id:
        return redirect('login')
    customer = Customer.objects.filter(pk=customer_id).first()
    if customer is None:
        return redirect('login')
    from shop.models import Order

    def _digits(value):
        return ''.join(c for c in (value or '') if c.isdigit())

    # Телефон в заказе может быть сохранён в любом формате (+7 (...) ...),
    # поэтому сравниваем по последним 10 цифрам номера.
    target = _digits(customer.phone)[-10:]
    orders = [
        o for o in Order.objects.order_by('-created_at')
        if _digits(o.customer_phone)[-10:] == target
    ]
    return render(request, 'accounts/profile.html', {'customer': customer, 'orders': orders})
