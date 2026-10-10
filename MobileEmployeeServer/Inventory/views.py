from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status, viewsets
from django.utils import timezone

from drf_spectacular.utils import (
    OpenApiExample,
    OpenApiParameter,
    OpenApiResponse,
    OpenApiTypes,
    extend_schema,
    extend_schema_view,
)

from .models import SyncItem, MobileUser, SyncAddressedItem
from .mixins import BasicAuthMixin, PaginationMixin
from .serializers import MobileUserSerializer, MobileUserReadSerializer


# ========================================== #
# 1. СЕРВЕРНЫЕ ЭНДПОИНТЫ (ДОСТУПНОСТЬ И ВРЕМЯ)
# ========================================== #

@extend_schema(
    tags=['Сервер'],
    summary="Проверка доступности API",
    description="Эндпоинт для проверки работоспособности API. Не требует авторизации.",
    responses={
        200: OpenApiResponse(
            description="API работает",
            response=OpenApiTypes.OBJECT,
            examples=[
                OpenApiExample(
                    'success_response',
                    value={'success': True, 'message': 'API is working'},
                )
            ]
        )
    }
)
class HealthCheckView(APIView):
    """Проверка доступности API (Не авторизованный пользователь)"""

    def get(self, request):
        return Response({
            'success': True,
            'message': 'API is working'
        })


@extend_schema(
    tags=['Сервер'],
    summary="Текущее время сервера",
    description="Возвращает текущее время сервера с учетом часового пояса. Требует авторизации.",
    responses={
        200: OpenApiResponse(
            description="Время успешно получено",
            response=OpenApiTypes.OBJECT,
            examples=[
                OpenApiExample(
                    'success_response',
                    value={
                        'success': True,
                        'server_time': '2026-05-20T17:30:00.123456+03:00',
                        'timestamp': 1716215400,
                        'timezone': 'Europe/Moscow'
                    },
                )
            ]
        ),
        401: OpenApiResponse(description="Требуется авторизация")
    }
)
class ServerTimeView(BasicAuthMixin, APIView):
    """Возвращает текущее время сервера (Авторизованный пользователь)"""
    
    def get(self, request):
        now = timezone.now()
        return Response({
            'success': True,
            'server_time': now.isoformat(),
            'timestamp': int(now.timestamp()),
            'timezone': timezone.get_current_timezone_name()
        })


# ========================================== #
# 2. ЭНДПОИНТЫ ОБЩИХ ДАННЫХ (СПРАВОЧНИКИ)
# ========================================== #

