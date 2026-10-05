import os
import uuid
from django.db import models
from django.contrib.auth import get_user_model

User = get_user_model()


def good_image_upload_path(instance, filename):
    """
    Генерирует уникальный путь для загрузки изображений товаров.
    Файлы сохраняются в директорию: media/goods/uuid_название.расширение
    """

    ext = filename.split('.')[-1]
    unique_filename = f"{uuid.uuid4()}.{ext}"
    return os.path.join('goods', unique_filename)


class Units(models.TextChoices):
    """Единицы измерения."""

    KG = 'kg', 'килограмм'
    PCS = 'pcs', 'штука'
    M = 'm', 'метр'
    L = 'l', 'литр'


class StorageTypes(models.TextChoices):
    """Типы хранения/операций."""

    REAL = 'real', 'real'
    TRANSFER = 'transfer', 'transfer'
    RECEPTION = 'reception', 'reception'
    WRITE_OFF = 'write_off', 'write_off'


class Storage(models.Model):
    """Склад / Место хранения."""

    sync_code = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        verbose_name='Сквозной код'
    )

    user = models.OneToOneField(
        User, 
        on_delete=models.CASCADE, 
        related_name='storage',
        verbose_name='Пользователь'
    )
    title = models.CharField(max_length=255, verbose_name='Название')
    can_create = models.BooleanField(default=False, verbose_name='Может создавать номенклатуру')

    class Meta:
        verbose_name = 'Склад'
        verbose_name_plural = 'Склады'

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        # Генерируем уникальный код
        if not self.sync_code:
            self.sync_code = uuid.uuid4()
        super().save(*args, **kwargs)


class Good(models.Model):
    """Товар."""

    sync_code = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        verbose_name='Сквозной код'
    )

    title = models.CharField(max_length=255, verbose_name='Название')
    category = models.CharField(max_length=255, blank=True, null=True, verbose_name='Категория')
    
    image = models.ImageField(
        upload_to=good_image_upload_path, 
        blank=True, 
        null=True, 
        verbose_name='Изображение товара'
    )
    
    is_serial = models.BooleanField(default=False, verbose_name='Учет по серийным номерам')
    serial_number = models.CharField(max_length=20, blank=True, null=True, verbose_name='Серийный номер')
    unit = models.CharField(
        max_length=10, 
        choices=Units.choices, 
        default=Units.PCS,
        verbose_name='Единица измерения'
    )
    code_v7 = models.CharField(max_length=20, blank=True, null=True, verbose_name='Код 1С7')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Дата создания')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='Дата обновления')

    class Meta:
        verbose_name = 'Товар'
        verbose_name_plural = 'Товары'

    def __str__(self):
        return f"{self.title} ({self.sync_code})"

    def save(self, *args, **kwargs):
        # Генерируем уникальный код
        if not self.sync_code:
            self.sync_code = uuid.uuid4()
        super().save(*args, **kwargs)


class ToolBalance(models.Model):
    """Остатки инструментов / товаров на складах."""

    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Дата записи')
    storage = models.ForeignKey(
        Storage, 
        on_delete=models.CASCADE, 
        related_name='balances',
        verbose_name='Склад'
    )
    good = models.ForeignKey(
        Good, 
        on_delete=models.CASCADE, 
        related_name='balances',
        verbose_name='Товар'
    )
    storage_type = models.CharField(
        max_length=10, 
        choices=StorageTypes.choices,
        verbose_name='Тип хранилища'
    )
    quantity = models.FloatField(default=0.0, verbose_name='Количество')

    class Meta:
        verbose_name = 'Остаток'
        verbose_name_plural = 'Остатки'

    def __str__(self):
        return f"{self.good.title} @ {self.storage.title}: {self.quantity}"


class CreateOrWriteOff(models.Model):
    """Операции создания или списания."""
    
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Дата операции')
    storage = models.ForeignKey(
        Storage, 
        on_delete=models.CASCADE, 
        related_name='operations',
        verbose_name='Склад'
    )
    good = models.ForeignKey(
        Good, 
        on_delete=models.CASCADE, 
        related_name='operations',
        verbose_name='Товар'
    )
    quantity = models.FloatField(default=0.0, verbose_name='Количество')

    class Meta:
        verbose_name = 'Операция создания/списания'
        verbose_name_plural = 'Операции создания/списания'

    def __str__(self):
        return f"Операция #{self.id} — {self.good.title}"


