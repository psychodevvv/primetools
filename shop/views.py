from django.shortcuts import render, get_object_or_404, redirect
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q
from .models import Category, Product, Order, OrderItem, VideoReview, Brand
from .telegram import send_order_notification
import json


def index(request):
    from django.db.models import Count
    # Топ-категории с количеством товаров — для «крутого» блока с карточками.
    featured_categories = list(
        Category.objects.filter(parent__isnull=True)
        .annotate(prod_count=Count('products'))
        .order_by('-prod_count')[:12]
    )
    total_products = Product.objects.count()
    # Хиты продаж — случайные товары с фото и в наличии.
    hits = list(
        Product.objects.exclude(image_url='').filter(in_stock=True)
        .order_by('?')[:8]
    )
    # Распродажа — товары с проставленной old_price.
    sales = list(
        Product.objects.exclude(image_url='').exclude(old_price__isnull=True)
        .order_by('?')[:8]
    )
    # На главной показываем только 3 видео-обзора; остальное — на /videos/.
    video_reviews = list(VideoReview.objects.filter(is_active=True)[:3])
    video_reviews_total = VideoReview.objects.filter(is_active=True).count()
    # ВСЕ бренды с приоритетом тех, у кого есть лого.
    from django.db.models import Case, When, Value, IntegerField
    top_brands = list(Brand.objects.filter(featured=True).annotate(
        has_logo=Case(
            When(logo__gt='', then=Value(0)),
            When(logo_url__gt='', then=Value(0)),
            default=Value(1),
            output_field=IntegerField(),
        )
    ).order_by('has_logo', 'order', 'name'))
    return render(request, 'shop/index.html', {
        'featured_categories': featured_categories,
        'total_products': total_products,
        'hits': hits,
        'sales': sales,
        'video_reviews': video_reviews,
        'video_reviews_total': video_reviews_total,
        'top_brands': top_brands,
    })


def video_reviews_page(request):
    videos = VideoReview.objects.filter(is_active=True)
    return render(request, 'shop/video_reviews.html', {'videos': videos})


def catalog(request):
    category_slug = request.GET.get('cat')
    brand_filter = request.GET.get('brand', '')
    search_query = request.GET.get('q', '').strip()
    sort = request.GET.get('sort', '')
    price_min = request.GET.get('price_min', '').strip()
    price_max = request.GET.get('price_max', '').strip()
    in_stock_only = request.GET.get('in_stock') == '1'
    sale_only = request.GET.get('sale') == '1'

    active_category = active_parent = None
    products = Product.objects.select_related('category')

    if category_slug:
        active_category = get_object_or_404(Category, slug=category_slug)
        active_parent = active_category.parent or active_category
        products = products.filter(category_id__in=active_category.descendant_ids())

    if brand_filter:
        products = products.filter(brand__iexact=brand_filter)
    if search_query:
        products = products.filter(
            Q(name__icontains=search_query) | Q(article__icontains=search_query))
    if price_min:
        try:
            products = products.filter(price__gte=float(price_min.replace(',', '.')))
        except ValueError:
            price_min = ''
    if price_max:
        try:
            products = products.filter(price__lte=float(price_max.replace(',', '.')))
        except ValueError:
            price_max = ''
    if in_stock_only:
        products = products.filter(in_stock=True)
    if sale_only:
        products = products.exclude(old_price__isnull=True)

    if sort == 'price_asc':
        products = products.order_by('price')
    elif sort == 'price_desc':
        products = products.order_by('-price')
    elif sort == 'name':
        products = products.order_by('name')

    brands = Product.objects.all()
    if active_category:
        brands = brands.filter(category_id__in=active_category.descendant_ids())
    brands = (brands.values_list('brand', flat=True)
              .distinct().exclude(brand='').order_by('brand'))

    # подкатегории текущего раздела для боковой колонки
    subcategories = []
    if active_parent:
        subcategories = list(active_parent.children.order_by('order', 'name'))

    total_count = products.count()
    paginator = Paginator(products, 24)
    page_obj = paginator.get_page(request.GET.get('page'))
    page_range = paginator.get_elided_page_range(
        page_obj.number, on_each_side=1, on_ends=1)

    params = request.GET.copy()
    params.pop('page', None)

    return render(request, 'shop/catalog.html', {
        'active_category': active_category,
        'active_parent': active_parent,
        'subcategories': subcategories,
        'products': page_obj,
        'page_obj': page_obj,
        'page_range': page_range,
        'total_count': total_count,
        'base_qs': params.urlencode(),
        'brands': brands,
        'brand_filter': brand_filter,
        'search_query': search_query,
        'sort': sort,
        'price_min': price_min,
        'price_max': price_max,
        'in_stock_only': in_stock_only,
        'sale_only': sale_only,
    })


