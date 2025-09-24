from django.contrib import admin

from .models import Replay


@admin.register(Replay)
class ReplayAdmin(admin.ModelAdmin):
    list_display = ("hand_id", "created_at")
    search_fields = ("hand_id",)
    ordering = ("-created_at",)
