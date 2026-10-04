import json
from django.db import transaction
from django.utils import timezone
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiExample, OpenApiResponse
from drf_spectacular.types import OpenApiTypes
from rest_framework.pagination import PageNumberPagination
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import generics, status

from .models import Good, Storage, ToolBalance, CreateOrWriteOff
from .serializers import GoodSerializer, StorageSerializer, OneClickDocumentSerializer
from .mixins import (
    BasicAuthMixin, 
    PaginationMixin, 
    SingleSyncCodeValidationMixin,
    DateRangeValidationMixin,
    JsonListValidationMixin
)


# Настройка пагинации
class CustomPagination(PageNumberPagination):
    """Кастомная пагинация с ограничением размера страницы"""
    page_size = 100
    max_page_size = 1000
    page_size_query_param = 'page_size'


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


# ========================================== #
# 2. СКЛАДЫ
# ========================================== #

@extend_schema(
    tags=['Storages'],
    summary="Получить список всех складов",
    description="Возвращает полный перечень мест хранения (складов), зарегистрированных на сервере. Требует авторизации Basic Auth. Пагинация отключена.",
    responses={
        200: OpenApiResponse(
            description="Список складов успешно получен",
            response=OpenApiTypes.OBJECT,
            examples=[
                OpenApiExample(
                    'success_response',
                    value={
                        'success': True,
                        'count': 2,
                        'results': [
                            {
                                'id': 1,
                                'sync_code': '123e4567-e89b-12d3-a456-426614174000',
                                'user': 3,
                                'title': 'Основной склад Москва',
                                'can_create': True
                            },
                            {
                                'id': 2,
                                'sync_code': '9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d',
                                'user': 5,
                                'title': 'Региональный склад СПБ',
                                'can_create': False
                            }
                        ]
                    }
                )
            ]
        ),
        401: OpenApiResponse(description="Требуется авторизация (Basic Auth)")
    }
)
class StorageListView(BasicAuthMixin, APIView):
    """Эндпоинт для получения полного списка складов без пагинации"""

    def get(self, request, *args, **kwargs):
        # Выбираем все склады из базы данных (оптимизируем запрос через select_related, если это необходимо)
        queryset = Storage.objects.all().select_related('user').order_by('id')
        
        # Передаем данные в ваш сериализатор с флагом many=True
        serializer = StorageSerializer(queryset, many=True)
        
        # Возвращаем стандартизированный ответ в едином стиле проекта
        return Response({
            'success': True,
            'count': queryset.count(),
            'results': serializer.data
        }, status=status.HTTP_200_OK)


# ========================================== #
# 2. НОМЕНКЛАТУРА
# ========================================== #

@extend_schema(
    tags=['Goods'],
    summary="Получить номенклатуру, созданную или измененнную в указанном диапазоне дат.",
    description="Возвращает все поля моделей Good, измененных в диапазоне указанных дат. Поддерживает пагинацию.",
    parameters=[
        OpenApiParameter(
            name='start_date',
            description='Дата в ISO формате (YYYY-MM-DDTHH:MM:SS)',
            required=True,
            type=str,
            location=OpenApiParameter.QUERY
        ),
                OpenApiParameter(
            name='end_date',
            description='Дата в ISO формате (YYYY-MM-DDTHH:MM:SS)',
            required=True,
            type=str,
            location=OpenApiParameter.QUERY
        ),
        OpenApiParameter(
            name='page',
            description='Номер страницы',
            required=False,
            type=int,
            location=OpenApiParameter.QUERY
        ),
        OpenApiParameter(
            name='page_size',
            description='Размер страницы (максимум 200, по умолчанию 100)',
            required=False,
            type=int,
            location=OpenApiParameter.QUERY
        )
    ],
    responses={
        200: OpenApiResponse(description="Успешный ответ"),
        400: OpenApiResponse(description="Ошибка валидации"),
        401: OpenApiResponse(description="Требуется авторизация"),
        404: OpenApiResponse(description="Страница не найдена")
    }
)
class ChangedGoodsDateRangeView(BasicAuthMixin, generics.ListAPIView):
    """Получить измененной номенклатуры с поддержкой пагинации"""

    serializer_class = GoodSerializer
    pagination_class = CustomPagination
    
    def get_queryset(self):
        validator = DateRangeValidationMixin()      
        start_date, end_date, error_response = validator.get_and_validate_date(self.request)

        if error_response:
            return Good.objects.none()
        
        return (Good.objects
                .filter(updated_at__gte=start_date, updated_at__lt=end_date)
                .order_by('updated_at'))
    
    def list(self, request, *args, **kwargs):
        validator = DateRangeValidationMixin()
        
        start_date, end_date, error_response = validator.get_and_validate_date(request)
        if error_response:
            return Response(error_response.data, status=error_response.status_code)
        
        return super().list(request, *args, **kwargs)


