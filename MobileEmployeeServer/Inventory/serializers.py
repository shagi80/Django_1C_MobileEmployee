from rest_framework import serializers
from .models import MobileUser


class MobileUserSerializer(serializers.ModelSerializer):
    # Сделайте password необязательным при обновлении
    password = serializers.CharField(write_only=True, required=False)

    class Meta:
        model = MobileUser
        fields = [
            'username',
            'password',
            'can_create_nomenclature',
            'warehouse_id',
            ]

    def create(self, validated_data):
        password = validated_data.pop('password', None)
        user = MobileUser(**validated_data)
        if password:
            user.set_password(password)
            user.save()
            return user

    def update(self, instance, validated_data):
        password = validated_data.pop('password', None)
        # Обновляем все остальные поля
        for attr, value in validated_data.items():
            setattr(instance, attr, value)

        # Меняем пароль только если 1С прислала новый
        if password:
            instance.set_password(password)

        instance.save()
        return instance