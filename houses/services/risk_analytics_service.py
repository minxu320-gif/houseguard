"""Risk statistics, trends, and page context (business logic for risk UI)."""

from __future__ import annotations

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


def _parse_int(value: str | None) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def build_risk_alerts_page_context(
    *,
    user: User,
    request_get,
    page_param: str = "page",
) -> dict[str, Any]:
    """Filters + pagination + aggregates without loading full alert history into memory."""
    if user.role == "owner":
        house_ids = list(House.objects.filter(owner_id=user.user_id).values_list("house_id", flat=True))
        qs = RiskAlertRepository.base_queryset_for_houses(house_ids)
    else:
        req_ids = list(StayRequest.objects.filter(sitter_id=user.user_id).values_list("request_id", flat=True))
        qs = RiskAlertRepository.base_queryset_for_requests(req_ids) if req_ids else RiskAlert.objects.none()

    house_id = _parse_int(request_get.get("house_id"))
    request_id = _parse_int(request_get.get("request_id"))
    level = (request_get.get("level") or "").strip().lower() or None
    date_from = _parse_date(request_get.get("date_from"))
    date_to = _parse_date(request_get.get("date_to"))

    qs = RiskAlertRepository.apply_filters(
        qs,
        house_id=house_id,
        request_id=request_id,
        level=level,
        date_from=date_from,
        date_to=date_to,
    )

    agg = qs.aggregate(
        high=Count("alert_id", filter=Q(level=RISK_LEVEL_HIGH)),
        medium=Count("alert_id", filter=Q(level=RISK_LEVEL_MEDIUM)),
        low=Count("alert_id", filter=Q(level=RISK_LEVEL_LOW)),
        critical=Count("alert_id", filter=Q(level=RISK_LEVEL_CRITICAL)),
    )

    high_like = qs.filter(level__in=(RISK_LEVEL_HIGH, RISK_LEVEL_CRITICAL)).exclude(request_id__isnull=True)
    high_rows = (
        high_like.values("request_id", "house_id")
        .annotate(alert_count=Count("alert_id"))
        .order_by("-alert_count", "-request_id")[:20]
    )
    high_risk_orders = []
    req_ids_hi = [r["request_id"] for r in high_rows]
    req_map_hi = {r.request_id: r for r in StayRequest.objects.filter(request_id__in=req_ids_hi)}
    for row in high_rows:
        req = req_map_hi.get(row["request_id"])
        high_risk_orders.append(
            {
                "request_id": row["request_id"],
                "house_id": row["house_id"],
                "alert_count": row["alert_count"],
                "status": req.status if req else "-",
            }
        )

    # Abnormal users: sample recent alerts only (cap) to bound work
    recent_ids = list(qs.values_list("alert_id", flat=True)[:500])
    sample = RiskAlert.objects.filter(alert_id__in=recent_ids) if recent_ids else RiskAlert.objects.none()
    user_risk_count: dict[int, dict[str, int]] = {}
    rid_set = {x for x in sample.values_list("request_id", flat=True) if x is not None}
    hid_set = set(sample.values_list("house_id", flat=True))
    req_map = {r.request_id: r for r in StayRequest.objects.filter(request_id__in=rid_set)}
    house_map = {h.house_id: h for h in House.objects.filter(house_id__in=hid_set)}

    for a in sample:
        req = req_map.get(a.request_id) if a.request_id else None
        house = house_map.get(a.house_id)
        related_uids = []
        if req:
            related_uids.append(req.sitter_id)
        if house:
            related_uids.append(house.owner_id)
        for uid in related_uids:
            if uid is None:
                continue
            if uid not in user_risk_count:
                user_risk_count[uid] = {"high": 0, "medium": 0, "low": 0, "critical": 0, "total": 0}
            lv = a.level
            if lv == RISK_LEVEL_CRITICAL:
                user_risk_count[uid]["critical"] += 1
            elif lv == RISK_LEVEL_HIGH:
                user_risk_count[uid]["high"] += 1
            elif lv == RISK_LEVEL_MEDIUM:
                user_risk_count[uid]["medium"] += 1
            elif lv == RISK_LEVEL_LOW:
                user_risk_count[uid]["low"] += 1
            user_risk_count[uid]["total"] += 1

    abnormal_users = []
    user_map = {u.user_id: u for u in User.objects.filter(user_id__in=user_risk_count.keys())}
    for uid, stat in user_risk_count.items():
        risk_score = stat["critical"] * 150 + stat["high"] * 100 + stat["medium"] * 60 + stat["low"] * 30
        if risk_score >= 250:
            risk_color = "red"
        elif risk_score >= 100:
            risk_color = "yellow"
        else:
            risk_color = "green"
        abnormal_users.append(
            {
                "user_id": uid,
                "username": user_map[uid].username if uid in user_map else f"用户{uid}",
                "total": stat["total"],
                "high": stat["high"],
                "medium": stat["medium"],
                "low": stat["low"],
                "critical": stat.get("critical", 0),
                "risk_score": risk_score,
                "risk_color": risk_color,
            }
        )
    abnormal_users.sort(key=lambda x: x["risk_score"], reverse=True)
    abnormal_users = abnormal_users[:20]

    paginator = Paginator(qs, RISK_ALERTS_PAGE_SIZE)
    page = _parse_int(request_get.get(page_param)) or 1
    page_obj = paginator.get_page(page)

    # Trend: last 14 days counts by level (for chart)
    end_d = timezone.localdate()
    start_d = end_d - timedelta(days=13)
    trend_labels = []
    trend_critical = []
    trend_high = []
    trend_medium = []
    trend_low = []
    d = start_d
    while d <= end_d:
        trend_labels.append(d.strftime("%m-%d"))
        day_q = qs.filter(create_time__date=d)
        trend_critical.append(day_q.filter(level=RISK_LEVEL_CRITICAL).count())
        trend_high.append(day_q.filter(level=RISK_LEVEL_HIGH).count())
        trend_medium.append(day_q.filter(level=RISK_LEVEL_MEDIUM).count())
        trend_low.append(day_q.filter(level=RISK_LEVEL_LOW).count())
        d += timedelta(days=1)

    return {
        "alerts_page": page_obj,
        "risk_high": agg["high"] or 0,
        "risk_medium": agg["medium"] or 0,
        "risk_low": agg["low"] or 0,
        "risk_critical": agg["critical"] or 0,
        "high_risk_orders": high_risk_orders,
        "abnormal_users": abnormal_users,
        "filter_house_id": house_id,
        "filter_request_id": request_id,
        "filter_level": level or "",
        "filter_date_from": request_get.get("date_from") or "",
        "filter_date_to": request_get.get("date_to") or "",
        "trend_labels": trend_labels,
        "trend_critical": trend_critical,
        "trend_high": trend_high,
        "trend_medium": trend_medium,
        "trend_low": trend_low,
        "paginator": paginator,
    }


def ai_risk_score_preview(alert_sample: list[dict]) -> dict:
    """
    Placeholder for future AI risk scoring.
    Pass lightweight dicts e.g. [{"level": "high", "alert_type": "..."}, ...]
    """
    if not alert_sample:
        return {"score": 0.0, "version": "rule-v0", "note": "no data"}
    weight = {"critical": 1.0, "high": 0.7, "medium": 0.4, "low": 0.15}
    s = sum(weight.get(x.get("level", "low"), 0.1) for x in alert_sample)
    return {
        "score": round(min(100.0, s * 12.0), 2),
        "version": "rule-v0",
        "note": "Replace with model inference endpoint",
    }
