"""
风险统计、趋势分析及页面上下文构建模块
为风险监控页面提供数据聚合、分页、图表数据等业务逻辑支撑
"""

from datetime import date, timedelta
from typing import Any

from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.utils import timezone

from houses.constants import (
    RISK_ALERTS_PAGE_SIZE,
    RISK_LEVEL_CRITICAL,
    RISK_LEVEL_HIGH,
    RISK_LEVEL_LOW,
    RISK_LEVEL_MEDIUM,
)
from houses.models import House, RiskAlert, StayRequest, User
from houses.repositories.risk_repository import RiskAlertRepository


def _parse_int_param(value):
    """
    将请求参数中的字符串转为整数，转换失败或为空时返回 None
    """
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_date_param(value):
    """
    将请求参数中的日期字符串（YYYY-MM-DD格式）转为 date 对象，转换失败或为空时返回 None
    """
    if not value:
        return None
    try:
        # 只取前10位，兼容可能带时间部分的参数
        date_str = value[:10]
        return date.fromisoformat(date_str)
    except ValueError:
        return None


def _build_base_queryset_by_user_role(user):
    """
    根据用户角色构建风险告警的基础查询集
    - 房主：查询其名下所有房源的风险告警
    - 看护人：查询其参与的所有托管请求关联的风险告警
    """
    if user.role == "owner":
        # 获取房主所有房源ID列表
        house_id_list = list(
            House.objects.filter(owner_id=user.user_id).values_list("house_id", flat=True)
        )
        base_qs = RiskAlertRepository.base_queryset_for_houses(house_id_list)
    else:
        # 获取看护人所有托管请求ID列表
        request_id_list = list(
            StayRequest.objects.filter(sitter_id=user.user_id).values_list("request_id", flat=True)
        )
        if request_id_list:
            base_qs = RiskAlertRepository.base_queryset_for_requests(request_id_list)
        else:
            # 无请求记录时返回空查询集，避免后续查询报错
            base_qs = RiskAlert.objects.none()
    return base_qs


def _aggregate_alert_level_counts(queryset):
    """
    对查询集按告警等级进行计数统计，返回各等级数量字典
    """
    agg_result = queryset.aggregate(
        high_count=Count("alert_id", filter=Q(level=RISK_LEVEL_HIGH)),
        medium_count=Count("alert_id", filter=Q(level=RISK_LEVEL_MEDIUM)),
        low_count=Count("alert_id", filter=Q(level=RISK_LEVEL_LOW)),
        critical_count=Count("alert_id", filter=Q(level=RISK_LEVEL_CRITICAL)),
    )
    return agg_result


def _get_high_risk_orders(queryset):
    """
    获取高危告警（HIGH 和 CRITICAL 级别）关联的订单列表，
    按告警数量倒序排列，最多返回20条
    """
    # 筛选高危等级且有关联请求ID的告警
    high_risk_qs = queryset.filter(
        level__in=(RISK_LEVEL_HIGH, RISK_LEVEL_CRITICAL)
    ).exclude(request_id__isnull=True)

    # 按请求ID和房源ID分组，统计每个分组的告警数量
    grouped_rows = (
        high_risk_qs.values("request_id", "house_id")
        .annotate(alert_count=Count("alert_id"))
        .order_by("-alert_count", "-request_id")[:20]
    )

    high_risk_order_list = []
    # 提取所有涉及的请求ID，批量查询对应的 StayRequest 对象
    request_id_set = [row["request_id"] for row in grouped_rows]
    request_map = {
        req.request_id: req
        for req in StayRequest.objects.filter(request_id__in=request_id_set)
    }

    for row in grouped_rows:
        request_obj = request_map.get(row["request_id"])
        status_display = request_obj.status if request_obj else "-"
        high_risk_order_list.append({
            "request_id": row["request_id"],
            "house_id": row["house_id"],
            "alert_count": row["alert_count"],
            "status": status_display,
        })

    return high_risk_order_list


