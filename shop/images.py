"""Получение фото, описания и характеристик товара со страницы поставщика.

Заточено под структуру ecogr.kz (вкладки «Характеристики» и «Описание»),
для других сайтов используется запасной разбор og:image / og:description.
Также умеет искать товар по артикулу на сайте поставщика.
"""
import html as _html
import re
import urllib.parse

import requests

_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                  'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36'
}

_IMAGE_PATTERNS = (
    r'<meta[^>]+(?:property|name)=["\']og:image(?::secure_url)?["\'][^>]+content=["\']([^"\']+)["\']',
    r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:property|name)=["\']og:image["\']',
    r'<meta[^>]+name=["\']twitter:image["\'][^>]+content=["\']([^"\']+)["\']',
    r'<link[^>]+rel=["\']image_src["\'][^>]+href=["\']([^"\']+)["\']',
)
_OGDESC_PATTERNS = (
    r'<meta[^>]+(?:property|name)=["\']og:description["\'][^>]+content=["\']([^"\']*)["\']',
    r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']*)["\']',
)

# Пара «название — значение» в таблице характеристик ecogr.kz.
_SPEC_RE = re.compile(
    r'<dl class="detail-specs">.*?detail-specs__name[^>]*>\s*<span>(.*?)</span>'
    r'.*?detail-specs__value[^>]*>\s*<span>(.*?)</span>',
    re.IGNORECASE | re.DOTALL,
)
# Блок описания: заголовок + текст (Преимущества, Комплектация и т.п.).
_DESC_RE = re.compile(
    r'description-item__header"[^>]*>(.*?)</h3>'
    r'.*?description-item__text[^>]*>(.*?)</div>\s*</div>\s*</div>',
    re.IGNORECASE | re.DOTALL,
)

_TAGS = re.compile(r'<[^>]+>')
_BULLET_ONLY = re.compile(r'^[\s■•▪◦*+\-–—]*$')


def _slice(page, start_marker, end_marker):
    """Вырезает кусок страницы между двумя маркерами."""
    i = page.find(start_marker)
    if i == -1:
        return ''
    j = page.find(end_marker, i + len(start_marker))
    return page[i:j] if j != -1 else page[i:]


def _clean(fragment):
    """Убирает теги, возвращает однострочный текст."""
    text = _html.unescape(_TAGS.sub(' ', fragment or ''))
    return re.sub(r'[ \t\r\n]+', ' ', text).strip()


def _clean_block(fragment):
    """Убирает теги, сохраняя переносы строк (каждый <div> — строка)."""
    text = re.sub(r'</(?:div|p|li)\s*>', '\n', fragment or '', flags=re.IGNORECASE)
    text = re.sub(r'<br\s*/?>', '\n', text, flags=re.IGNORECASE)
    text = _html.unescape(_TAGS.sub('', text))
    lines = []
    for raw in text.splitlines():
        line = re.sub(r'[ \t]+', ' ', raw).strip()
        if line and not _BULLET_ONLY.match(line):
            lines.append(line)
    return '\n'.join(lines)


def _first_match(page, patterns):
    for pattern in patterns:
        m = re.search(pattern, page, re.IGNORECASE | re.DOTALL)
        if m and m.group(1).strip():
            return m.group(1).strip()
    return ''


def fetch_product_info(url, timeout=10):
    """Загружает страницу товара и возвращает фото, описание и характеристики.

    Возвращает dict: {'image', 'description', 'characteristics'}.
    """
    empty = {'image': '', 'description': '', 'characteristics': ''}
    if not url or not url.lower().startswith(('http://', 'https://')):
        return empty
    try:
        resp = requests.get(url, timeout=timeout, headers=_HEADERS)
        if resp.status_code != 200:
            return empty
        page = resp.text
    except requests.RequestException:
        return empty

    # ── Фото ──
    image = _first_match(page, _IMAGE_PATTERNS)
    if image.startswith('//'):
        image = 'https:' + image
    if not image.lower().startswith(('http://', 'https://')):
        image = ''

    # ── Характеристики (вкладка «Характеристики») ──
    char_html = _slice(page, 'id="nav-technical_characteristics"', 'id="nav-description"')
    specs, seen = [], set()
    for name, value in _SPEC_RE.findall(char_html or page):
        n, v = _clean(name), _clean(value)
        if n and n.lower() not in seen:
            seen.add(n.lower())
            specs.append(f'{n}: {v}' if v else n)
    characteristics = '\n'.join(specs)[:4000]

    # ── Описание (вкладка «Описание») ──
    desc_html = _slice(page, 'id="nav-description"', 'id="nav-files"')
    parts, seen_d = [], set()
    for header, body in _DESC_RE.findall(desc_html or page):
        h, b = _clean(header), _clean_block(body)
        key = (h.lower(), b[:80])
        if key in seen_d:
            continue
        seen_d.add(key)
        block = (h + '\n' + b).strip() if h else b
        if block:
            parts.append(block)
    description = '\n\n'.join(parts)[:6000]
    if not description:
        description = _clean(_first_match(page, _OGDESC_PATTERNS))[:2000]

    return {'image': image, 'description': description, 'characteristics': characteristics}