class UnifiedSyncView(BasicAuthMixin, PaginationMixin, APIView):
    """" Обработчик универсальной синхронизации """

    @extend_schema(
        tags=['Общие данные'],
        summary="Размещение пакета изменений на сервере",
        description="Обновляет или создает записи, либо помечает их как удаленные при значении data: 'DELETED'.",
        request=OpenApiTypes.OBJECT,  # Указываем, что ждем JSON-объект
        examples=[
            OpenApiExample(
                'Пример запроса на синхронизацию',
                value=[
                        {"sync_code": "prod_1", "model_type": "Справочник объект: Номенклатура", "data": {"name": "Товар 1", "price": 100}},
                        {"sync_code": "prod_3", "model_type": "Справочник объект: Номенклатура", "data": {"name": "Товар 3", "price": 200}},
                        {"sync_code": "prod_2", "model_type": None, "data": "DELETED"}
                    ]
            )
        ],
        responses={
            200: OpenApiResponse(
                description="Пакет успешно обработан",
                response=OpenApiTypes.OBJECT,
                examples=[OpenApiExample('Успех', value={"success": True})]
            ),
            400: OpenApiResponse(
                description="Неверная структура данных или отсутствуют обязательные поля",
                response=OpenApiTypes.OBJECT,
                examples=[OpenApiExample('Ошибка валидации', value={"error": "Ожидался массив объектов в корне запроса."})]
            )
        }
    )
    def post(self, request, *args, **kwargs):
        """ Обработка запроса на размещение пакета обмена на сервере """
        # Так как JSON прилетает в виде [{...}, {...}], данные находятся прямо в request.data
        items = request.data
        
        # Защитная проверка: если 1С прислала не массив, принудительно делаем его списком или возвращаем 400
        if not isinstance(items, list):
            return Response(
                {"detail": "Ожидался массив объектов в корне запроса."}, 
                status=status.HTTP_400_BAD_REQUEST
            )

        # Перебираем пакет изменений
        for item in items:
            sync_code = item.get('sync_code')
            model_type = item.get('model_type')
            raw_data = item.get('data')

            if raw_data == "DELETED":
                SyncItem.objects.update_or_create(
                    sync_code=sync_code,
                    defaults={'model_type': model_type, 'is_deleted': True, 'data': None}
                )
            else:
                SyncItem.objects.update_or_create(
                    sync_code=sync_code,
                    defaults={'model_type': model_type, 'is_deleted': False, 'data': raw_data}
                )

        return Response({"success": True}, status=status.HTTP_200_OK)

    @extend_schema(
        tags=['Общие данные'],
        summary="Скачивание изменений со шлюза.",
        description="Используется для получения актуальных данных по конкретному виду объекта с поддержкой фильтрации по времени изменения и пагинации.",
        parameters=[
            OpenApiParameter(
                name='type', 
                type=OpenApiTypes.STR, 
                location=OpenApiParameter.QUERY, 
                required=True, 
                description="Тип модели для синхронизации (например, 'products')"
            ),
            OpenApiParameter(
                name='since', 
                type=OpenApiTypes.DATETIME, 
                location=OpenApiParameter.QUERY, 
                required=False, 
                description="ISO дата-время. Возвращает изменения строго после этой даты."
            ),
            OpenApiParameter(
                name='page', 
                type=OpenApiTypes.INT, 
                location=OpenApiParameter.QUERY, 
                required=False, 
                description="Номер запрашиваемой страницы (по умолчанию 1)"
            ),
            OpenApiParameter(
                name='page_size', 
                type=OpenApiTypes.INT, 
                location=OpenApiParameter.QUERY, 
                required=False, 
                description="Количество элементов на странице (по умолчанию 100, max 1000)"
            ),
        ],
        responses={
            200: OpenApiResponse(
                description="Успешное получение списка изменений",
                response=OpenApiTypes.OBJECT,
                examples=[
                    OpenApiExample(
                        'Пример успешного ответа с данными',
                        value={
                            "success": True,
                            "type": "products",
                            "server_time": "2026-10-09T10:30:00.000Z",
                            "pagination": {
                                "current_page": 1,
                                "page_size": 100,
                                "total_pages": 5,
                                "total_records": 450,
                                "has_next": True,
                                "has_previous": False,
                                "next_page": 2,
                                "previous_page": None
                            },
                            "items": [
                                {"sync_code": "prod_1", "is_deleted": False, "data": {"name": "Товар 1", "price": 100}},
                                {"sync_code": "prod_2", "is_deleted": True, "data": None}
                            ]
                        }
                    )
                ]
            ),
            400: OpenApiResponse(
                description="Ошибка в переданных query-параметрах",
                response=OpenApiTypes.OBJECT,
                examples=[OpenApiExample('Ошибка параметров', value={"error": "Параметр 'type' обязателен."})]
            ),
            404: OpenApiResponse(
                description="Запрошенная страница не существует",
                response=OpenApiTypes.OBJECT,
                examples=[OpenApiExample('Страница не найдена', value={"error": "Page not found", "message": "Page 999 does not exist. Total pages: 5"})]
            )
        }
    )
    def get(self, request, *args, **kwargs):
        """ Эндпоинт для Мобильного приложения (Скачивание изменений со шлюза) с пагинацией """        
        # 1. Валидация параметров синхронизации
        model_type, parsed_datetime, error_response = self.validate_get_params(request)
        if error_response:
            return error_response

        # 2. Формирование базового QuerySet
        queryset = SyncItem.objects.filter(model_type=model_type)

        if parsed_datetime:
            queryset = queryset.filter(updated_at__gt=parsed_datetime)

        queryset = queryset.order_by('updated_at')

        # 3. Извлечение параметров пагинации из запроса
        # Используем лимиты из вашего CustomPagination (1000 макс, 100 по умолчанию)
        page, page_size = self.get_pagination_params(
            request, 
            max_page_size=1000, 
            default_page_size=100
        )

        # 4. Применение пагинации
        current_page, pagination_data = self.paginate_queryset(queryset, page, page_size)
        
        # Если страница не найдена (например, page=9999), миксин вернет (None, Response)
        if current_page is None:
            return pagination_data  # Это готовый Response с ошибкой 404

        # 5. Сериализация объектов только для текущей страницы
        result = [
            {
                "sync_code": item.sync_code,
                "is_deleted": item.is_deleted,
                "data": item.data 
            }
            for item in current_page  # Итерируемся по странице, а не по всему queryset
        ]

        # 6. Формирование финального ответа
        return Response({
            "success": True,
            "type": model_type,
            "server_time": timezone.now().isoformat(),
            "pagination": pagination_data,  # Метаданные (текущая страница, всего записей и т.д.)
            "items": result
        }, status=status.HTTP_200_OK)


