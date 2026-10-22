from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.utils import timezone
from django.db import transaction

from drf_spectacular.utils import (
    OpenApiExample,
    OpenApiParameter,
    OpenApiResponse,
    OpenApiTypes,
    extend_schema,
    extend_schema_view,
)

from .models import SyncItem, MobileUser, SyncDocumentItem
from .mixins import BasicAuthMixin, PaginationMixin
from .serializers import (
    MobileUserSerializer,
    MobileUserReadSerializer,
    SyncBulkDocumentSerializer,
    SyncOneDocumentSerializer)

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
# 2. ЭНДПОИНТЫ ДАННЫХ
# ========================================== #

class UnifiedSyncView(BasicAuthMixin, PaginationMixin, APIView):
    """" Обработчик универсальной синхронизации """

    @extend_schema(
        tags=['Общие данные'],
        summary="Размещение пакета данных на сервере",
        description=(
            "Принимает пакет изменений от 1С. Обновляет существующие записи по `sync_code` или создает новые. "
            "Если поле `data` имеет строковое значение `'DELETED'`, запись помечается как удаленная (`is_deleted=True`), "
        ),
        request={
            "application/json": OpenApiTypes.OBJECT
        },
        examples=[
            OpenApiExample(
                'Пример запроса на синхронизацию (Массив объектов)',
                value=[
                    {
                        "sync_code": "uuid_item", 
                        "model_type": "Номенклатура", 
                        "data": {"Ref": "uuid_item", "Description": "Товар"}
                    },
                    {
                        "sync_code": "prod_3", 
                        "model_type": "Склады", 
                        "data": {"Ref": "uuid_ggod1", "Description": "Склад Инструмента"}
                    }
                ]
            )
        ],
        responses={
            200: OpenApiResponse(
                description="Пакет успешно обработан и сохранен в базу данных",
                response=OpenApiTypes.OBJECT,
                examples=[OpenApiExample('Успех', value={"success": True})]
            ),
            400: OpenApiResponse(
                description="Неверная структура данных (не массив) или отсутствует обязательный 'sync_code'",
                response=OpenApiTypes.OBJECT,
                examples=[
                    OpenApiExample(
                        'Ошибка: Передан не массив', 
                        value={"detail": "Ожидался массив объектов в корне запроса."}
                    ),
                    OpenApiExample(
                        'Ошибка: Пропущен sync_code', 
                        value={"detail": "Отсутствует обязательное поле 'sync_code' в одном из элементов."}
                    )
                ]
            ),
            500: OpenApiResponse(
                description="Внутренняя ошибка сервера при пакетной записи в БД (база недоступна или заблокирована)",
                response=OpenApiTypes.OBJECT,
                examples=[
                    OpenApiExample(
                        'Ошибка базы данных', 
                        value={"detail": "Ошибка при сохранении пакета данных: ... текст ошибки ..."}
                    )
                ]
            )
        }
    )
    def post(self, request, *args, **kwargs):
        """ Обработка запроса на размещение пакета обмена на сервере """
        items = request.data
        
        # 1. Защитная проверка типа
        if not isinstance(items, list):
            return Response(
                {"detail": "Ожидался массив объектов в корне запроса."}, 
                status=status.HTTP_400_BAD_REQUEST
            )

        # 2. Если массив пустой, сразу возвращаем успех
        if not items:
            return Response({"success": True}, status=status.HTTP_200_OK)

        # Подготавливаем списки объектов для базы данных
        items_to_upsert = []

        # 3. Перебираем пакет изменений в памяти (без обращений к БД)
        for item in items:
            sync_code = item.get('sync_code')
            model_type = item.get('model_type')
            raw_data = item.get('data')

            # Валидация обязательного уникального ключа
            if not sync_code:
                return Response(
                    {"detail": f"Отсутствует обязательное поле 'sync_code' в одном из элементов."}, 
                    status=status.HTTP_400_BAD_REQUEST
                )

            if raw_data == "DELETED":
                sync_item = SyncItem(
                    sync_code=sync_code,
                    model_type=None,
                    is_deleted=True
                )
            else:
                sync_item = SyncItem(
                    sync_code=sync_code,
                    model_type=model_type,
                    is_deleted=False,
                    data=raw_data
                )
            
            items_to_upsert.append(sync_item)

        # 4. Выполняем ОДИН атомарный запрос к БД для всего пакета данных
        try:
            with transaction.atomic():
                SyncItem.objects.bulk_create(
                    items_to_upsert,
                    update_conflicts=True,
                    unique_fields=['sync_code'],  # Поле, по которому база понимает, что запись уже есть
                    update_fields=['model_type', 'is_deleted', 'data', 'updated_at'] # Что обновлять
                )
        except Exception as e:
            return Response(
                {"detail": f"Ошибка при сохранении пакета данных: {str(e)}"}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        return Response({"success": True}, status=status.HTTP_200_OK)

    @extend_schema(
        tags=['Общие данные'],
        summary="Скачивание изменений со шлюза (для мобильного приложения).",
        description="Используется для получения актуальных данных с поддержкой фильтрации по типу данных, коду синхронизации и времени изменения и пагинации.",
        parameters=[
            OpenApiParameter(
                name='model_type', 
                type=OpenApiTypes.STR, 
                location=OpenApiParameter.QUERY, 
                required=False, 
                description="Тип данных для фильтрации (например, 'Номенклатура')."
            ),
            OpenApiParameter(
                name='sync_code', 
                type=OpenApiTypes.STR, 
                location=OpenApiParameter.QUERY, 
                required=False, 
                description="Уникальный код синхронизации конкретного объекта."
            ),
            OpenApiParameter(
                name='updated_at', 
                type=OpenApiTypes.DATETIME, 
                location=OpenApiParameter.QUERY, 
                required=False, 
                description="ISO дата-время. Возвращает изменения строго ПОСЛЕ указанной даты (`updated_at__gt`)."
            ),
            OpenApiParameter(
                name='page', 
                type=OpenApiTypes.INT, 
                location=OpenApiParameter.QUERY, 
                required=False, 
                description="Номер запрашиваемой страницы (по умолчанию 1)."
            ),
            OpenApiParameter(
                name='page_size', 
                type=OpenApiTypes.INT, 
                location=OpenApiParameter.QUERY, 
                required=False, 
                description="Количество элементов на странице (по умолчанию 100, max 1000)."
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
                            "server_time": "2026-10-14T18:30:00.000Z",
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
                                {
                                    "sync_code": "uuid_doc",
                                    "model_type": "ПеремещениеТоваров",
                                    "is_deleted": False,
                                    "data": {"Ref": "uuid_good", "count": 100}
                                },
                                {
                                    "sync_code": "uuid_item",
                                    "model_type": "Номенклатура",
                                    "is_deleted": True,
                                    "data": None
                                }
                            ]
                        }
                    )
                ]
            ),
            400: OpenApiResponse(
                description="Ошибка в формате переданных query-параметров",
                response=OpenApiTypes.OBJECT,
                examples=[OpenApiExample('Ошибка параметров', value={"error": "Неверный формат даты и времени"})]
            ),
            404: OpenApiResponse(
                description="Запрошенная страница пагинации не существует",
                response=OpenApiTypes.OBJECT,
                examples=[OpenApiExample('Страница не найдена', value={"error": "Page not found", "message": "Page 999 does not exist. Total pages: 5"})]
            )
        }
    )
    def get(self, request, *args, **kwargs):
        """ Эндпоинт для Мобильного приложения (Скачивание изменений со шлюза) с пагинацией """        
        # 1. Получение параметров синхронизации
        model_type = request.query_params.getlist('model_type')
        sync_code = request.query_params.getlist('sync_code')
        updated_at = request.query_params.get('updated_at')


        # 2. Формирование QuerySet
        filter_kwargs = {}

        if model_type:
            filter_kwargs['model_type__in'] = model_type
        if sync_code:
            filter_kwargs['sync_code__in'] = sync_code
        if updated_at:
            filter_kwargs['updated_at__gt'] = updated_at

        queryset = SyncItem.objects.filter(**filter_kwargs).order_by('updated_at')

        # 3. Извлечение параметров пагинации из запроса
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
                "model_type": item.model_type,
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


