import base64
import json
import uuid
from datetime import datetime

from django.contrib.auth import authenticate
from django.http import JsonResponse
from django.utils.dateparse import parse_datetime
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response


class BasicAuthMixin:
    """Базовая аутентификация для 1С (исправленная версия, не ломающая рендереры)"""
    
    def dispatch(self, request, *args, **kwargs):
        auth_header = request.headers.get('Authorization')
        
        if not auth_header or not auth_header.startswith('Basic '):
            # Переводим на JsonResponse — это защищает жизненный цикл Django и DRF
            return JsonResponse({'error': 'Unauthorized'}, status=401)
        
        try:
            auth_decoded = base64.b64decode(auth_header[6:]).decode('utf-8')
            username, password = auth_decoded.split(':', 1)
        except Exception:
            return JsonResponse({'error': 'Invalid auth format'}, status=401)
        
        user = authenticate(request, username=username, password=password)
        
        if not user:
            return JsonResponse({'error': 'Invalid credentials'}, status=401)
        
        request.user = user
        return super().dispatch(request, *args, **kwargs)


class DateRangeValidationMixin:
    """Миксин для валидации диапазона дат"""
    
    def get_and_validate_date(self, request, start_date_param='start_date', end_date_param='end_date'):
        """Получить и проверить диапазон дат из GET параметров"""

        start_str = request.query_params.get(start_date_param)
        end_str = request.query_params.get(end_date_param)
         
        if not start_str:
            return None, None, self._missing_date_error(start_date_param)
        
        if not end_str:
            return None, None, self._missing_date_error(end_date_param)
        
        # Очищаем от случайных кавычек по краям, если они проскочат
        start_str = start_str.strip("'\"").strip()
        end_str = end_str.strip("'\"").strip()
        
        # Список форматов, которые мы готовы принять (сначала ISO из Swagger, затем обычный)
        formats = ['%Y-%m-%dT%H:%M:%S', '%Y-%m-%d']
        
        for fmt in formats:
            try:
                start_date = datetime.strptime(start_str, fmt)
                if timezone.is_naive(start_date):
                    start_date = timezone.make_aware(start_date)
                
                end_date = datetime.strptime(end_str, fmt)
                if timezone.is_naive(end_date):
                    end_date = timezone.make_aware(end_date)

                return start_date, end_date, None
            except ValueError:
                continue
                
        # Если ни один формат не подошел
        return None, None, self._invalid_date_error()
    
    def _missing_date_error(self, param_name):
        return Response({
            'error': 'Missing parameter',
            'message': f'{param_name} required (format: YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS)'
        }, status=status.HTTP_400_BAD_REQUEST)
    
    def _invalid_date_error(self):
        return Response({
            'error': 'Invalid date format',
            'message': 'Use format: YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS.'
        }, status=status.HTTP_400_BAD_REQUEST)
    
    def _invalid_date_range(self):
        return Response({
            'error': 'Invalid date range',
            'message': 'The end date must be greater than the start date..'
        }, status=status.HTTP_400_BAD_REQUEST)
    
    
class PaginationMixin:
    """Миксин для пагинации"""
    
    def get_pagination_params(self, request, max_page_size=200, default_page_size=100):
        """Получить параметры пагинации"""
        page = int(request.GET.get('page', 1))
        page_size = int(request.GET.get('page_size', default_page_size))
        
        if page_size > max_page_size:
            page_size = max_page_size
        
        return page, page_size
    
    def paginate_queryset(self, queryset, page, page_size):
        """Применить пагинацию к queryset"""
        from django.core.paginator import Paginator
        paginator = Paginator(queryset, page_size)
        
        if page > paginator.num_pages and queryset.count() > 0:
            return None, Response({
                'error': 'Page not found',
                'message': f'Page {page} does not exist. Total pages: {paginator.num_pages}'
            }, status=404)
        
        current_page = paginator.get_page(page)
        
        pagination_info = {
            'current_page': page,
            'page_size': page_size,
            'total_pages': paginator.num_pages,
            'total_records': paginator.count,
            'has_next': current_page.has_next(),
            'has_previous': current_page.has_previous(),
            'next_page': page + 1 if current_page.has_next() else None,
            'previous_page': page - 1 if current_page.has_previous() else None
        }
        
        return current_page, pagination_info
    

