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

from .models import SyncItem, MobileUser
from .mixins import BasicAuthMixin, SyncValidationMixin, PaginationMixin
from .serializers import MobileUserSerializer


# ========================================== #
# 1. СЕРВЕРНЫЕ ЭНДПОИНТЫ (ДОСТУПНОСТЬ И ВРЕМЯ)
# ========================================== #

@extend_schema(
    tags=['Server'],
    summary="Проверка доступности API",
    description="Эндпоинт для проверки работоспособности API. Не требует авторизации.",
    responses={
        200: OpenApiResponse(
            description="API работает",
            response=OpenApiTypes.OBJECT,
            examples=[
                OpenApiExample(
                    'success_response',
                    value={'status': 'ok', 'message': 'API is working'},
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
    tags=['Server'],
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


class UnifiedSyncView(BasicAuthMixin, SyncValidationMixin, PaginationMixin, APIView):
    """" Обработчик универсальной синхронизации """

    @extend_schema(
        tags=['Синхронизация'],
        summary="Размещение пакета измеенний на сервере",
        description="Принимает пакет изменений для сущностей определенного типа. Обновляет или создает записи, либо помечает их как удаленные при значении 'DELETED'.",
        request=OpenApiTypes.OBJECT,  # Указываем, что ждем JSON-объект
        examples=[
            OpenApiExample(
                'Пример запроса на синхронизацию',
                value={
                    "model_type": "products",
                    "items": [
                        {"sync_code": "prod_1", "data": {"name": "Товар 1", "price": 100}},
                        {"sync_code": "prod_2", "data": "DELETED"}
                    ]
                }
            )
        ],
        responses={
            200: OpenApiResponse(
                description="Пакет успешно обработан",
                response=OpenApiTypes.OBJECT,
                examples=[OpenApiExample('Успех', value={"status": "success"})]
            ),
            400: OpenApiResponse(
                description="Неверная структура данных или отсутствуют обязательные поля",
                response=OpenApiTypes.OBJECT,
                examples=[OpenApiExample('Ошибка валидации', value={"error": "Параметры 'model_type' и 'items' (массив) обязательны."})]
            )
        }
    )
    def post(self, request, *args, **kwargs):
        """ Обработка запроса на размещение пакета обмена на сервере """
        payload, error_response = self.validate_post_payload(request)
        if error_response:
            return error_response

        model_type = payload.get('model_type')
        items = payload.get('items')

        # Перебираем пакет изменений
        for item in items:
            sync_code = item.get('sync_code')
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
        tags=['Синхронизация'],
        summary="Скачивание изменений со шлюза",
        description="Используется мобильным приложением для получения актуальных данных по конкретной модели с поддержкой фильтрации по времени изменения и пагинации.",
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
    tags=['Синхронизация'],
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
class SyncModelTypesView(APIView):
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


@extend_schema_view(
    list=extend_schema(
        tags=['Mobile Users'],
        summary='Получение списка активных мобильных пользователей',
        description='Возвращает список всех мобильных пользователей, у которых флаг `is_active` равен True. Деактивированные пользователи исключаются из списка.',
        responses={
            200: OpenApiResponse(
                description='Успешный ответ со списком пользователей',
                response=MobileUserSerializer(many=True),
            )
        },
    ),
    create=extend_schema(
        tags=['Mobile Users'],
        summary='Создание нового мобильного пользователя',
        description='Принимает данные из 1С, создает пользователя и автоматически хеширует переданный пароль.',
        responses={
            201: OpenApiResponse(
                description='Пользователь успешно создан',
                response=MobileUserSerializer,
            ),
            400: OpenApiResponse(
                description='Ошибка валидации (например, логин уже занят или не заполнены обязательные поля)',
                response=OpenApiTypes.OBJECT,
                examples=[
                    OpenApiExample(
                        'validation_error',
                        value={
                            'username': [
                                'Пользователь с таким именем уже существует.'
                            ]
                        },
                    )
                ],
            ),
        },
    ),
    retrieve=extend_schema(
        tags=['Mobile Users'],
        summary='Получение данных конкретного пользователя',
        description='Возвращает профиль мобильного пользователя по его логину (`username`). Позволяет просматривать в том числе деактивированных пользователей.',
        responses={
            200: OpenApiResponse(
                description='Данные пользователя найдены',
                response=MobileUserSerializer,
            ),
            404: OpenApiResponse(
                description='Пользователь с таким логином не найден',
                response=OpenApiTypes.OBJECT,
                examples=[
                    OpenApiExample(
                        'not_found_error',
                        value={'detail': 'Страница не найдена.'},
                    )
                ],
            ),
        },
    ),
    update=extend_schema(
        tags=['Mobile Users'],
        summary='Полное обновление данных пользователя (PUT)',
        description='Полностью перезаписывает поля мобильного пользователя. Если поле `password` передано, оно будет захешировано и обновлено.',
        responses={
            200: OpenApiResponse(
                description='Данные успешно обновлены',
                response=MobileUserSerializer,
            )
        },
    ),
    partial_update=extend_schema(
        tags=['Mobile Users'],
        summary='Частичное обновление данных пользователя (PATCH)',
        description='Изменяет только переданные поля пользователя (например, только `warehouse_id` или только `password`). Рекомендуемый метод для синхронизации из 1С.',
        responses={
            200: OpenApiResponse(
                description='Данные успешно изменены',
                response=MobileUserSerializer,
            )
        },
    ),
    destroy=extend_schema(
        tags=['Mobile Users'],
        summary='Деактивация пользователя (Мягкое удаление)',
        description='Переводит флаг `is_active` пользователя в состояние `False`. Физического удаления из БД не происходит для сохранения целостности связанных данных.',
        responses={
            204: OpenApiResponse(
                description='Пользователь успешно деактивирован. Тело ответа отсутствует.',
                response=OpenApiTypes.NONE,
            ),
            400: OpenApiResponse(
                description='Пользователь уже был деактивирован ранее',
                response=OpenApiTypes.OBJECT,
                examples=[
                    OpenApiExample(
                        'already_inactive',
                        value={'detail': 'Пользователь уже деактивирован.'},
                    )
                ],
            ),
        },
    ),
)
class MobileUserViewSet(viewsets.ModelViewSet):
    queryset = MobileUser.objects.all()
    serializer_class = MobileUserSerializer
    lookup_field = 'username'
    lookup_value_regex = '[^/]+'

    def get_queryset(self):
        if self.action == 'list':
            return MobileUser.objects.filter(is_active=True)
        return MobileUser.objects.all()

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        if not instance.is_active:
            return Response(
                {'detail': 'Пользователь уже деактивирован.'},
                status=status.HTTP_400_BAD_REQUEST,
                )

        instance.is_active = False
        instance.save()
        return Response(status=status.HTTP_204_NO_CONTENT)
