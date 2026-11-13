from ipaddress import ip_address

from django.conf import settings


def ip_cliente(request):
    endereco = request.META.get("REMOTE_ADDR", "")
    if settings.RENDER_HOST:
        encaminhados = request.META.get("HTTP_X_FORWARDED_FOR", "").split(",")
        endereco = encaminhados[-1].strip() or endereco
    try:
        return str(ip_address(endereco))
    except ValueError:
        return None