class JsonSyncCodeValidationMixin:
    """Миксин для валидации входящих списков sync_code (UUID)"""
    
    def get_and_validate_sync_codes(self, request, max_limit=50):
        try:
            body_data = json.loads(request.body)
            # 1С присылает список sync_codes вместо ids
            record_codes = body_data.get('sync_codes') 
            
            if record_codes is None or not isinstance(record_codes, list):
                return None, Response({
                    'error': 'Bad Request',
                    'message': 'Field "sync_codes" is required and must be a list of UUID strings.'
                }, status=400)
            
            if not record_codes:
                return None, Response({
                    'error': 'Bad Request',
                    'message': 'The "sync_codes" list cannot be empty.'
                }, status=400)
                
            if len(record_codes) > max_limit:
                return None, Response({
                    'error': 'Too Many Codes',
                    'message': f'Maximum allowed per request is {max_limit}.'
                }, status=400)
                
            # Проверяем, что все переданные строки являются валидными UUID
            valid_uuids = []
            for code in record_codes:
                try:
                    valid_uuids.append(uuid.UUID(str(code)))
                except ValueError:
                    return None, Response({
                        'error': 'Invalid UUID format',
                        'message': f'Value "{code}" is not a valid UUID.'
                    }, status=400)
                    
            return valid_uuids, None

        except json.JSONDecodeError:
            return None, Response({'error': 'Bad Request', 'message': 'Invalid JSON format.'}, status=400)


class SingleSyncCodeValidationMixin:
    """Миксин для валидации одиночного sync_code (UUID) из GET-параметров"""
    
    def get_and_validate_sync_code(self, request, param_name='sync_code'):
        target_code = request.query_params.get(param_name)
        
        if not target_code:
            return None, Response({
                'error': 'Missing parameter',
                'message': f'Параметр {param_name} является обязательным.'
            }, status=status.HTTP_400_BAD_REQUEST)
            
        try:
            return uuid.UUID(str(target_code)), None
        except ValueError:
            return None, Response({
                'error': 'Invalid UUID format',
                'message': f'Параметр {param_name} должен быть валидным UUID.'
            }, status=status.HTTP_400_BAD_REQUEST)


class JsonListValidationMixin:
    """Миксин для валидации входящих JSON-массивов (списков объектов)"""
    
    def get_and_validate_json_list(self, request):
        """
        Проверяет, является ли тело запроса непустым списком (массивом).
        Возвращает кортеж: (список_данных, None) или (None, Response с ошибкой)
        """
        # В DRF request.data уже содержит распарсенный JSON благодаря парсерам
        data = request.data
        
        if not isinstance(data, list):
            return None, Response({
                'error': 'Bad Request',
                'message': 'Ожидался массив JSON (список объектов).'
            }, status=status.HTTP_400_BAD_REQUEST)

        if not data:
            return None, Response({
                'error': 'Bad Request',
                'message': 'Массив переданных объектов не может быть пустым.'
            }, status=status.HTTP_400_BAD_REQUEST)
            
        return data, None


class SyncValidationMixin:
    """ Миксин для валидации входящих данных в UnifiedSyncView """

    def validate_post_payload(self, request):
        """ Валидация тела POST-запроса """
        payload = request.data

        if not isinstance(payload, dict):
            return None, Response(
                {"error": "Ожидается JSON-объект с метаданными"},
                status=status.HTTP_400_BAD_REQUEST
            )

        model_type = payload.get('model_type')
        items = payload.get('items')

        if not model_type or not isinstance(items, list):
            return None, Response(
                {"error": "Параметры 'model_type' и 'items' (массив) обязательны."},
                status=status.HTTP_400_BAD_REQUEST
            )

        return payload, None

    def validate_get_params(self, request):
        """ Валидация query-параметров GET-запроса """
        model_type = request.query_params.get('type')
        since_param = request.query_params.get('since')

        if not model_type:
            return None, None, Response(
                {"error": "Параметр 'type' обязателен."},
                status=status.HTTP_400_BAD_REQUEST
            )

        parsed_datetime = None
        if since_param:
            parsed_datetime = parse_datetime(since_param)
            if not parsed_datetime:
                return None, None, Response(
                    {"error": "Неверный формат даты 'since'."},
                    status=status.HTTP_400_BAD_REQUEST
                )

        return model_type, parsed_datetime, None















