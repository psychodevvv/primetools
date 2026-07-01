from django.contrib import messages
from django.shortcuts import redirect, render

from .models import Customer


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


def register(request):
    if request.session.get('customer_id'):
        return redirect('index')

    ctx = {'phone': '', 'first_name': '', 'last_name': ''}
    if request.method == 'POST':
        first_name = request.POST.get('first_name', '').strip()
        last_name = request.POST.get('last_name', '').strip()
        phone = _norm_phone(request.POST.get('phone', ''))
        password = request.POST.get('password') or ''
        password2 = request.POST.get('password2') or ''
        ctx.update({'phone': phone, 'first_name': first_name,
                    'last_name': last_name})

        if not first_name:
            messages.error(request, 'Укажите имя.')
        elif not phone:
            messages.error(request, 'Укажите корректный номер телефона.')
        elif len(password) < 6:
            messages.error(request, 'Пароль должен быть не короче 6 символов.')
        elif password != password2:
            messages.error(request, 'Пароли не совпадают.')
        elif Customer.objects.filter(phone=phone).exists():
            messages.error(request, 'Этот номер уже зарегистрирован — войдите.')
        else:
            customer = Customer(first_name=first_name, last_name=last_name,
                                phone=phone)
            customer.set_password(password)
            customer.save()
            _login_customer(request, customer)
            messages.success(request, f'Добро пожаловать, {customer.first_name}!')
            return redirect('index')

    return render(request, 'accounts/register.html', ctx)


def login_view(request):
    if request.session.get('customer_id'):
        return redirect('index')

    phone = ''
    if request.method == 'POST':
        phone = _norm_phone(request.POST.get('phone', ''))
        password = request.POST.get('password') or ''

        if not phone or not password:
            messages.error(request, 'Введите номер и пароль.')
        else:
            customer = Customer.objects.filter(phone=phone).first()
            if customer is None:
                messages.error(request, 'Аккаунт с таким номером не найден — зарегистрируйтесь.')
            elif not customer.check_password(password):
                messages.error(request, 'Неверный пароль.')
            else:
                _login_customer(request, customer)
                messages.success(request, f'Добро пожаловать, {customer.first_name}!')
                return redirect('index')

    return render(request, 'accounts/login.html', {'phone': phone})


def logout_view(request):
    for key in ('customer_id', 'customer_name', 'customer_phone'):
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