def _compute_abnormal_users(queryset, max_sample_size=500):
    """
    基于近期告警样本计算异常用户列表（按风险评分排序）
    为防止数据量过大，只取前500条告警进行分析
    """
    # 获取最近一批告警ID用于采样
    recent_alert_ids = list(queryset.values_list("alert_id", flat=True)[:max_sample_size])
    if recent_alert_ids:
        sample_queryset = RiskAlert.objects.filter(alert_id__in=recent_alert_ids)
    else:
        sample_queryset = RiskAlert.objects.none()

    # 收集样本中涉及的所有请求ID和房源ID
    request_id_in_sample = set()
    house_id_in_sample = set()
    for alert in sample_queryset:
        if alert.request_id is not None:
            request_id_in_sample.add(alert.request_id)
        house_id_in_sample.add(alert.house_id)

    # 批量获取关联的请求和房源对象
    request_map = {
        req.request_id: req
        for req in StayRequest.objects.filter(request_id__in=request_id_in_sample)
    }
    house_map = {
        h.house_id: h
        for h in House.objects.filter(house_id__in=house_id_in_sample)
    }

    # 统计每个用户（房主或看护人）关联的告警等级分布
    user_risk_stats = {}  # key: user_id, value: 各等级计数及总计数

    for alert in sample_queryset:
        # 找出与该告警相关的用户ID（看护人、房主）
        related_user_ids = []
        if alert.request_id:
            req_obj = request_map.get(alert.request_id)
            if req_obj:
                related_user_ids.append(req_obj.sitter_id)
        house_obj = house_map.get(alert.house_id)
        if house_obj:
            related_user_ids.append(house_obj.owner_id)

        for user_id in related_user_ids:
            if user_id is None:
                continue
            if user_id not in user_risk_stats:
                user_risk_stats[user_id] = {
                    "high": 0,
                    "medium": 0,
                    "low": 0,
                    "critical": 0,
                    "total": 0,
                }
            level = alert.level
            if level == RISK_LEVEL_CRITICAL:
                user_risk_stats[user_id]["critical"] += 1
            elif level == RISK_LEVEL_HIGH:
                user_risk_stats[user_id]["high"] += 1
            elif level == RISK_LEVEL_MEDIUM:
                user_risk_stats[user_id]["medium"] += 1
            elif level == RISK_LEVEL_LOW:
                user_risk_stats[user_id]["low"] += 1
            user_risk_stats[user_id]["total"] += 1

    # 批量获取用户名信息
    all_affected_user_ids = list(user_risk_stats.keys())
    user_map = {
        u.user_id: u
        for u in User.objects.filter(user_id__in=all_affected_user_ids)
    }

    abnormal_user_list = []
    for uid, stat_data in user_risk_stats.items():
        # 计算风险评分：不同等级赋予不同权重
        risk_score = (
            stat_data["critical"] * 150
            + stat_data["high"] * 100
            + stat_data["medium"] * 60
            + stat_data["low"] * 30
        )
        # 根据风险评分确定颜色标识
        if risk_score >= 250:
            risk_color = "red"
        elif risk_score >= 100:
            risk_color = "yellow"
        else:
            risk_color = "green"

        username = user_map[uid].username if uid in user_map else f"用户{uid}"
        abnormal_user_list.append({
            "user_id": uid,
            "username": username,
            "total": stat_data["total"],
            "high": stat_data["high"],
            "medium": stat_data["medium"],
            "low": stat_data["low"],
            "critical": stat_data["critical"],
            "risk_score": risk_score,
            "risk_color": risk_color,
        })

    # 按风险评分降序排列，取前20名
    abnormal_user_list.sort(key=lambda x: x["risk_score"], reverse=True)
    return abnormal_user_list[:20]


def _build_trend_data(queryset, days=14):
    """
    构建最近N天的告警趋势数据，用于前端图表展示
    返回标签列表和各等级每日数量列表
    """
    end_date = timezone.localdate()
    start_date = end_date - timedelta(days=days - 1)

    trend_labels = []
    trend_critical_counts = []
    trend_high_counts = []
    trend_medium_counts = []
    trend_low_counts = []

    current_date = start_date
    while current_date <= end_date:
        # 格式化日期标签为 "MM-DD"
        trend_labels.append(current_date.strftime("%m-%d"))

        # 查询当天各等级告警数量
        day_queryset = queryset.filter(create_time__date=current_date)
        trend_critical_counts.append(
            day_queryset.filter(level=RISK_LEVEL_CRITICAL).count()
        )
        trend_high_counts.append(day_queryset.filter(level=RISK_LEVEL_HIGH).count())
        trend_medium_counts.append(day_queryset.filter(level=RISK_LEVEL_MEDIUM).count())
        trend_low_counts.append(day_queryset.filter(level=RISK_LEVEL_LOW).count())

        current_date += timedelta(days=1)

    return (
        trend_labels,
        trend_critical_counts,
        trend_high_counts,
        trend_medium_counts,
        trend_low_counts,
    )


