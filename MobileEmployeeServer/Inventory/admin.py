from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import SyncItem, MobileUser


@admin.register(MobileUser)
class MobileUserAdmin(UserAdmin):
    list_display = ('id', 'username', 'first_name', 'sync_code', 'warehouse_id', 'is_active')
    list_display_links = ('id', 'username')
    list_filter = ('is_active', 'can_create_nomenclature')
    search_fields = ('username', 'sync_code', 'warehouse_id')
    
    # СТРОКА ДЛЯ ИСПРАВЛЕНИЯ ОШИБКИ:
    # Указываем Django, что это поле предназначено только для чтения на форме
    readonly_fields = ('sync_code',)

    # Настройка отображения полей внутри карточки редактирования пользователя
    fieldsets = UserAdmin.fieldsets + (
        ('Синхронизация с 1С', {'fields': ('sync_code', 'warehouse_id', 'can_create_nomenclature')}),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (
        ('Синхронизация с 1С', {'fields': ('sync_code', 'warehouse_id', 'can_create_nomenclature')}),
    )



@admin.register(SyncItem)
class SyncItemAdmin(admin.ModelAdmin):
    # Поля, которые будут отображаться в таблице списка складов
    list_display = ('model_type', 'sync_code', 'is_deleted', 'updated_at')
    
    # Поля, по которым будет работать строка поиска
    search_fields = ('=sync_code', )
    
    # Фильтры в правой панели
    list_filter = ('model_type',)
    
    # Делает поле sync_code доступным только для чтения
    readonly_fields = ('sync_code',)
