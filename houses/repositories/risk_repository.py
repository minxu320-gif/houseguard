"""Data access for risk alerts (query construction only)."""

from __future__ import annotations

from django.db.models import QuerySet

from houses.models import RiskAlert


class RiskAlertRepository:
    @staticmethod
    def base_queryset_for_houses(house_ids: list[int]) -> QuerySet[RiskAlert]:
        if not house_ids:
            return RiskAlert.objects.none()
        return RiskAlert.objects.filter(house_id__in=house_ids).order_by("-create_time")

    @staticmethod
    def base_queryset_for_requests(request_ids: list[int]) -> QuerySet[RiskAlert]:
        return RiskAlert.objects.filter(request_id__in=request_ids).order_by("-create_time")

    @staticmethod
    def apply_filters(
        qs: QuerySet[RiskAlert],
        *,
        house_id: int | None,
        request_id: int | None,
        level: str | None,
        date_from,
        date_to,
    ) -> QuerySet[RiskAlert]:
        if house_id is not None:
            qs = qs.filter(house_id=house_id)
        if request_id is not None:
            qs = qs.filter(request_id=request_id)
        if level:
            qs = qs.filter(level=level.strip().lower())
        if date_from is not None:
            qs = qs.filter(create_time__date__gte=date_from)
        if date_to is not None:
            qs = qs.filter(create_time__date__lte=date_to)
        return qs