@extend_schema(
    tags=['Goods'],
    summary="Массовое создание и обновление номенклатуры (Upsert)",
    description=(
        "Принимает массив JSON-объектов товаров. Объекты сопоставляются по сквозному `sync_code` (UUID).\n\n"
        "**Логика обработки:**\n"
        "1. Если `sync_code` передан как `null` или отсутствует — сервер создаёт новый товар и генерирует для него UUID.\n"
        "2. Если `sync_code` совпадает с существующим в базе данных — сервер перезаписывает (обновляет) данные товара.\n\n"
        "Операция атомарна: при ошибке валидации хотя бы одного элемента изменения откатываются для всего пакета."
    ),
    request={
        'application/json': {
            'type': 'array',
            'items': {
                'type': 'object',
                'properties': {
                    'title': {'type': 'string', 'example': 'Молоток отбойный'},
                    'sync_code': {'type': 'string', 'format': 'uuid', 'example': None, 'nullable': True},
                    'unit': {'type': 'string', 'example': 'pcs'},
                    'is_serial': {'type': 'boolean', 'example': False},
                    'serial_number': {'type': 'string', 'example': None, 'nullable': True},
                    'code_v7': {'type': 'string', 'example': 'В7-1054'}
                },
                'required': ['title', 'unit']
            }
        }
    },
    responses={
        201: OpenApiResponse(
            description="Пакет успешно обработан (создан или обновлен)",
            response=OpenApiTypes.OBJECT,
            examples=[
                OpenApiExample(
                    'success_response',
                    value={
                        'success': True,
                        'received_count': 3,
                        'results': [
                            {'index': 0, 'sync_code': '4a8a6192-3c81-4b1a-bd7e-d890cf2c12ba'},
                            {'index': 1, 'sync_code': '123e4567-e89b-12d3-a456-426614174000'},
                            {'index': 2, 'sync_code': '8f12a819-219d-4eab-92bb-1a0c8b3dcb6d'}
                        ]
                    }
                )
            ]
        ),
        400: OpenApiResponse(
            description="Ошибка валидации структуры JSON или бизнес-полей данных",
            response=OpenApiTypes.OBJECT,
            examples=[
                OpenApiExample(
                    'validation_error',
                    value={
                        'error': 'Bad Request',
                        'message': 'Ошибка валидации переданных данных.',
                        'details': [
                            {
                                'index': 1,
                                'errors': {'title': ['Обязательное поле.']}
                            },
                            {
                                'index': 2,
                                'errors': {'unit': ['Недопустимая единица измерения. Доступные варианты: ...']}
                            }
                        ]
                    }
                )
            ]
        ),
        401: OpenApiResponse(description="Требуется авторизация (Basic Auth)")
    }
)
class GoodBulkCreateView(BasicAuthMixin, JsonListValidationMixin, APIView):
    """Эндпоинт для массового создания и обновления товаров из массива JSON"""

    def post(self, request, *args, **kwargs):
        # 1. Валидация структуры входящего JSON-массива через миксин
        payload_data, error_response = self.get_and_validate_json_list(request)
        if error_response:
            return error_response

        # 2. Инициализируем сериализатор с флагом many=True
        serializer = GoodSerializer(data=payload_data, many=True)
        
        # 3. Валидируем бизнес-логику полей данных
        if not serializer.is_valid():
            # Преобразуем стандартный список ошибок DRF в массив с явным указанием индексов для 1С
            formatted_errors = []
            for index, errors_dict in enumerate(serializer.errors):
                if errors_dict:  # Если словарь ошибок для данного элемента не пустой
                    formatted_errors.append({
                        'index': index,
                        'errors': errors_dict
                    })

            return Response({
                'error': 'Bad Request',
                'message': 'Ошибка валидации переданных данных.',
                'details': formatted_errors
            }, status=status.HTTP_400_BAD_REQUEST)

        # 4. Атомарно сохраняем или обновляем всю пачку в базе данных
        try:
            with transaction.atomic():
                # Наш GoodListSerializer под капотом выполняет Upsert 
                # и возвращает массив словарей вида: [{'index': 0, 'sync_code': '...'}, ...]
                processed_data = serializer.save()
            
            # 5. Возвращаем 1С успешный облегченный ответ в едином стиле проекта
            return Response({
                'success': True,
                'received_count': len(payload_data),
                'results': processed_data
            }, status=status.HTTP_201_CREATED)

        except Exception as e:
            return Response({
                'error': 'Internal Server Error',
                'message': f'Не удалось выполнить массовую запись данных в БД. Ошибка: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@extend_schema(
    tags=['Goods'],
    summary="Загрузка изображения товара (Multipart)",
    description="Принимает бинарный файл изображения товара и привязывает его к объекту по `sync_code`. Формат запроса: multipart/form-data.",
    responses={
        200: OpenApiResponse(description="Изображение успешно загружено"),
        400: OpenApiResponse(description="Файл не передан или имеет неверный формат"),
        404: OpenApiResponse(description="Товар с указанным sync_code не найден")
    }
)
class GoodImageUploadView(BasicAuthMixin, APIView):
    """Эндпоинт для загрузки фотографии к товару по его sync_code"""
    
    # Явно указываем парсеры для работы с файлами
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request, sync_code, *args, **kwargs):
        # 1. Ищем товар в базе данных по его сквозному sync_code (UUID)
        good = get_object_or_404(Good, sync_code=sync_code)

        # 2. Достаем файл из запроса (1С должна передать его под ключом 'image')
        image_file = request.FILES.get('image')
        
        if not image_file:
            return Response({
                'error': 'Bad Request',
                'message': 'Файл изображения не найден в запросе. Передайте файл под ключом "image".'
            }, status=status.HTTP_400_BAD_REQUEST)

        # 3. Передаем файл в сериализатор для валидации расширения/размера и сохранения
        # partial=True позволяет обновить ТОЛЬКО поле image, не требуя title и unit
        serializer = GoodSerializer(good, data={'image': image_file}, partial=True)
        
        if serializer.is_valid():
            # Метод save() под капотом вызовет нашу функцию 'good_image_upload_path',
            # сгенерирует уникальное имя файла с UUID, запишет его физически на диск 
            # и обновит текстовый путь в базе данных.
            serializer.save()
            
            return Response({
                'success': True,
                'message': 'Изображение успешно сохранено на диск и привязано к товару.',
                'image_url': serializer.data['image']  # DRF вернет полный абсолютный URL до картинки
            }, status=status.HTTP_200_OK)
            
        return Response({
            'error': 'Bad Request',
            'message': 'Ошибка валидации файла.',
            'details': serializer.errors
        }, status=status.HTTP_400_BAD_REQUEST)


