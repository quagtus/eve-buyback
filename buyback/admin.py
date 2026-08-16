from django.contrib import admin
from django.utils.html import format_html
from unfold.admin import ModelAdmin, TabularInline

from buyback.models import Snapshot, SnapshotItem


class SnapshotItemInline(TabularInline):
    model = SnapshotItem
    extra = 0
    can_delete = False
    fields = [
        "type_name", "quantity", "unit_price",
        "percent_applied", "price_source", "line_total", "flag_reason",
    ]
    readonly_fields = fields

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Snapshot)
class SnapshotAdmin(ModelAdmin):
    """Quotes are immutable records — read-only bookkeeping only."""

    list_display = ["code", "created_at", "total_value", "item_count", "public_link"]
    search_fields = ["code"]
    date_hierarchy = "created_at"
    inlines = [SnapshotItemInline]
    readonly_fields = [
        "code", "created_at", "total_value", "contract_to", "contract_instructions",
    ]

    @admin.display(description="Public page")
    def public_link(self, obj):
        return format_html('<a href="/quote/{}/" target="_blank">open</a>', obj.code)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
