from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import Usuario


@admin.register(Usuario)
class UsuarioAdmin(UserAdmin):
    list_display = ('username', 'email', 'rol', 'is_active')
    list_filter = ('rol', 'is_active')
    fieldsets = UserAdmin.fieldsets + (('Altavida', {'fields': ('rol',)}),)
    add_fieldsets = UserAdmin.add_fieldsets + (('Altavida', {'fields': ('email', 'rol')}),)
