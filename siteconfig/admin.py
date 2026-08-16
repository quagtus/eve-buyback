from django.contrib import admin
from unfold.admin import ModelAdmin

from siteconfig.models import SiteConfig


@admin.register(SiteConfig)
class SiteConfigAdmin(ModelAdmin):
    """Singleton — exactly one row, never added or deleted by hand."""

    list_display = ["__str__", "market_id", "pricing_basis", "contract_to"]

    def has_add_permission(self, request):
        return not SiteConfig.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False
