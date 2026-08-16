from django.contrib import admin
from unfold.admin import ModelAdmin

from catalog.models import EveCategory, EveGroup, EveType


class ReadOnlyAdmin(ModelAdmin):
    search_fields = ["name"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(EveCategory)
class EveCategoryAdmin(ReadOnlyAdmin):
    list_display = ["id", "name"]


@admin.register(EveGroup)
class EveGroupAdmin(ReadOnlyAdmin):
    list_display = ["id", "name", "category"]
    list_filter = ["category"]


@admin.register(EveType)
class EveTypeAdmin(ReadOnlyAdmin):
    list_display = ["id", "name", "group"]
    list_select_related = ["group", "group__category"]
