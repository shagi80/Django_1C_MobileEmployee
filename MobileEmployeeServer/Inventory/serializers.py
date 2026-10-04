import uuid
from rest_framework import serializers
from django.contrib.auth import get_user_model
from .models import Good, Storage, Units, StorageTypes

User = get_user_model()


class StorageSerializer(serializers.ModelSerializer):
    # Указываем, что sync_code не обязателен на вход (1С может прислать null),
    # но он вернется в ответе после генерации в методе save()
    sync_code = serializers.UUIDField(required=False, allow_null=True)

    class Meta:
        model = Storage
        fields = ['id', 'sync_code', 'user', 'title', 'can_create']
        extra_kwargs = {
            'user': {'help_text': 'ID связанного пользователя Django'}
        }


class GoodListSerializer(serializers.ListSerializer):
    """Кастомный ListSerializer для реализации операции Upsert с возвратом индекса элемента"""

    def create(self, validated_data):
        # 1. Собираем все переданные sync_code для пакетного поиска в БД
        sync_codes = [item['sync_code'] for item in validated_data if item.get('sync_code')]
        
        # 2. Вытаскиваем существующие товары в словарь для быстрого поиска O(1)
        existing_goods = {
            str(good.sync_code): good 
            for good in Good.objects.filter(sync_code__in=sync_codes)
        }

        response_data = []

        # 3. Обходим массив с использованием enumerate, чтобы получить точный индекс элемента (начиная с 0)
        for index, item in enumerate(validated_data):
            item_sync_code = item.get('sync_code')
            sync_code_str = str(item_sync_code) if item_sync_code else None

            # Если товар с таким sync_code уже есть — обновляем его
            if sync_code_str and sync_code_str in existing_goods:
                instance = existing_goods[sync_code_str]
                for attr, value in item.items():
                    setattr(instance, attr, value)
                instance.save()
                
                # Добавляем в результат индекс и текущий sync_code
                response_data.append({
                    'index': index,
                    'sync_code': str(instance.sync_code)
                })
            
            # Если sync_code нет или он не найден — создаем новый товар
            else:
                # Если 1С передала null, генерируем UUID вручную до создания, 
                # чтобы сразу зафиксировать его и вернуть в ответе
                if not item.get('sync_code'):
                    item['sync_code'] = uuid.uuid4()
                
                new_good = Good.objects.create(**item)
                
                # Добавляем в результат индекс и сгенерированный sync_code
                response_data.append({
                    'index': index,
                    'sync_code': str(new_good.sync_code)
                })

        # Возвращаем сформированный массив с индексами вместо инстансов моделей
        return response_data


class GoodSerializer(serializers.ModelSerializer):
    sync_code = serializers.UUIDField(required=False, allow_null=True)
    unit_display = serializers.CharField(source='get_unit_display', read_only=True)
    image = serializers.ImageField(required=False, allow_null=True)

    class Meta:
        model = Good
        fields = [
            'id', 'sync_code', 'title', 'category', 'image', 'is_serial', 
            'serial_number', 'unit', 'unit_display', 'code_v7', 
            'created_at', 'updated_at'
        ]
        read_only_fields = ['created_at', 'updated_at']
        
        # Указываем Django использовать наш кастомный класс для обработки списков (many=True)
        list_serializer_class = GoodListSerializer

    def validate_unit(self, value):
        if value not in Units.values:
            raise serializers.ValidationError(
                f"Недопустимая единица измерения. Доступные варианты: {Units.values}"
            )
        return value


class OneClickDocumentSerializer(serializers.Serializer):
    # Поля документа 1С
    document_guid = serializers.UUIDField(
        required=True, 
        help_text="GUID самого документа из 1С"
    )
    storage_sync_code = serializers.UUIDField(
        required=True, 
        help_text="sync_code склада-получателя/отправителя"
    )
    good_sync_code = serializers.UUIDField(
        required=True, 
        help_text="sync_code товара"
    )
    quantity = serializers.FloatField(
        required=True, 
        help_text="Количество (положительное или отрицательное)"
    )
    storage_type = serializers.ChoiceField(
        choices=StorageTypes.choices, 
        required=True, 
        help_text="Вид движения (real, transfer, reception, write_off)"
    )

    def validate_storage_sync_code(self, value):
        """Проверяем существование склада в Django"""
        try:
            return Storage.objects.get(sync_code=value)
        except Storage.DoesNotExist:
            raise serializers.ValidationError(f"Склад с sync_code={value} не найден.")

    def validate_good_sync_code(self, value):
        """Проверяем существование товара в Django"""
        try:
            return Good.objects.get(sync_code=value)
        except Good.DoesNotExist:
            raise serializers.ValidationError(f"Товар с sync_code={value} не найден.")

    def validate_quantity(self, value):
        """Количество не должно быть нулевым"""
        if value == 0:
            raise serializers.ValidationError("Количество не может быть равным нулю.")
        return value
