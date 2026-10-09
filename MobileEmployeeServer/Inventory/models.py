"""Модели данных обмена"""
from django.db import models


class SyncItem(models.Model):
    """ Общая модели синхронизации произвольных данных"""

    # Храним GUID как строку, чтобы не спотыкаться на валидации UUID СУБД
    sync_code = models.CharField(
        max_length=36, 
        primary_key=True, 
        verbose_name="GUID из 1С"
    )
    model_type = models.CharField(
        max_length=100, 
        db_index=True, 
        verbose_name="Тип объекта 1С"
    )
    # Принимает экранированную XDTO-строку JSON в чистом виде
    data = models.TextField(
        verbose_name="Слепок данных (строка JSON)",
        blank=True,
        null=True
    )
    is_deleted = models.BooleanField(
        default=False,
        verbose_name="Флаг удаления"
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name="Дата обновления на шлюзе"
    )

    objects = models.Manager() # подсказка линтеру о наличии свойства "object"

    class Meta:
        verbose_name = "Объект синхронизации"
        verbose_name_plural = "Объекты синхронизации"
        # Индекс для быстрой выборки данных конкретного типа
        indexes = [
            models.Index(fields=['model_type', 'is_deleted']),
        ]

    def __str__(self):
        return f"{self.model_type} ({self.sync_code})"
