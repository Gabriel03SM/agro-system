from django.utils.cache import patch_cache_control


class PaginasPrivadasMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if request.user.is_authenticated or request.path in ("/entrar/", "/admin/login/"):
            patch_cache_control(response, private=True, no_store=True, no_cache=True, must_revalidate=True)
            response["Pragma"] = "no-cache"
        return response
