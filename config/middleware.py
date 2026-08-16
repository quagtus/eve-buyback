"""Keep the admin in English regardless of the visitor's language choice.

LocaleMiddleware would otherwise translate the Django admin and Unfold
automatically. Translation is scoped to the public site by product decision,
so this re-activates English for anything under /admin/ — including the
rule summary page, which is rendered inside the admin shell.
"""

from django.utils import translation

ADMIN_PREFIX = "/admin/"


class AdminEnglishMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path.startswith(ADMIN_PREFIX):
            translation.activate("en")
            request.LANGUAGE_CODE = "en"
        return self.get_response(request)
