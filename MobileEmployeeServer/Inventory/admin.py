from django.contrib import admin
from .models import Storage, Good, ToolBalance, CreateOrWriteOff


@admin.register(Storage)
class StorageAdmin(admin.ModelAdmin):
    # Поля, которые будут отображаться в таблице списка складов
    list_display = ('title', 'user', 'can_create')
    
    # Поля, по которым будет работать строка поиска
    search_fields = ('title', '=sync_code', 'user__username')
    
    # Фильтры в правой панели
    list_filter = ('can_create',)
    
    # Делает поле sync_code доступным только для чтения, если оно уже сгенерировано
    readonly_fields = ('sync_code',)


@admin.register(Good)
class GoodAdmin(admin.ModelAdmin):
    list_display = ('title', 'serial_number', 'updated_at')
    search_fields = ('title', '=sync_code', 'serial_number', 'code_v7')
    list_filter = ('unit', 'is_serial', 'created_at')
    readonly_fields = ('sync_code', 'created_at', 'updated_at')
    
    # Удобное разделение полей на логические блоки внутри карточки товара
    fieldsets = (
        ('Основная информация', {
            'fields': ('title', 'sync_code', 'unit', 'image')
        }),
        ('Серийный учет', {
            'fields': ('is_serial', 'serial_number')
        }),
        ('Дополнительно', {
            'fields': ('code_v7', 'created_at', 'updated_at'),
            'classes': ('collapse',)  # Сворачиваемый блок
        }),
    )


@admin.register(ToolBalance)
class ToolBalanceAdmin(admin.ModelAdmin):
    list_display = ('good', 'storage', 'storage_type', 'quantity', 'created_at')
    search_fields = ('good__title', '=good__sync_code', 'storage__title', '=storage__sync_code')
    list_filter = ('storage_type', 'storage', 'created_at')
    readonly_fields = ('created_at',)


@admin.register(CreateOrWriteOff)
class CreateOrWriteOffAdmin(admin.ModelAdmin):
    list_display = ('id', 'good', 'storage', 'quantity', 'created_at')
    search_fields = ('good__title', '=good__sync_code', 'storage__title', '=storage__sync_code')
    list_filter = ('storage', 'created_at')
    readonly_fields = ('created_at',)

    # Запрещаем редактировать уже совершенные движения из админки,
    # чтобы не ломать логику автоматического пересчета остатков
    def has_change_permission(self, request, obj=None):
        return False