# ========================================== #
# 3. ДВИЖЕНИЧ
# ========================================== #

@extend_schema(
    tags=['Operations'],
    summary="Проведение одиночного документа движения из 1С",
    description="Принимает JSON-структуру одиночной складской операции (один документ — один товар). "
                "Сопоставляет объекты по `sync_code`, фиксирует вид движения и обновляет остатки на складе. "
                "Сам документ в базе данных не сохраняется.",
    request={
        'application/json': {
            'type': 'object',
            'properties': {
                'document_guid': {'type': 'string', 'format': 'uuid', 'example': 'a4fc7281-129d-4eab-92bb-1a0c8b3dcb6d'},
                'storage_sync_code': {'type': 'string', 'format': 'uuid', 'example': '123e4567-e89b-12d3-a456-426614174000'},
                'good_sync_code': {'type': 'string', 'format': 'uuid', 'example': '9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d'},
                'quantity': {'type': 'number', 'example': 10.0, 'description': 'Расход передается со знаком минус.'},
                'storage_type': {'type': 'string', 'example': 'real', 'description': 'Варианты: real, transfer, reception, write_off'}
            },
            'required': ['document_guid', 'storage_sync_code', 'good_sync_code', 'quantity', 'storage_type']
        }
    },
    responses={
        201: OpenApiResponse(
            description="Движение по документу успешно записано",
            response=OpenApiTypes.OBJECT,
            examples=[
                OpenApiExample(
                    'success_response',
                    value={
                        'success': True,
                        'message': 'Документ успешно проведен.',
                        'document_guid': 'a4fc7281-129d-4eab-92bb-1a0c8b3dcb6d',
                        'operation_id': 42
                    }
                )
            ]
        ),
        400: OpenApiResponse(description="Ошибка валидации бизнес-полей или UUID кодов"),
        401: OpenApiResponse(description="Требуется авторизация (Basic Auth)")
    }
)
class ProcessSingleDocumentView(BasicAuthMixin, APIView):
    """Прием и обработка одиночного документа движения (1 документ = 1 товар)"""

    def post(self, request, *args, **kwargs):
        # 1. Передаем входящий JSON в сериализатор для сквозной валидации
        serializer = OneClickDocumentSerializer(data=request.data)
        
        if not serializer.is_valid():
            return Response({
                'error': 'Bad Request',
                'message': 'Ошибка валидации данных документа.',
                'details': serializer.errors
            }, status=status.HTTP_400_BAD_REQUEST)

        # 2. Извлекаем уже валидированные и сопоставленные объекты моделей
        validated_data = serializer.validated_data
        storage_obj = validated_data['storage_sync_code']  # Уже объект класса Storage
        good_obj = validated_data['good_sync_code']        # Уже объект класса Good
        
        # 3. Атомарно записываем движение
        try:
            with transaction.atomic():
                # Создаем запись движения (метод save() в CreateOrWriteOff автоматически 
                # обновит ToolBalance и проставит нужный вид движения storage_type)
                operation = CreateOrWriteOff.objects.create(
                    storage=storage_obj,
                    good=good_obj,
                    quantity=validated_data['quantity']
                )

            # 4. Успешный ответ для 1С в едином стиле проекта
            return Response({
                'success': True,
                'message': 'Документ успешно проведен. Движение зафиксировано.',
                'document_guid': str(validated_data['document_guid']),
                'operation_id': operation.id
            }, status=status.HTTP_201_CREATED)

        except Exception as e:
            return Response({
                'error': 'Internal Server Error',
                'message': f'Не удалось записать операцию в БД. Ошибка: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

