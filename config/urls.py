from django.contrib import admin
from django.urls import include, path

from pricing.views import rule_summary

urlpatterns = [
    path("admin/pricing/summary/", admin.site.admin_view(rule_summary), name="pricing_summary"),
    path("admin/", admin.site.urls),
    path("", include("buyback.urls")),
]
