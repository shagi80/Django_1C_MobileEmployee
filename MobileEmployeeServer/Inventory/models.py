"""Модели данных обмена"""
from django.contrib.auth.models import AbstractUser
from django.db import models


class MobileUser(AbstractUser):
 
    sync_code = models.UUIDField(
        unique=True, 
        editable=False,
        null=True, 
        blank=True,
        verbose_name='Уникальный код синхронизации 1С'
    )
    can_create_nomenclature = models.BooleanField(
        default=False,
        verbose_name='Может создавать номенклатуру (поступления)',
    )
    warehouse_id = models.CharField(
        max_length=36,
        blank=True,
        null=True,
        verbose_name='Идентификатор склада',
    )

    class Meta:
        ordering = ['id']
        verbose_name = 'Мобильный пользователь'
        verbose_name_plural = 'Мобильные пользователи'

    def __str__(self):
        return f"{self.username}"


class SyncItem(models.Model):
    """ Модель синхронизации общих данных данных"""

    sync_code = models.CharField(
        max_length=50, 
        unique=True,  
        verbose_name="UUID из 1С"
    )
    model_type = models.CharField(
        max_length=100, 
        db_index=True, 
        verbose_name="Тип объекта 1С"
    )
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
        verbose_name = "Объект общих данных"
        verbose_name_plural = "Объекты общих данных"
        
    def __str__(self):
        return f"{self.model_type} ({self.sync_code})"


class SyncDocumentItem(models.Model):
    """ Модель синхронизации документов данных"""

    storage_to = models.CharField(
        max_length=36,
        verbose_name="UUID склада-получателя из 1С",
        blank=True,
        null=True
     )
    storage_from = models.CharField(
            max_length=36,
            verbose_name="UUID склада-отправителя из 1С",
            blank=True,
            null=True
         )
    sync_code = models.CharField(
        max_length=50, 
        unique=True,  
        verbose_name="UUID из 1С"
    )
    model_type = models.CharField(
        max_length=100, 
        db_index=True, 
        verbose_name="Тип объекта 1С"
    )
    data = models.TextField(
        verbose_name="Слепок данных (строка JSON)",
        blank=True,
        null=True
    )
    is_deleted = models.BooleanField(
        default=False,
        verbose_name="Флаг удаления"
    )
    doc_date = models.DateTimeField(
            verbose_name="Дата документа"
        )
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name="Дата обновления на шлюзе"
    )

    objects = models.Manager() 

    class Meta:
        verbose_name = "Объект документа"
        verbose_name_plural = "Объекты документов"
        
    def __str__(self):
        return f"{self.model_type} ({self.sync_code})"