class UnifiedDocumentView(BasicAuthMixin, PaginationMixin, APIView):
    """" Обработчик универсальной синхронизации документов """

    @extend_schema(
        tags=['Документы'],
        summary="Размещение пакета документов на сервере",
        description=(
            "Принимает пакет документов от 1С. Обновляет существующие записи по `sync_code` или создает новые. "
            "Если поле `data` имеет строковое значение `'DELETED'`, запись помечается как удаленная (`is_deleted=True`), "
        ),
        request=SyncOneDocumentSerializer,
        examples=[
            OpenApiExample(
                'Пример запроса на синхронизацию (Массив документов)',
                value=[
                    {
                        "storage_to": "uuid_wh1",
                        "storage_from": "uuid_wh2",
                        "sync_code": "uuid_item", 
                        "doc_date": "12.10.2026 13:30:30",
                        "model_type": "ПеремещениеТоваров", 
                        "data": [{"Ref": "uuid_ggod1", "count": 200}]
                    },
                    {
                        "storage_to": "uuid_wh1",
                        "storage_from": None,
                        "sync_code": "prod_3", 
                        "doc_date": "10.11.2026 11:10:30",
                        "model_type": "ПоступлениеТовароУслуг", 
                        "data": [{"Ref": "uuid_ggod1", "count": 200}]
                    }
                ]
            )
        ],
        responses={
            200: OpenApiResponse(description="Пакет успешно обработан", response=OpenApiTypes.OBJECT),
            400: OpenApiResponse(description="Ошибка валидации данных", response=OpenApiTypes.OBJECT),
            500: OpenApiResponse(description="Ошибка базы данных", response=OpenApiTypes.OBJECT)
        }
    )
    def post(self, request, *args, **kwargs):
        """ Обработка запроса на размещение пакета документов на сервере """
        
        # 1. Валидация всего пакета данных через сериализатор
        serializer = SyncBulkDocumentSerializer(data=request.data)
        if not serializer.is_valid():
             return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        # Получаем уже очищенные и преобразованные данные (включая объекты datetime)
        validated_items = serializer.validated_data.get('items', [])

        # 2. Если массив пустой, сразу возвращаем успех
        if not validated_items:
            return Response({"success": True}, status=status.HTTP_200_OK)

        items_to_upsert = []

        # 3. Перебираем пакет изменений в памяти (теперь без ручной валидации типов)
        for item in validated_items:
            sync_code = item.get('sync_code')
            raw_data = item.get('data')

            if raw_data == "DELETED":
                sync_item = SyncDocumentItem(
                    sync_code=sync_code,
                    model_type=None,
                    storage_to=None,
                    storage_from=None,
                    is_deleted=True,
                    data=None,
                    doc_date=None
                )
            else:
                sync_item = SyncDocumentItem(
                    sync_code=sync_code,
                    model_type=item.get('model_type'),
                    storage_to=item.get('storage_to'),
                    storage_from=item.get('storage_from'),
                    is_deleted=False,
                    data=raw_data,
                    doc_date=item.get('doc_date')  
                )
            
                items_to_upsert.append(sync_item)

        # 4. Выполняем ОДИН атомарный запрос к БД для всего пакета данных
        try:
            with transaction.atomic():
                SyncDocumentItem.objects.bulk_create(
                    items_to_upsert,
                    update_conflicts=True,
                    unique_fields=['sync_code'],
                    update_fields=['storage_to', 'storage_from', 'model_type', 'is_deleted', 'data', 'doc_date', 'updated_at']
                )
        except Exception as e:
            return Response(
                {"detail": f"Ошибка при сохранении пакета данных: {str(e)}"}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        return Response({"success": True}, status=status.HTTP_200_OK)

    @extend_schema(
        tags=['Документы'],
        summary="Скачивание документов со шлюза (для мобильного приложения).",
        description="Используется для получения актуальных данных с поддержкой фильтрации по типу данных, складу, коду синхронизации, дате документа и пагинации.",
        parameters=[
            OpenApiParameter(
                name='model_type', 
                type=OpenApiTypes.STR, 
                location=OpenApiParameter.QUERY, 
                required=False, 
                description="Тип данных для фильтрации (например, 'ПеремещеинеТоваров')."
            ),
            OpenApiParameter(
                name='storage_to', 
                type=OpenApiTypes.STR, 
                location=OpenApiParameter.QUERY, 
                required=False, 
                description="Код склада-получателя для фильтрации."
            ),
            OpenApiParameter(
                name='storage_from', 
                type=OpenApiTypes.STR, 
                location=OpenApiParameter.QUERY, 
                required=False, 
                description="Код склада-отправителя для фильтрации."
            ),
            OpenApiParameter(
                name='sync_code', 
                type=OpenApiTypes.STR, 
                location=OpenApiParameter.QUERY, 
                required=False, 
                description="Уникальный код синхронизации конкретного объекта."
            ),
            OpenApiParameter(
                name='doc_date', 
                type=OpenApiTypes.DATETIME, 
                location=OpenApiParameter.QUERY, 
                required=False, 
                description="ISO дата-время. Возвращает документы с датой после указанной (`doc_date__gt`)."
            ),
            OpenApiParameter(
                name='page', 
                type=OpenApiTypes.INT, 
                location=OpenApiParameter.QUERY, 
                required=False, 
                description="Номер запрашиваемой страницы (по умолчанию 1)."
            ),
            OpenApiParameter(
                name='page_size', 
                type=OpenApiTypes.INT, 
                location=OpenApiParameter.QUERY, 
                required=False, 
                description="Количество элементов на странице (по умолчанию 100, max 1000)."
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
                            "server_time": "2026-10-14T18:30:00.000Z",
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
                                {
                                    "storage_to": "wh_main",
                                    "storage_from": "wh_from",
                                    "sync_code": "uuid_doc",
                                    "model_type": "ПеремещениеТоваров",
                                    "doc_date": "12.10.2026T12:40:40",
                                    "is_deleted": False,
                                    "data": {"Ref": "uuid_good", "count": 100}
                                },
                                {
                                    "storage_to": None,
                                    "storage_to": None,
                                    "sync_code": "uuid_item",
                                    "model_type": "Номенклатура",
                                    "doc_date": "11.10.2026T12:40:40",
                                    "is_deleted": True,
                                    "data": None
                                }
                            ]
                        }
                    )
                ]
            ),
            400: OpenApiResponse(
                description="Ошибка в формате переданных query-параметров",
                response=OpenApiTypes.OBJECT,
                examples=[OpenApiExample('Ошибка параметров', value={"error": "Неверный формат даты и времени"})]
            ),
            404: OpenApiResponse(
                description="Запрошенная страница пагинации не существует",
                response=OpenApiTypes.OBJECT,
                examples=[OpenApiExample('Страница не найдена', value={"error": "Page not found", "message": "Page 999 does not exist. Total pages: 5"})]
            )
        }
    )
    def get(self, request, *args, **kwargs):
        """ Эндпоинт для Мобильного приложения (Скачивание изменений со шлюза) с пагинацией """        
        # 1. Получение параметров синхронизации
        storage_to = request.query_params.getlist('storage_to')
        storage_from = request.query_params.getlist('storage_from')
        model_type = request.query_params.getlist('model_type')
        sync_code = request.query_params.getlist('sync_code')
        doc_date = request.query_params.get('doc_date') 


        # 2. Формирование QuerySet
        filter_kwargs = {}

        if model_type:
            filter_kwargs['model_type__in'] = model_type
        if storage_to:
            filter_kwargs['storage_to__in'] = storage_to
        if storage_from:
            filter_kwargs['storage_from__in'] = storage_from
        if sync_code:
            filter_kwargs['sync_code__in'] = sync_code
        if doc_date:
            filter_kwargs['doc_date__gt'] = doc_date

        queryset = SyncDocumentItem.objects.filter(**filter_kwargs).order_by('doc_date')

        # 3. Извлечение параметров пагинации из запроса
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
                "storage_to": item.storage_to,
                "storage_from": item.storage_from,
                "sync_code": item.sync_code,
                "model_type": item.model_type,
                "doc_date": item.doc_date,
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



