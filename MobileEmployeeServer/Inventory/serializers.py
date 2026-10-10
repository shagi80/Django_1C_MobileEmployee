import json
from django.contrib.auth.hashers import make_password
from rest_framework import serializers
from .models import MobileUser  # Укажите ваше актуальное приложение

class MobileUserSerializer(serializers.ModelSerializer):
    data = serializers.CharField(write_only=True, required=True)
    sync_code = serializers.UUIDField(required=True)

    class Meta:
        model = MobileUser
        # Используем стандартные поля Django Auth
        fields = ['sync_code', 'data', 'username', 'first_name', 'warehouse_id', 'can_create_nomenclature', 'is_active']
        extra_kwargs = {
            'username': {'required': False, 'allow_blank': True},
            'first_name': {'required': False, 'allow_blank': True}
        }

    def to_internal_value(self, data):
        sync_code = data.get('sync_code')
        raw_data_str = data.get('data', '')

        # 1. Обработка экшена удаления (строка "DELETED")
        if isinstance(raw_data_str, str) and raw_data_str.strip() == "DELETED":
            return {
                'sync_code': sync_code, 
                'is_active': False, 
                '_is_deleted_action': True
            }

        # 2. Парсинг внутренней JSON-строки от 1С
        try:
            parsed_data = json.loads(raw_data_str) if isinstance(raw_data_str, str) else raw_data_str
            value_block = parsed_data.get('#value', {})
        except (ValueError, TypeError, KeyError):
            raise serializers.ValidationError({"data": "Некорректный формат JSON внутри поля data."})

        # 3. Извлечение данных по точным ключам из вашего JSON
        username = value_block.get('Логин')
        first_name = value_block.get('Description', '')
        warehouse_id = value_block.get('Склад')
        can_create_nomenclature = value_block.get('МожетСоздаватьПоступление', False)
        
        # Если в 1С стоит пометка удаления (DeletionMark: true), то в Django деактивируем (is_active=False)
        is_active = not value_block.get('DeletionMark', False)

        internal_data = {
            'sync_code': sync_code,
            'username': username,
            'first_name': first_name,  
            'warehouse_id': warehouse_id,
            'can_create_nomenclature': can_create_nomenclature,
            'is_active': is_active,
            '_is_deleted_action': False
        }
        
        # Безопасно сохраняем пароль в контекст для последующего хеширования
        raw_password = value_block.get('Пароль')
        if raw_password:
            self.context[f'raw_password_{sync_code}'] = raw_password
            
        return internal_data

    def validate(self, attrs):
        # Для операции удаления полная валидация полей не требуется
        if attrs.get('_is_deleted_action'):
            return attrs
            
        sync_code = attrs.get('sync_code')
        username = attrs.get('username')
        
        # Если это новый пользователь, Логин (username) обязателен
        if not username and not MobileUser.objects.filter(sync_code=sync_code).exists():
            raise serializers.ValidationError({"username": "Поле 'Логин' обязательно для создания нового пользователя."})
            
        return attrs

    def create(self, validated_data):
        """Вызывается при bulk/single создании через сериализатор"""
        return self._upsert_user(validated_data)

    def update(self, instance, validated_data):
        """Вызывается при bulk/single обновлении через сериализатор"""
        return self._upsert_user(validated_data)

    def _upsert_user(self, data):
        """Единый метод для реализации логики Upsert (создание или обновление)"""
        sync_code = data.get('sync_code')
        
        # Если пришел маркер удаления — просто деактивируем запись
        if data.get('_is_deleted_action'):
            MobileUser.objects.filter(sync_code=sync_code).update(is_active=False)
            return None

        raw_password = self.context.get(f'raw_password_{sync_code}')
        
        defaults = {
            'username': data.get('username'),
            'first_name': data.get('first_name'),  
            'warehouse_id': data.get('warehouse_id'),
            'can_create_nomenclature': data.get('can_create_nomenclature'),
            'is_active': data.get('is_active', True)
        }
        
        # Хешируем пароль только если он был передан в пакете синхронизации
        if raw_password:
            defaults['password'] = make_password(raw_password)

        user, created = MobileUser.objects.update_or_create(
            sync_code=sync_code,
            defaults=defaults
        )
        return user


class MobileUserReadSerializer(serializers.ModelSerializer):
    """Сериализатор только для чтения (GET-запросы)"""
    class Meta:
        model = MobileUser
        fields = ['id', 'sync_code', 'username', 'first_name', 'warehouse_id', 'can_create_nomenclature', 'is_active']