def build_risk_alerts_page_context(user, request_get, page_param="page"):
    """
    构建风险告警页面的完整上下文数据，包含：
    - 分页后的告警列表
    - 各等级告警总数统计
    - 高危订单列表
    - 异常用户列表
    - 过滤条件回显
    - 近14天趋势数据

    参数:
        user: 当前登录用户对象
        request_get: request.GET 或类似字典对象，用于获取过滤参数
        page_param: 分页参数的键名，默认为 "page"

    返回:
        包含页面所需全部数据的字典
    """
    # 1. 根据用户角色获取基础查询集
    base_queryset = _build_base_queryset_by_user_role(user)

    # 2. 解析请求中的过滤参数
    filter_house_id = _parse_int_param(request_get.get("house_id"))
    filter_request_id = _parse_int_param(request_get.get("request_id"))
    filter_level = (request_get.get("level") or "").strip().lower() or None
    filter_date_from = _parse_date_param(request_get.get("date_from"))
    filter_date_to = _parse_date_param(request_get.get("date_to"))

    # 3. 应用过滤条件
    filtered_queryset = RiskAlertRepository.apply_filters(
        base_queryset,
        house_id=filter_house_id,
        request_id=filter_request_id,
        level=filter_level,
        date_from=filter_date_from,
        date_to=filter_date_to,
    )

    # 4. 统计各等级告警总数
    level_counts = _aggregate_alert_level_counts(filtered_queryset)

    # 5. 获取高危订单列表
    high_risk_orders = _get_high_risk_orders(filtered_queryset)

    # 6. 计算异常用户列表
    abnormal_users = _compute_abnormal_users(filtered_queryset)

    # 7. 分页处理
    paginator = Paginator(filtered_queryset, RISK_ALERTS_PAGE_SIZE)
    page_number = _parse_int_param(request_get.get(page_param)) or 1
    page_obj = paginator.get_page(page_number)

    # 8. 构建近14天趋势数据
    (
        trend_labels,
        trend_critical,
        trend_high,
        trend_medium,
        trend_low,
    ) = _build_trend_data(filtered_queryset, days=14)

    # 9. 组装返回数据
    context = {
        "alerts_page": page_obj,
        "risk_high": level_counts.get("high_count") or 0,
        "risk_medium": level_counts.get("medium_count") or 0,
        "risk_low": level_counts.get("low_count") or 0,
        "risk_critical": level_counts.get("critical_count") or 0,
        "high_risk_orders": high_risk_orders,
        "abnormal_users": abnormal_users,
        "filter_house_id": filter_house_id,
        "filter_request_id": filter_request_id,
        "filter_level": filter_level or "",
        "filter_date_from": request_get.get("date_from") or "",
        "filter_date_to": request_get.get("date_to") or "",
        "trend_labels": trend_labels,
        "trend_critical": trend_critical,
        "trend_high": trend_high,
        "trend_medium": trend_medium,
        "trend_low": trend_low,
        "paginator": paginator,
    }
    return context


def ai_risk_score_preview(alert_sample):
    """
    AI风险评分预览（占位实现，后续可替换为模型推理）
    传入告警样本列表，每项为包含 level 和 alert_type 的字典

    当前采用基于等级的加权规则计算模拟分数
    """
    if not alert_sample:
        return {
            "score": 0.0,
            "version": "rule-v0",
            "note": "no data"
        }

    # 不同等级的权重配置
    level_weight_map = {
        "critical": 1.0,
        "high": 0.7,
        "medium": 0.4,
        "low": 0.15,
    }

    total_weight = 0.0
    for alert_item in alert_sample:
        level = alert_item.get("level", "low")
        weight = level_weight_map.get(level, 0.1)
        total_weight += weight

    # 将累计权重映射到0-100区间，乘以系数12使分布更合理
    raw_score = total_weight * 12.0
    final_score = round(min(100.0, raw_score), 2)

    return {
        "score": final_score,
        "version": "rule-v0",
        "note": "Replace with model inference endpoint",
    }