@extend_schema(
    tags=['Общие данные'],
    summary="Список типов данных синхронизации",
    description="Возвращает массив строк, содержащий все уникальные типы данных 1С (model_type), которые на данный момент зарегистрированы в базе шлюза.",
    responses={
        200: OpenApiResponse(
            description="Список типов успешно получен",
            response=OpenApiTypes.OBJECT,
            examples=[
                OpenApiExample(
                    'success_response',
                    value={
                        'success': True,
                        'count': 'Количество типов',
                        'model_types': 'Массив строк с типами моделей 1С'
                    },
                )
            ]
        ),
        401: OpenApiResponse(description="Требуется авторизация")
    }
)
class SyncModelTypesView(BasicAuthMixin, APIView):
    """
    Эндпоинт, возвращающий список всех уникальных типов моделей 1С,
    которые сейчас зарегистрированы в базе данных шлюза.
    """
    def get(self, request, *args, **kwargs):
        # Находим уникальные значения поля model_type, исключая пустые
        unique_types = SyncItem.objects.exclude(
            model_type=""
        ).values_list(
            'model_type', flat=True
        ).distinct()
        
        # Превращаем QuerySet в обычный массив строк Python
        types_list = list(unique_types)
        
        return Response({
            "success": True,
            "count": len(types_list),
            "model_types": types_list
        }, status=status.HTTP_200_OK)


# ========================================== #
# 3. ЭНДПОИНТЫ МОДЕЛИ ПОЛЬЗОВАТЕЛЯ
# ========================================== #

