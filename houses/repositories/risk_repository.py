"""
风险告警数据访问层
仅负责构建查询条件，不涉及业务逻辑
"""

from django.db.models import QuerySet
from houses.models import RiskAlert


class RiskAlertRepository:
    """
    风险告警数据仓库类
    封装常用的查询构造方法，统一管理对 RiskAlert 表的查询入口
    """

    @staticmethod
    def base_queryset_for_houses(house_ids):
        """
        根据房源ID列表构建基础查询集，按创建时间倒序排列
        若传入空列表，返回空查询集避免无效查询
        """
        if not house_ids:
            return RiskAlert.objects.none()
        # 使用 house_id__in 过滤多个房源，并按创建时间倒序
        query_set = RiskAlert.objects.filter(house_id__in=house_ids).order_by("-create_time")
        return query_set

    @staticmethod
    def base_queryset_for_requests(request_ids):
        """
        根据托管请求ID列表构建基础查询集，按创建时间倒序排列
        """
        query_set = RiskAlert.objects.filter(request_id__in=request_ids).order_by("-create_time")
        return query_set

    @staticmethod
    def apply_filters(query_set, house_id=None, request_id=None, level=None, date_from=None, date_to=None):
        """
        在已有查询集上叠加过滤条件
        参数均为可选，仅当传入有效值时才会追加过滤条件
        返回过滤后的查询集
        """
        # 按房源ID过滤
        if house_id is not None:
            query_set = query_set.filter(house_id=house_id)

        # 按请求ID过滤
        if request_id is not None:
            query_set = query_set.filter(request_id=request_id)

        # 按告警等级过滤，统一转小写后比较
        if level:
            level_value = level.strip().lower()
            query_set = query_set.filter(level=level_value)

        # 按日期范围过滤：起始日期（大于等于）
        if date_from is not None:
            query_set = query_set.filter(create_time__date__gte=date_from)

        # 按日期范围过滤：结束日期（小于等于）
        if date_to is not None:
            query_set = query_set.filter(create_time__date__lte=date_to)

        return query_set