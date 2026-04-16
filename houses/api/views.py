"""
轻量级 JSON API 接口（不依赖 DRF）
所有业务逻辑均委托给 services 层处理，视图层仅负责请求校验、数据组装和响应返回
"""

from django.http import JsonResponse
from django.views.decorators.http import require_GET

from houses.models import User
from houses.services.risk_analytics_service import ai_risk_score_preview, build_risk_alerts_page_context


@require_GET
def api_health(request):
    """
    健康检查接口，用于监控系统运行状态
    GET /api/health/
    """
    response_data = {
        "status": "ok",
        "service": "houseguard"
    }
    return JsonResponse(response_data)


@require_GET
def api_risk_summary(request):
    """
    风险数据摘要接口，返回当前登录用户的风险统计及 AI 评分预览
    GET /api/risk-summary/

    注意：原逻辑未捕获 User.DoesNotExist 异常，此处保持行为一致，
    若会话中的 user_id 对应记录已被删除，将抛出 500 错误，由上层中间件处理。
    """
    # 1. 会话校验：从 session 中获取当前登录用户的 ID
    session_user_id = request.session.get("user_id")
    if not session_user_id:
        return JsonResponse({"detail": "unauthorized"}, status=401)

    # 2. 获取用户对象
    user = User.objects.get(user_id=session_user_id)

    # 3. 构建风险告警页面的上下文数据（包含分页、统计计数等）
    context = build_risk_alerts_page_context(user=user, request_get=request.GET)

    # 4. 从上下文中提取所需信息
    risk_alerts_page = context["alerts_page"]          # 分页后的告警列表 Page 对象
    paginator = context["paginator"]                   # Paginator 实例，用于获取总数等

    # 5. 构建用于 AI 评分预览的样本数据（取当前页前 50 条告警）
    sample_list = []
    alert_objects = risk_alerts_page.object_list[:50]  # 最多取前 50 个告警对象
    for alert in alert_objects:
        sample_item = {
            "level": alert.level,
            "alert_type": alert.alert_type
        }
        sample_list.append(sample_item)

    # 6. 调用 AI 服务获取风险评分预览
    ai_preview_result = ai_risk_score_preview(sample_list)

    # 7. 组装 JSON 响应数据
    response_data = {
        "counts": {
            "critical": context["risk_critical"],
            "high": context["risk_high"],
            "medium": context["risk_medium"],
            "low": context["risk_low"],
        },
        "ai_risk_preview": ai_preview_result,
        "page": risk_alerts_page.number,
        "total": paginator.count,
    }

    # 确保中文字符不被转义为 Unicode 编码
    return JsonResponse(response_data, json_dumps_params={"ensure_ascii": False})