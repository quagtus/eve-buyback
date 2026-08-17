import re

from django.conf import settings
from django.contrib import admin
from django.urls import include, path, re_path
from django.views.static import serve

from contracts.views import callback, contract_check, disconnect, link
from pricing.views import rule_summary

# Every admin/ route here must come BEFORE admin.site.urls, which is a catch-all
# under that prefix — anything registered after it never matches.
urlpatterns = [
    path("i18n/", include("django.conf.urls.i18n")),
    path("admin/pricing/summary/", admin.site.admin_view(rule_summary), name="pricing_summary"),
    path("admin/contracts/check/", admin.site.admin_view(contract_check), name="contract_check"),
    path("admin/contracts/link/", admin.site.admin_view(link), name="contract_link"),
    path("admin/contracts/callback/", admin.site.admin_view(callback), name="contract_callback"),
    path("admin/contracts/disconnect/", admin.site.admin_view(disconnect), name="contract_disconnect"),
    path("admin/", admin.site.urls),
    path("", include("buyback.urls")),
]

# Serve admin-uploaded media.
#
# WhiteNoise only serves STATIC_ROOT, which is populated by collectstatic at
# image build time — a logo uploaded afterwards would 404 in production. This
# route reads MEDIA_ROOT directly so uploads work without a rebuild.
#
# django.views.static.serve is inefficient for high-traffic media, but this
# app's media is a single admin-managed logo. Put a real web server in front
# if that ever changes.
def _serve_media(request, path):
    """Read MEDIA_ROOT per request rather than binding it into the URLconf.

    Passing {"document_root": settings.MEDIA_ROOT} captures the value at import
    time, so the view keeps serving the original directory even when the setting
    changes — which silently breaks override_settings(MEDIA_ROOT=...) in tests
    and makes them pass or fail depending on import order.
    """
    return serve(request, path, document_root=settings.MEDIA_ROOT)


urlpatterns += [
    re_path(
        r"^%s(?P<path>.*)$" % re.escape(settings.MEDIA_URL.lstrip("/")),
        _serve_media,
    ),
]