# ========================================== #
# 3. ЭНДПОИНТЫ МОДЕЛИ ПОЛЬЗОВАТЕЛЯ
# ========================================== #

@extend_schema_view(
    get=extend_schema(
        tags=['Пользователи'],
        summary='Получение профиля текущего мобильного пользователя',
        description=(
            'Возвращает личные данные и настройки профиля для текущего авторизованного сотрудника. '
            'Авторизация определяется автоматически по токену в заголовках. Параметры в URL не требуются.'
        ),
        parameters=[], 
        responses={
            200: OpenApiResponse(
                description='Успешное получение данных профиля сотрудника',
                response=OpenApiTypes.OBJECT,
                examples=[
                    OpenApiExample(
                        'Пример успешного ответа',
                        value={
                            "success": True,
                            "data": {
                                "id": 1,
                                "sync_code": "3b235161-1234-5678-90ab-cdef12345678",
                                "username": "ivanov_ii",
                                "fio": "Иванов Иван Иванович",
                                "is_active": True
                            }
                        }
                    )
                ]
            ),
            401: OpenApiResponse(
                description='Пользователь не авторизован (отсутствует или неверный токен)',
                response=OpenApiTypes.OBJECT,
                examples=[OpenApiExample('Ошибка авторизации', value={"detail": "Учетные данные не были предоставлены."})]
            ),
            404: OpenApiResponse(
                description='Профиль сотрудника для текущего аккаунта не найден на шлюзе',
                response=OpenApiTypes.OBJECT,
                examples=[OpenApiExample('Профиль не найден', value={"detail": "Профиль сотрудника для пользователя 'ivanov_ii' не найден на шлюзе."})]
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

    def get(self, request, *args, **kwargs):
        """ Получение данных профиля мобильного сотрудника для текущего авторизованного пользователя """
        
        # request.user — это объект стандартного пользователя Django (User), который авторизовался
        current_username = request.user.username

        try:
            # Ищем запись в MobileUser, где username совпадает с текущим пользователем
            user = MobileUser.objects.get(username=current_username)
            
            # Сериализуем данные ОДНОГО найденного пользователя
            serializer = MobileUserReadSerializer(user)
            return Response({"success": True,
                             "data": serializer.data
                             }, status=status.HTTP_200_OK)
            
        except MobileUser.DoesNotExist:
            return Response(
                {
                    "detail": f"Профиль сотрудника для пользователя '{current_username}' не найден на шлюзе."
                }, 
                status=status.HTTP_404_NOT_FOUND
            )

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