def fetch_product_image(url, timeout=10):
    """Совместимость: возвращает только URL изображения."""
    return fetch_product_info(url, timeout)['image']


# ─── Поиск товара по артикулу на сайте поставщика ─────────────────────────
_SEARCH_PATTERNS = (
    '/search?q={q}', '/search?text={q}', '/search?query={q}', '/search/?q={q}',
    '/catalog/search?q={q}', '/?s={q}', '/search?keyword={q}', '/search?search={q}',
)
_PRODUCT_PATH = re.compile(
    r'/(?:product|products|tovar|tovary|item|items|goods|good|card|shop|p)s?/[\w%.-]',
    re.IGNORECASE)


def search_product_on_site(base, article, prefer_pattern=None, timeout=10):
    """Ищет страницу товара по артикулу на сайте поставщика.

    base — адрес сайта (например https://technosector.kz).
    Возвращает (url_страницы_товара, сработавший_шаблон_поиска) или ('', None).
    """
    if not base or not article:
        return '', None
    base = base.strip()
    if not base.lower().startswith(('http://', 'https://')):
        base = 'https://' + base
    base = base.rstrip('/')
    host = urllib.parse.urlparse(base).netloc.replace('www.', '')
    art = str(article).strip()
    q = urllib.parse.quote(art)

    patterns = list(_SEARCH_PATTERNS)
    if prefer_pattern in patterns:
        patterns.remove(prefer_pattern)
        patterns.insert(0, prefer_pattern)

    for pat in patterns:
        try:
            resp = requests.get(base + pat.format(q=q), timeout=timeout, headers=_HEADERS)
        except requests.RequestException:
            continue
        if resp.status_code != 200:
            continue

        by_article, by_path = [], []
        for href in re.findall(r'''href\s*=\s*["']([^"'<>\s]+)["']''', resp.text):
            full = urllib.parse.urljoin(resp.url, _html.unescape(href))
            pu = urllib.parse.urlparse(full)
            if not pu.scheme.startswith('http'):
                continue
            if host and pu.netloc and pu.netloc.replace('www.', '') != host:
                continue
            # принимаем только ссылки на страницу товара (а не на сам поиск/ленту)
            if not _PRODUCT_PATH.search(pu.path):
                continue
            clean = pu._replace(fragment='').geturl()
            if art.lower() in pu.path.lower():
                by_article.append(clean)   # артикул прямо в адресе товара
            else:
                by_path.append(clean)

        # ссылка с артикулом прямо в адресе — это точно нужный товар
        if by_article:
            return by_article[0], pat
        # иначе подтверждаем, что на странице товара действительно есть артикул
        for cand in by_path[:3]:
            try:
                pr = requests.get(cand, timeout=timeout, headers=_HEADERS)
            except requests.RequestException:
                continue
            if pr.status_code == 200 and art.lower() in pr.text.lower():
                return cand, pat
    return '', None


# ─── Поиск фото на al-style.kz по артикулу ────────────────────────────────
_ALSTYLE_IMG = re.compile(r'img\.al-style\.kz/([0-9A-Za-z_-]+\.(?:jpg|jpeg|png))',
                          re.IGNORECASE)


def fetch_alstyle_image(article, timeout=12):
    """Ищет фото товара на al-style.kz по артикулу.

    Поиск al-style выдаёт страницу с карточкой товара (картинка видна без
    авторизации). Возвращает URL картинки или ''.
    """
    art = str(article or '').strip()
    if not art:
        return ''
    try:
        resp = requests.get(
            'https://al-style.kz/search/index.php',
            params={'q': art}, timeout=timeout, headers=_HEADERS)
    except requests.RequestException:
        return ''
    if resp.status_code != 200:
        return ''
    page = resp.text
    # берём только блок результатов поиска, чтобы не схватить баннер/новинки
    i = page.find('Результаты поиска')
    segment = page[i:i + 12000] if i != -1 else ''
    m = _ALSTYLE_IMG.search(segment)
    if not m:
        return ''
    return 'https://img.al-style.kz/' + m.group(1)
