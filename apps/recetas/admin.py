from django.contrib import admin

from .models import ItemReceta, Receta


class ItemRecetaInline(admin.TabularInline):
    model = ItemReceta
    extra = 0


@admin.register(Receta)
class RecetaAdmin(admin.ModelAdmin):
    list_display = ('folio', 'paciente', 'medico', 'estado', 'emitida_en')
    list_filter = ('estado',)
    inlines = [ItemRecetaInline]
