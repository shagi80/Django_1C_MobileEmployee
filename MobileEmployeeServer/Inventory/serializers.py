import json
from rest_framework import serializers
from django.contrib.auth.hashers import make_password
from .models import MobileUser


class MobileUserSerializer(serializers.ModelSerializer):
    data = serializers.CharField(write_only=True)
    sync_code = serializers.UUIDField(required=True)

    class Meta:
        model = MobileUser
        # Используем стандартное поле first_name вместо кастомного full_name
        fields = ['sync_code', 'data', 'username', 'first_name', 'warehouse_id', 'can_create_nomenclature', 'is_active']
        extra_kwargs = {'username': {'required': False}}

    def to_internal_value(self, data):
        sync_code = data.get('sync_code')
        raw_data_str = data.get('data', '').strip()

        if raw_data_str == "DELETED":
            return {'sync_code': sync_code, 'is_active': False, '_is_deleted_action': True}

        try:
            parsed_data = json.loads(raw_data_str)
            value_block = parsed_data.get('#value', {})
        except (ValueError, TypeError, KeyError):
            raise serializers.ValidationError({"data": "Некорректный формат JSON внутри поля data."})

        internal_data = {
            'sync_code': sync_code,
            'username': value_block.get('Логин'),
            'first_name': value_block.get('Description'),  
            'warehouse_id': value_block.get('Склад'),
            'can_create_nomenclature': value_block.get('МожетСоздаватьПоступление', False),
            'is_active': not value_block.get('DeletionMark', False),
            '_is_deleted_action': False
        }
        
        self.context[f'raw_password_{sync_code}'] = value_block.get('Пароль')
        return internal_data

    def validate(self, attrs):
        if attrs.get('_is_deleted_action'):
            return attrs
        if not attrs.get('username') and not MobileUser.objects.filter(sync_code=attrs.get('sync_code')).exists():
            raise serializers.ValidationError({"username": "Поле 'Логин' обязательно для нового пользователя."})
        return attrs

    def save(self, **kwargs):
        sync_code = self.validated_data.get('sync_code')
        
        if self.validated_data.get('_is_deleted_action'):
            MobileUser.objects.filter(sync_code=sync_code).update(is_active=False)
            return None

        raw_password = self.context.get(f'raw_password_{sync_code}')
        
        defaults = {
            'username': self.validated_data.get('username'),
            'first_name': self.validated_data.get('first_name'),  
            'warehouse_id': self.validated_data.get('warehouse_id'),
            'can_create_nomenclature': self.validated_data.get('can_create_nomenclature'),
            'is_active': self.validated_data.get('is_active', True)
        }
        
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
        # Отдаем first_name мобильному приложению вместо full_name
        fields = ['id', 'sync_code', 'username', 'first_name', 'warehouse_id', 'can_create_nomenclature', 'is_active']
