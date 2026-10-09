from django.contrib import admin
from .models import SyncItem


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