@extend_schema_view(
    get=extend_schema(
        tags=['Пользователи'],
        summary='Получение списка пользователей или поиск по sync_code',
        description=(
            'Если вызвать метод без параметров, он вернет список всех мобильных пользователей. '
            'Если передать query-параметр `sync_code`, вернет данные одного конкретного пользователя.'
        ),
        parameters=[
            OpenApiParameter(
                name='sync_code',
                type=OpenApiTypes.UUID,
                location=OpenApiParameter.QUERY,
                description='Уникальный код синхронизации 1С для поиска конкретного пользователя',
                required=False
            )
        ],
        responses={
            200: OpenApiResponse(
                description='Успешный ответ (массив пользователей или один объект)',
                response=MobileUserReadSerializer(many=True),
            ),
            404: OpenApiResponse(
                description='Пользователь с указанным sync_code не найден',
                response=OpenApiTypes.OBJECT
            )
        }
    ),
    post=extend_schema(
        tags=['Пользователи'],
        summary='Пакетная синхронизация пользователей из 1С (Создание/Обновление/Удаление)',
        description=(
            'Принимает массив элементов непосредственно в корне POST-запроса. Для каждого элемента '
            'выполняется Upsert (создание или обновление) по полю `sync_code`. '
            'Если во вложенном поле `data` передана строка `"DELETED"`, пользователь деактивируется '
            '(`is_active=False`). Все пришедшие пароли автоматически хешируются.'
        ),
        # Указываем, что в теле запроса ожидается массив (список объектов)
        request=MobileUserSerializer(many=True), 
        responses={
            200: OpenApiResponse(
                description='Синхронизация успешно выполнена для всего массива',
                response=OpenApiTypes.OBJECT,
                examples=[
                    OpenApiExample(
                        'success_sync', 
                        value={"success": True, "message": "Синхронизация завершена"}
                    )
                ]
            ),
            400: OpenApiResponse(
                description='Ошибка валидации структуры запроса или некорректный JSON внутри поля data',
                response=OpenApiTypes.OBJECT
            )
        }
    )
)
class SyncMobileUsersView(BasicAuthMixin, APIView):
    """
    Контроллер для управления мобильными пользователями.
    Разделен на GET (для мобильного приложения / проверок) и POST (для пакетного обмена с 1С).
    """

    def get(self, request):
        sync_code = request.query_params.get('sync_code')
        
        # 1. Сценарий поиска одиночного пользователя по sync_code
        if sync_code:
            try:
                user = MobileUser.objects.get(sync_code=sync_code)
                serializer = MobileUserReadSerializer(user)
                return Response(serializer.data, status=status.HTTP_200_OK)
            except MobileUser.DoesNotExist:
                return Response(
                    {"detail": f"Пользователь с sync_code {sync_code} не найден."}, 
                    status=status.HTTP_404_NOT_FOUND
                )
        
        # 2. Сценарий получения полного списка пользователей
        users = MobileUser.objects.all()
        serializer = MobileUserReadSerializer(users, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def post(self, request):
        # Так как JSON прилетает в виде [{...}, {...}], данные находятся прямо в request.data
        items = request.data
        
        # Защитная проверка: если 1С прислала не массив, принудительно делаем его списком или возвращаем 400
        if not isinstance(items, list):
            return Response(
                {"detail": "Ожидался массив объектов в корне запроса."}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Передаем массив в сериализатор-парсер с флагом many=True
        serializer = MobileUserSerializer(data=items, many=True)
        
        if serializer.is_valid():
            # Запускаем сохранение. Сериализатор сам переберет массив,
            # сделает update_or_create для обычных данных или выставит is_active=False для "DELETED"
            serializer.save()
            return Response(
                {"success": True, "message": "Синхронизация завершена"}, 
                status=status.HTTP_200_OK
            )
            
        # Если хотя бы в одном элементе массива ошибка, DRF вернет структурированный ответ с ошибками по индексам
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


# ================================================= #
# 4. ЭНДПОИНТЫ АДРЕСНЫХ ДАННЫХ (РЕГИСТРЫ, ДОКУМЕНТЫ)
# ================================================= #


class UnifiedAddressedSyncView(BasicAuthMixin, PaginationMixin, APIView):
    """" Обработчик универсальной синхронизации адресных данных """

    @extend_schema(
        tags=['Адресные данные'],
        summary="Размещение пакета адресных измеенний на сервере",
        description="Принимает пакет изменений для адресных сущностей (регистры, документы). Обновляет или создает записи, либо помечает их как удаленные при значении 'DELETED'.",
        request=OpenApiTypes.OBJECT,  # Указываем, что ждем JSON-объект
        examples=[
            OpenApiExample(
                'Пример тела POST запроса',
                value=[
                        {"storage_code": "UUID_4", "sync_code": "UUID_1", "model_type": "Справочник объект: Номенклатура", "data": {"name": "Товар 1", "price": 100}},
                        {"storage_code": "UUID_5", "sync_code": "UUID_3", "model_type": "Справочник объект: Номенклатура", "data": {"name": "Товар 3", "price": 200}},
                        {"storage_code": None, "sync_code": "UUID_2", "model_type": None, "data": "DELETED"}
                    ]
            )
        ],
        responses={
            200: OpenApiResponse(
                description="Пакет успешно обработан",
                response=OpenApiTypes.OBJECT,
                examples=[OpenApiExample('Успех', value={"success": True})]
            ),
            400: OpenApiResponse(
                description="Неверная структура данных или отсутствуют обязательные поля",
                response=OpenApiTypes.OBJECT,
                examples=[OpenApiExample('Ошибка валидации', value={"error": "Ожидался массив объектов в корне запроса."})]
            )
        }
    )
    def post(self, request, *args, **kwargs):
        """ Обработка запроса на размещение пакета обмена на сервере """

        items = request.data
        
        # Защитная проверка: если 1С прислала не массив, принудительно делаем его списком или возвращаем 400
        if not isinstance(items, list):
            return Response(
                {"detail": "Ожидался массив объектов в корне запроса."}, 
                status=status.HTTP_400_BAD_REQUEST
            )

        # Перебираем пакет изменений
        for item in items:
            storage_code = item.get('storage_code')
            sync_code = item.get('sync_code')
            model_type = item.get('model_type')
            raw_data = item.get('data')

            if raw_data == "DELETED":
                SyncAddressedItem.objects.update_or_create(
                    sync_code=sync_code,
                    defaults={
                        'storage_code': None,
                        'model_type': None,
                        'is_deleted': True,
                        'data': None
                    }
                )
            else:
                SyncAddressedItem.objects.update_or_create(
                    sync_code=sync_code,
                    defaults={
                        'storage_code': storage_code,
                        'model_type': model_type,
                        'is_deleted': False,
                        'data': raw_data
                    }
                )

        return Response({"success": True}, status=status.HTTP_200_OK)

    @extend_schema(
        tags=['Адресные данные'],
        summary="Скачивание адресных изменений со шлюза",
        description="Используется мобильным приложением для получения актуальных данных по конкретной складу и конкретному типу объекта с поддержкой фильтрации по времени изменения и пагинации.",
        parameters=[
            OpenApiParameter(
                name='storage_code', 
                type=OpenApiTypes.STR, 
                location=OpenApiParameter.QUERY, 
                required=True, 
                description="Склад-получатель (UUID)"
            ),
            OpenApiParameter(
                name='model_type', 
                type=OpenApiTypes.STR, 
                location=OpenApiParameter.QUERY, 
                required=False, 
                description="Тип модели для синхронизации (например, 'products')"
            ),
            OpenApiParameter(
                name='since', 
                type=OpenApiTypes.DATETIME, 
                location=OpenApiParameter.QUERY, 
                required=False, 
                description="ISO дата-время. Возвращает изменения строго после этой даты."
            ),
            OpenApiParameter(
                name='page', 
                type=OpenApiTypes.INT, 
                location=OpenApiParameter.QUERY, 
                required=False, 
                description="Номер запрашиваемой страницы (по умолчанию 1)"
            ),
            OpenApiParameter(
                name='page_size', 
                type=OpenApiTypes.INT, 
                location=OpenApiParameter.QUERY, 
                required=False, 
                description="Количество элементов на странице (по умолчанию 100, max 1000)"
            ),
        ],
        responses={
            200: OpenApiResponse(
                description="Успешное получение списка изменений",
                response=OpenApiTypes.OBJECT,
                examples=[
                    OpenApiExample(
                        'Пример успешного ответа с данными',
                        value={
                            "success": True,
                            "type": "products",
                            "server_time": "2026-10-09T10:30:00.000Z",
                            "pagination": {
                                "current_page": 1,
                                "page_size": 100,
                                "total_pages": 5,
                                "total_records": 450,
                                "has_next": True,
                                "has_previous": False,
                                "next_page": 2,
                                "previous_page": None
                            },
                            "items": [
                                {"storage_code": "UUID_1", "sync_code": "UUID_5", "is_deleted": False, "data": {"name": "Товар 1", "price": 100}},
                                {"storage_code": "UUID_3", "sync_code": "UUID_6", "is_deleted": True, "data": None}
                            ]
                        }
                    )
                ]
            ),
            400: OpenApiResponse(
                description="Ошибка в переданных query-параметрах",
                response=OpenApiTypes.OBJECT,
                examples=[OpenApiExample('Ошибка параметров', value={"error": "Параметр 'type' обязателен."})]
            ),
            404: OpenApiResponse(
                description="Запрошенная страница не существует",
                response=OpenApiTypes.OBJECT,
                examples=[OpenApiExample('Страница не найдена', value={"error": "Page not found", "message": "Page 999 does not exist. Total pages: 5"})]
            )
        }
    )
    def get(self, request, *args, **kwargs):
        """ Эндпоинт для Мобильного приложения (Скачивание изменений со шлюза) с пагинацией """        
        # 1. Валидация параметров синхронизации
        storage_type, model_type, parsed_datetime, error_response = self.validate_get_params(request)
        if error_response:
            return error_response

        # 2. Формирование базового QuerySet
        queryset = SyncAddressedItem.objects.filter(storage_type=storage_type)

        if parsed_datetime:
            queryset = queryset.filter(updated_at__gt=parsed_datetime)

        if model_type:
            queryset = queryset.filter(model_type=model_type)

        queryset = queryset.order_by('updated_at')

        # 3. Извлечение параметров пагинации из запроса
        # Используем лимиты из вашего CustomPagination (1000 макс, 100 по умолчанию)
        page, page_size = self.get_pagination_params(
            request, 
            max_page_size=1000, 
            default_page_size=100
        )

        # 4. Применение пагинации
        current_page, pagination_data = self.paginate_queryset(queryset, page, page_size)
        
        # Если страница не найдена (например, page=9999), миксин вернет (None, Response)
        if current_page is None:
            return pagination_data  # Это готовый Response с ошибкой 404

        # 5. Сериализация объектов только для текущей страницы
        result = [
            {
                "model_type": item.model_type,
                "sync_code": item.sync_code,
                "is_deleted": item.is_deleted,
                "data": item.data 
            }
            for item in current_page  # Итерируемся по странице, а не по всему queryset
        ]

        # 6. Формирование финального ответа
        return Response({
            "success": True,
            "type": model_type,
            "server_time": timezone.now().isoformat(),
            "pagination": pagination_data,  # Метаданные (текущая страница, всего записей и т.д.)
            "items": result
        }, status=status.HTTP_200_OK)
