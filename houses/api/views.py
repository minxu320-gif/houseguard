"""Lightweight JSON API (no DRF) — business logic stays in services."""

from __future__ import annotations

from django.http import JsonResponse
from django.views.decorators.http import require_GET

from houses.models import User
from houses.services.risk_analytics_service import ai_risk_score_preview, build_risk_alerts_page_context


@require_GET
def api_health(request):
    return JsonResponse({"status": "ok", "service": "houseguard"})


@require_GET
def api_risk_summary(request):
    user_id = request.session.get("user_id")
    if not user_id:
        return JsonResponse({"detail": "unauthorized"}, status=401)
    user = User.objects.get(user_id=user_id)
    ctx = build_risk_alerts_page_context(user=user, request_get=request.GET)
    sample = [
        {"level": a.level, "alert_type": a.alert_type}
        for a in ctx["alerts_page"].object_list[:50]
    ]
    preview = ai_risk_score_preview(sample)
    return JsonResponse(
        {
            "counts": {
                "critical": ctx["risk_critical"],
                "high": ctx["risk_high"],
                "medium": ctx["risk_medium"],
                "low": ctx["risk_low"],
            },
            "ai_risk_preview": preview,
            "page": ctx["alerts_page"].number,
            "total": ctx["paginator"].count,
        },
        json_dumps_params={"ensure_ascii": False},
    )