def product_detail(request, pk):
    product = get_object_or_404(Product, pk=pk)
    related = Product.objects.filter(category=product.category).exclude(pk=pk)[:4]
    return render(request, 'shop/product_detail.html', {
        'product': product,
        'images': product.image_list(),
        'related': related,
    })


def search(request):
    q = request.GET.get('q', '').strip()
    if q:
        products = Product.objects.filter(
            Q(name__icontains=q) | Q(article__icontains=q)
        )[:40]
    else:
        products = []
    return render(request, 'shop/search.html', {'products': products, 'query': q})


def search_suggest(request):
    """JSON-подсказки для живого поиска в шапке (по названию и артикулу)."""
    q = request.GET.get('q', '').strip()
    results = []
    if len(q) >= 2:
        products = Product.objects.filter(
            Q(name__icontains=q) | Q(article__icontains=q)
        )[:8]
        for p in products:
            results.append({
                'id': p.pk,
                'name': p.name,
                'article': p.article,
                'price': '{:,}'.format(int(p.price)).replace(',', ' '),
                'image_url': p.image_url,
                'in_stock': p.in_stock,
            })
    return JsonResponse({'results': results})


@require_POST
def cart_add(request):
    data = json.loads(request.body)
    product_id = str(data.get('product_id'))
    quantity = int(data.get('quantity', 1))

    product = get_object_or_404(Product, pk=product_id)
    cart = request.session.get('cart', {})

    if product_id in cart:
        cart[product_id]['quantity'] += quantity
    else:
        cart[product_id] = {
            'name': product.name,
            'price': str(product.price),
            'quantity': quantity,
            'image_url': product.image_url,
            'article': product.article,
        }

    request.session['cart'] = cart
    # бейдж в шапке показывает число разных позиций, а не общее количество штук
    return JsonResponse({'success': True, 'cart_count': len(cart)})


@require_POST
def cart_remove(request):
    data = json.loads(request.body)
    product_id = str(data.get('product_id'))
    cart = request.session.get('cart', {})
    cart.pop(product_id, None)
    request.session['cart'] = cart
    return JsonResponse({'success': True})


@require_POST
def cart_update(request):
    data = json.loads(request.body)
    product_id = str(data.get('product_id'))
    quantity = int(data.get('quantity', 1))
    cart = request.session.get('cart', {})
    if product_id in cart:
        if quantity <= 0:
            cart.pop(product_id)
        else:
            cart[product_id]['quantity'] = quantity
    request.session['cart'] = cart
    return JsonResponse({'success': True})


def cart_view(request):
    cart = request.session.get('cart', {})
    items = []
    total = 0
    for pid, item in cart.items():
        subtotal = float(item['price']) * item['quantity']
        total += subtotal
        items.append({
            'id': pid,
            'name': item['name'],
            'price': float(item['price']),
            'quantity': item['quantity'],
            'image_url': item.get('image_url', ''),
            'subtotal': subtotal,
        })
    return render(request, 'shop/cart.html', {'items': items, 'total': total})


def checkout(request):
    cart = request.session.get('cart', {})
    if not cart:
        return redirect('cart')

    if not request.session.get('customer_id'):
        messages.warning(request, 'Для оформления заказа необходимо войти в аккаунт.')
        return redirect('/account/login/')

    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        phone = request.POST.get('phone', '').strip()
        comment = request.POST.get('comment', '').strip()

        if not name or not phone:
            messages.error(request, 'Укажите имя и номер телефона.')
            return redirect('checkout')

        order = Order.objects.create(
            customer_name=name,
            customer_phone=phone,
            comment=comment,
        )

        for pid, item in cart.items():
            OrderItem.objects.create(
                order=order,
                product_id=pid if Product.objects.filter(pk=pid).exists() else None,
                product_name=item['name'],
                product_article=item.get('article', ''),
                product_price=item['price'],
                quantity=item['quantity'],
            )

        order.calculate_total()

        request.session['cart'] = {}

        send_order_notification(order)

        messages.success(request, f'Заказ #{order.pk} оформлен! Мы свяжемся с вами по номеру {phone}.')
        return redirect('order_success', pk=order.pk)

    cart_items = []
    total = 0
    for pid, item in cart.items():
        subtotal = float(item['price']) * item['quantity']
        total += subtotal
        cart_items.append({**item, 'id': pid, 'subtotal': subtotal, 'price': float(item['price'])})

    customer_name = request.session.get('customer_name', '')
    customer_phone = request.session.get('customer_phone', '')

    return render(request, 'shop/checkout.html', {
        'cart_items': cart_items,
        'total': total,
        'customer_name': customer_name,
        'customer_phone': customer_phone,
    })


def order_success(request, pk):
    order = get_object_or_404(Order, pk=pk)
    return render(request, 'shop/order_success.html', {'order': order})
