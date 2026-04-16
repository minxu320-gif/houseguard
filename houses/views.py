# 视图函数定义
from django.core.paginator import Paginator
from django.shortcuts import render, redirect
from .models import House
from django.contrib import messages
from .models import HouseTask, Pet, StayRequest, RiskAlert, StayTaskProgress
from django.shortcuts import get_object_or_404
from .models import User, UserProfile, UserCredit
from django.utils import timezone
from django.utils.safestring import mark_safe
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from django.conf import settings
import os
import json
import urllib.request
import urllib.error
import logging
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from .models import StayAgreement
from django.contrib import messages
from .models import StayCheckinLog, StayStatus
from .models import Rating
from django.db.models import Sum
from django.contrib.auth.hashers import make_password, check_password
from houses.utils.logger import log_action
from houses.services.credit_service import update_user_credit
from houses.services.risk_service import check_risk
from houses.services.match_service import calculate_match_score
from houses.services.risk_analytics_service import build_risk_alerts_page_context
from houses.services import dashboard_service
from houses.constants import DEFAULT_PAGE_SIZE
from .models import StayMatchScore

logger = logging.getLogger(__name__)

_AI_ERR_MSG_MAX = 800


def _short_user_message(msg, limit=_AI_ERR_MSG_MAX):
    """限制提示消息长度，避免超长错误内容导致页面异常。"""
    s = str(msg)
    if len(s) <= limit:
        return s
    return s[: limit - 1] + "…"


def _call_deepseek(prompt):
    """调用 DeepSeek 聊天接口并返回生成文本。"""
    api_key = getattr(settings, 'DEEPSEEK_API_KEY', '')
    if not api_key:
        return None, "未配置 DEEPSEEK_API_KEY"

    api_url = getattr(settings, 'DEEPSEEK_API_URL', 'https://api.deepseek.com').rstrip('/')
    model = getattr(settings, 'DEEPSEEK_MODEL', 'deepseek-reasoner')

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "你是房屋代管平台的专业助手，回答要实用、清晰、可执行。"},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.7
    }

    try:
        raw_body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            url=f"{api_url}/chat/completions",
            data=raw_body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            method="POST",
        )
        _timeout = int(getattr(settings, "DEEPSEEK_REQUEST_TIMEOUT", 120) or 120)
        with urllib.request.urlopen(req, timeout=_timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        choice0 = (body.get("choices") or [{}])[0]
        if not isinstance(choice0, dict):
            logger.warning("DeepSeek unexpected choice shape: %s", type(choice0).__name__)
            return None, "AI 返回格式异常"
        msg = choice0.get("message") or {}
        if not isinstance(msg, dict):
            msg = {}
        content = (msg.get("content") or "").strip()
        # deepseek-reasoner 等模型可能将输出放在 reasoning_content 字段
        if not content:
            content = (msg.get("reasoning_content") or "").strip()
        if not content:
            logger.warning("DeepSeek empty content; keys=%s", list(msg.keys()) if isinstance(msg, dict) else type(msg))
            return None, "AI 返回内容为空"
        return content, None
    except urllib.error.HTTPError as e:
        try:
            detail = e.read().decode("utf-8", errors="replace")
        except Exception:
            detail = str(e)
        logger.warning("DeepSeek HTTP %s: %s", getattr(e, "code", "?"), detail[:2000])
        return None, _short_user_message(f"AI 请求失败: {detail}")
    except Exception as e:
        logger.exception("DeepSeek request failed")
        return None, _short_user_message(f"AI 请求异常: {e}")


def _get_house_owner_id(house_id):
    house = House.objects.filter(house_id=house_id).first()
    return house.owner_id if house else None


def _active_approved_stay(house_id):
    """当前日期处于已批准申请的入住区间内时返回该申请（用于 AI 与任务进度）。"""
    today = timezone.localdate()
    return (
        StayRequest.objects.filter(
            house_id=house_id,
            status='approved',
            start_date__lte=today,
            end_date__gte=today,
        )
        .order_by('-request_id')
        .first()
    )


def _stay_span_days(req):
    return max((req.end_date - req.start_date).days + 1, 1)


def _task_progress_chart_for_request(req, today):
    """按入住天数计算各任务完成比例，并附今日是否已签到。"""
    tasks = list(HouseTask.objects.filter(house_id=req.house_id).order_by('task_id'))
    span = _stay_span_days(req)
    labels = []
    percents = []
    task_rows = []
    total = 0
    for t in tasks:
        done_n = StayTaskProgress.objects.filter(
            request_id=req.request_id, task_id=t.task_id, status='done'
        ).count()
        pct = min(100, int(round(100 * done_n / span)))
        labels.append((t.task_type or '任务')[:24])
        percents.append(pct)
        today_done = StayTaskProgress.objects.filter(
            request_id=req.request_id,
            task_id=t.task_id,
            status='done',
            update_time__date=today,
        ).exists()
        task_rows.append({
            'task': t,
            'done_count': done_n,
            'span_days': span,
            'percent': pct,
            'today_done': today_done,
        })
        total += pct
    overall = int(round(total / len(tasks))) if tasks else 100
    return labels, percents, overall, task_rows


def _add_credit_log(user_id, score_change, reason):
    UserCredit.objects.create(
        user_id=user_id,
        score_change=score_change,
        reason=reason,
        create_time=timezone.now()
    )


def _rating_to_credit_delta(score):
    """将 1-5 分评分映射为信用分增减值。"""
    return int(score) - 3


def house_list(request):
    qs = House.objects.all().order_by("-house_id")
    paginator = Paginator(qs, DEFAULT_PAGE_SIZE)
    page_obj = paginator.get_page(request.GET.get("page"))
    return render(request, "houses/house_list.html", {"page_obj": page_obj})


def house_detail(request, house_id):
    house = House.objects.get(house_id=house_id)
    pets = Pet.objects.filter(house_id=house_id)
    stay_requests = StayRequest.objects.filter(house_id=house_id)
    risk_alerts = RiskAlert.objects.filter(house_id=house_id)

    pet_care_plan = None
    cleaning_tips = None

    session_uid = request.session.get('user_id')
    try:
        is_owner = session_uid is not None and int(session_uid) == int(house.owner_id)
    except (TypeError, ValueError):
        is_owner = False

    # ===== 申请逻辑 =====
    if request.method == 'POST':
        action = request.POST.get('action')
        on_stay = _active_approved_stay(house_id)

        if action == 'apply':
            user_id = request.session.get('user_id')

            if not user_id:
                return redirect('/houses/login/')

            # 防止重复申请（可选但推荐）
            if StayRequest.objects.filter(house_id=house_id, sitter_id=user_id).exists():
                pass
            else:
                req = StayRequest.objects.create(
                    house_id=house_id,
                    sitter_id=user_id,
                    start_date=house.available_from,
                    end_date=house.available_to,
                    status='pending',
                    create_time=timezone.now()
                )
                calculate_match_score(req.request_id)
                log_action(request=request, user_id=user_id, action="stay_request.applied", target_id=req.request_id, target_type="stay_request")
        elif action == 'ai_pet_plan':
            if not on_stay:
                messages.error(request, "仅在已批准且当前处于入住期内可使用 AI 宠物照料计划")
            else:
                try:
                    house_tasks_ai = HouseTask.objects.filter(house_id=house_id)
                    pet_text = "；".join([f"{p.name}({p.type})" for p in pets]) if pets else "暂无宠物信息"
                    task_text = "；".join([f"{t.task_type}:{t.description or '无描述'}" for t in house_tasks_ai]) if house_tasks_ai else "暂无任务"
                    prompt = (
                        f"请为以下房屋生成7天宠物照料计划，按天列出喂食、清洁、互动和注意事项。\n"
                        f"房屋地址：{house.address}\n"
                        f"宠物：{pet_text}\n"
                        f"房屋任务：{task_text}\n"
                        "输出中文，分点清晰，便于执行。"
                    )
                    pet_care_plan, err = _call_deepseek(prompt)
                    if err:
                        messages.error(request, err)
                except Exception as e:
                    logger.exception("ai_pet_plan failed house_id=%s", house_id)
                    messages.error(request, f"生成宠物照料计划失败：{_short_user_message(e)}")
        elif action == 'ai_clean_tips':
            if not on_stay:
                messages.error(request, "仅在已批准且当前处于入住期内可使用 AI 清扫小贴士")
            else:
                house_tasks_ai = HouseTask.objects.filter(house_id=house_id)
                task_text = "；".join([f"{t.task_type}:{t.description or '无描述'}" for t in house_tasks_ai]) if house_tasks_ai else "暂无任务"
                prompt = (
                    f"请根据以下房屋信息生成房屋打扫小贴士（按区域：客厅、卧室、厨房、卫生间），"
                    f"并给出每日、每周清洁清单。\n"
                    f"房屋地址：{house.address}\n"
                    f"描述：{house.description or '无'}\n"
                    f"任务：{task_text}\n"
                    "输出中文，简洁可执行。"
                )
                cleaning_tips, err = _call_deepseek(prompt)
                if err:
                    messages.error(request, err)
        elif action == 'add_task':
            if not is_owner:
                messages.error(request, "仅房主可为该房源添加任务")
            else:
                task_type = (request.POST.get('task_type') or '').strip()
                description = (request.POST.get('description') or '').strip() or None
                freq = (request.POST.get('frequency') or '每日').strip()[:6]
                if not task_type:
                    messages.error(request, "请填写任务类型")
                else:
                    HouseTask.objects.create(
                        house_id=house_id,
                        task_type=task_type[:50],
                        description=description,
                        frequency=freq or '每日',
                    )
                    messages.success(request, "任务已添加")
            return redirect('house_detail', house_id=house_id)

    house_tasks = HouseTask.objects.filter(house_id=house_id)
    active_stay = _active_approved_stay(house_id)
    show_ai_features = active_stay is not None

    task_progress_rows = []
    if active_stay:
        span_days = (active_stay.end_date - active_stay.start_date).days + 1
        span_days = max(span_days, 1)
        for t in house_tasks:
            done_n = StayTaskProgress.objects.filter(
                request_id=active_stay.request_id,
                task_id=t.task_id,
                status='done',
            ).count()
            pct = min(100, int(round(100 * done_n / span_days)))
            task_progress_rows.append({
                'task': t,
                'done_count': done_n,
                'span_days': span_days,
                'percent': pct,
            })
    else:
        for t in house_tasks:
            task_progress_rows.append({
                'task': t,
                'done_count': 0,
                'span_days': None,
                'percent': None,
            })

    return render(request, 'houses/house_detail.html', {
        'house': house,
        'house_tasks': house_tasks,
        'pets': pets,
        'stay_requests': stay_requests,
        'risk_alerts': risk_alerts,
        'pet_care_plan': pet_care_plan,
        'cleaning_tips': cleaning_tips,
        'show_ai_features': show_ai_features,
        'active_stay': active_stay,
        'task_progress_rows': task_progress_rows,
        'is_owner': is_owner,
    })

def my_dashboard(request):
    user_id = request.session.get('user_id')
    if not user_id:
        return redirect('/houses/login/')

    user = User.objects.get(user_id=user_id)
    if user.role == 'owner':
        return redirect('/houses/owner/')
    return redirect('/houses/sitter/')


def owner_dashboard(request):
    user_id = request.session.get('user_id')
    if not user_id:
        return redirect('/houses/login/')

    user = User.objects.get(user_id=user_id)
    if user.role != 'owner':
        return redirect('/houses/sitter/')

    profile = UserProfile.objects.filter(user_id=user_id).first()
    houses = House.objects.filter(owner_id=user_id)
    house_ids = list(houses.values_list('house_id', flat=True))
    pets = Pet.objects.filter(house_id__in=house_ids)

    house_requests = StayRequest.objects.filter(house_id__in=house_ids)
    request_ids = list(house_requests.values_list('request_id', flat=True))
    agreements = StayAgreement.objects.filter(request_id__in=request_ids)
    match_scores = {m.request_id: m for m in StayMatchScore.objects.filter(request_id__in=request_ids)}
    sitters = {
        u.user_id: u for u in User.objects.filter(
            user_id__in=house_requests.values_list('sitter_id', flat=True)
        )
    }
    house_request_rows = []
    recommended_sitters = []
    for r in house_requests:
        score = match_scores.get(r.request_id)
        score_percent = int(round(float(score.total_score))) if score else 0
        match_reasons = []
        if score:
            if (score.experience_score or 0) >= 70:
                match_reasons.append("宠物经验匹配")
            if (score.time_match_score or 0) >= 80:
                match_reasons.append("地理与时间安排匹配")
            if (score.credit_score or 0) >= 75:
                match_reasons.append("信用评分高")
            if not match_reasons:
                match_reasons.append("基础匹配通过")

        house_request_rows.append({
            'req': r,
            'match_score': score,
            'score_percent': score_percent,
            'match_reasons': match_reasons,
            'sitter_user': sitters.get(r.sitter_id),
        })
        if score:
            recommended_sitters.append({
                'request_id': r.request_id,
                'house_id': r.house_id,
                'sitter_id': r.sitter_id,
                'sitter_name': sitters.get(r.sitter_id).username if sitters.get(r.sitter_id) else f"用户{r.sitter_id}",
                'score_percent': score_percent,
                'match_reasons': match_reasons,
            })

    recommended_sitters.sort(key=lambda x: x['score_percent'], reverse=True)
    recommended_sitters = recommended_sitters[:8]
    alerts = RiskAlert.objects.filter(house_id__in=house_ids).order_by('-create_time')[:10]

    agreements_with_perms = dashboard_service.build_agreements_with_perms(agreements, user_id)

    owner_credit_total = dashboard_service.owner_credit_total(user_id)
    return render(request, "houses/dashboard/owner_dashboard.html", {
        'user': user,
        'profile': profile,
        'houses': houses,
        'pets': pets,
        'house_request_rows': house_request_rows,
        'recommended_sitters': recommended_sitters,
        'alerts': alerts,
        'agreements_with_perms': agreements_with_perms,
        'MEDIA_URL': dashboard_service.media_url(),
        'owner_credit_total': owner_credit_total,
    })


def sitter_dashboard(request):
    user_id = request.session.get('user_id')
    if not user_id:
        return redirect('/houses/login/')

    user = User.objects.get(user_id=user_id)
    if user.role != 'sitter':
        return redirect('/houses/owner/')

    profile = UserProfile.objects.filter(user_id=user_id).first()
    my_requests = StayRequest.objects.filter(sitter_id=user_id)

    reminders = []
    report_rows = []
    today = timezone.now().date()

    request_ids = [req.request_id for req in my_requests]
    checkin_today_map = {}
    latest_log_map = {}
    if request_ids:
        checkin_today_map = {
            log.request_id: log for log in StayCheckinLog.objects.filter(
                request_id__in=request_ids,
                checkin_time__date=today
            )
        }
        for req in my_requests:
            latest_log_map[req.request_id] = StayCheckinLog.objects.filter(
                request_id=req.request_id
            ).order_by('-checkin_time').first()

    related_user_ids = set([user_id])
    for req in my_requests:
        req.today_checkin = checkin_today_map.get(req.request_id)
        req.latest_checkin_log = latest_log_map.get(req.request_id)
        req.task_rows = []

        owner_id = _get_house_owner_id(req.house_id)
        req.owner_id = owner_id
        if owner_id:
            related_user_ids.add(owner_id)

        task_list = HouseTask.objects.filter(house_id=req.house_id)
        for task in task_list:
            today_progress = StayTaskProgress.objects.filter(
                request_id=req.request_id,
                task_id=task.task_id,
                status='done',
                update_time__date=today
            ).order_by('-update_time').first()

            latest_progress = StayTaskProgress.objects.filter(
                request_id=req.request_id,
                task_id=task.task_id
            ).order_by('-update_time').first()

            req.task_rows.append({
                'task': task,
                'today_progress': today_progress,
                'latest_progress': latest_progress,
            })

        active_today = (req.status == 'approved' and req.start_date <= today <= req.end_date)
        total_tasks = len(task_list)
        done_tasks_today = sum(1 for row in req.task_rows if row['today_progress'])
        task_completion_rate = round((done_tasks_today / total_tasks) * 100, 1) if total_tasks else 100.0

        if active_today and not req.today_checkin:
            reminders.append(f"请求 {req.request_id} 今日还未完成入住签到")
        if active_today and total_tasks and done_tasks_today < total_tasks:
            reminders.append(f"请求 {req.request_id} 今日任务完成度 {done_tasks_today}/{total_tasks}，请及时补签")

        report_rows.append({
            'request_id': req.request_id,
            'house_id': req.house_id,
            'active_today': active_today,
            'checkin_done': bool(req.today_checkin),
            'task_done_today': done_tasks_today,
            'task_total': total_tasks,
            'task_completion_rate': task_completion_rate,
        })

    active_rows = [row for row in report_rows if row['active_today']]
    active_count = len(active_rows)
    checkin_done_count = sum(1 for row in active_rows if row['checkin_done'])
    task_total_today = sum(row['task_total'] for row in active_rows)
    task_done_today = sum(row['task_done_today'] for row in active_rows)
    report_summary = {
        'active_count': active_count,
        'checkin_rate': round((checkin_done_count / active_count) * 100, 1) if active_count else 100.0,
        'task_rate': round((task_done_today / task_total_today) * 100, 1) if task_total_today else 100.0,
        'reminder_count': len(reminders),
    }

    credit_score_map = {}
    for uid in related_user_ids:
        rows = Rating.objects.filter(target_id=uid)
        avg_score = round(sum(r.score for r in rows) / rows.count(), 2) if rows.exists() else None
        credit_total = UserCredit.objects.filter(user_id=uid).aggregate(total=Sum('score_change'))['total'] or 0
        credit_score_map[uid] = {'avg_rating': avg_score, 'credit_total': credit_total}

    for req in my_requests:
        req.owner_credit = credit_score_map.get(req.owner_id, {})
        req.sitter_credit = credit_score_map.get(req.sitter_id, {})

    sitter_credit_total = credit_score_map.get(user_id, {}).get('credit_total', 0)
    alerts = RiskAlert.objects.filter(request_id__in=request_ids).order_by('-create_time')[:10] if request_ids else []

    ag_by_req = {}
    if request_ids:
        ag_by_req = {a.request_id: a for a in StayAgreement.objects.filter(request_id__in=request_ids)}
    pending_contract_n = 0
    for req in my_requests:
        if req.status != 'approved':
            continue
        ag = ag_by_req.get(req.request_id)
        if not ag or not (ag.signed_by_sitter and ag.signed_by_host):
            pending_contract_n += 1

    return render(request, "houses/dashboard/sitter_dashboard.html", {
        'user': user,
        'profile': profile,
        'my_requests': my_requests,
        'reminders': reminders,
        'report_rows': report_rows,
        'report_summary': report_summary,
        'sitter_credit_total': sitter_credit_total,
        'alerts': alerts,
        'pending_contract_n': pending_contract_n,
    })


def owner_listings(request):
    """房主：集中查看、编辑已发布房源，并可视化当前入住的任务进度。"""
    user_id = request.session.get('user_id')
    if not user_id:
        return redirect('login')
    user = User.objects.get(user_id=user_id)
    if user.role != 'owner':
        messages.info(request, '「我发布的房源」仅房主可用。')
        return redirect('sitter_dashboard')

    today = timezone.localdate()
    houses = House.objects.filter(owner_id=user_id).order_by('-house_id')
    house_cards = []
    charts_for_js = []
    for house in houses:
        task_count = HouseTask.objects.filter(house_id=house.house_id).count()
        active = (
            StayRequest.objects.filter(
                house_id=house.house_id,
                status='approved',
                start_date__lte=today,
                end_date__gte=today,
            )
            .order_by('-request_id')
            .first()
        )
        agreement = None
        labels, percents, overall, task_rows = [], [], None, []
        if active:
            agreement = StayAgreement.objects.filter(request_id=active.request_id).first()
            labels, percents, overall, task_rows = _task_progress_chart_for_request(active, today)
            if labels:
                charts_for_js.append({
                    'canvasId': f'houseTaskChart{house.house_id}',
                    'labels': labels,
                    'data': percents,
                })
        house_cards.append({
            'house': house,
            'task_count': task_count,
            'active_stay': active,
            'agreement': agreement,
            'task_rows': task_rows,
            'overall_pct': overall if active else None,
            'contract_ok': (
                bool(agreement and agreement.signed_by_sitter and agreement.signed_by_host)
            ),
        })

    summary_labels = []
    summary_data = []
    for card in house_cards:
        if card['overall_pct'] is not None:
            summary_labels.append(f"房源 #{card['house'].house_id}")
            summary_data.append(card['overall_pct'])

    listings_total = len(house_cards)
    listings_active_stay = sum(1 for c in house_cards if c['active_stay'])
    listings_pending_contract = sum(
        1 for c in house_cards if c['active_stay'] and not c['contract_ok']
    )

    return render(request, "houses/dashboard/owner_listings.html", {
        'user': user,
        'house_cards': house_cards,
        'charts_json': mark_safe(json.dumps(charts_for_js)),
        'summary_chart_json': mark_safe(json.dumps({'labels': summary_labels, 'data': summary_data})),
        'listings_total': listings_total,
        'listings_active_stay': listings_active_stay,
        'listings_pending_contract': listings_pending_contract,
    })


def sitter_my_stays(request):
    """看护人（旅客）：待签合同区域 + 我的入住与任务进度图表。"""
    user_id = request.session.get('user_id')
    if not user_id:
        return redirect('login')
    user = User.objects.get(user_id=user_id)
    if user.role != 'sitter':
        messages.info(request, '「我的入住」仅看护人（旅客）可用。')
        return redirect('owner_dashboard')

    today = timezone.localdate()
    my_requests = list(StayRequest.objects.filter(sitter_id=user_id).order_by('-request_id'))
    request_ids = [r.request_id for r in my_requests]

    checkin_today_map = {}
    if request_ids:
        checkin_today_map = {
            log.request_id: log
            for log in StayCheckinLog.objects.filter(
                request_id__in=request_ids,
                checkin_time__date=today,
            )
        }

    house_ids = {r.house_id for r in my_requests}
    house_map = {h.house_id: h for h in House.objects.filter(house_id__in=house_ids)}

    contract_pending = []
    stay_cards = []
    charts_for_js = []
    summary_labels = []
    summary_data = []

    for req in my_requests:
        house = house_map.get(req.house_id)
        if not house:
            house = House.objects.filter(house_id=req.house_id).first()
        ag = StayAgreement.objects.filter(request_id=req.request_id).first()

        if req.status == 'approved' and not (ag and ag.signed_by_sitter and ag.signed_by_host):
            contract_pending.append({
                'req': req,
                'house': house,
                'agreement': ag,
                'need_sitter_sign': bool(ag and not ag.signed_by_sitter),
                'waiting_owner': bool(ag and ag.signed_by_sitter and not ag.signed_by_host),
                'missing_agreement': ag is None,
            })

        show_progress = (
            req.status == 'approved'
            and ag
            and ag.signed_by_sitter
            and ag.signed_by_host
            and today <= req.end_date
        )
        labels, percents, overall, task_rows = [], [], None, []
        if show_progress:
            labels, percents, overall, task_rows = _task_progress_chart_for_request(req, today)
            in_stay_today = req.start_date <= today <= req.end_date
            if in_stay_today and labels:
                charts_for_js.append({
                    'canvasId': f'stayTaskChart{req.request_id}',
                    'labels': labels,
                    'data': percents,
                })
                summary_labels.append(f"入住 #{req.request_id}")
                summary_data.append(overall)

        stay_cards.append({
            'req': req,
            'house': house,
            'agreement': ag,
            'today_checkin': checkin_today_map.get(req.request_id),
            'task_rows': task_rows,
            'overall_pct': overall,
            'show_progress': show_progress,
            'in_stay_today': req.start_date <= today <= req.end_date if req.status == 'approved' else False,
        })

    return render(request, "houses/dashboard/sitter_my_stays.html", {
        'user': user,
        'contract_pending': contract_pending,
        'stay_cards': stay_cards,
        'charts_json': mark_safe(json.dumps(charts_for_js)),
        'summary_chart_json': mark_safe(json.dumps({'labels': summary_labels, 'data': summary_data})),
        'stays_pending_contract_n': len(contract_pending),
        'stays_total_n': len(stay_cards),
        'stays_in_house_today_n': sum(1 for c in stay_cards if c['in_stay_today']),
    })


def statistics_view(request):
    user_id = request.session.get('user_id')
    if not user_id:
        return redirect('/houses/login/')
    user = User.objects.get(user_id=user_id)
    from datetime import timedelta
    now = timezone.now().date()
    days = [now]
    for i in range(1, 7):
        days.append(now - timedelta(days=i))
    days = list(reversed(days))

    # 按用户角色确定统计范围
    if user.role == 'owner':
        house_ids = list(House.objects.filter(owner_id=user_id).values_list('house_id', flat=True))
        req_ids = list(StayRequest.objects.filter(house_id__in=house_ids).values_list('request_id', flat=True))
    else:
        req_ids = list(StayRequest.objects.filter(sitter_id=user_id).values_list('request_id', flat=True))
        house_ids = list(StayRequest.objects.filter(request_id__in=req_ids).values_list('house_id', flat=True).distinct())

    labels = [d.strftime("%m-%d") for d in days]
    checkin_counts = []
    task_counts = []
    for d in days:
        checkin_counts.append(
            StayCheckinLog.objects.filter(request_id__in=req_ids, checkin_time__date=d).count()
        )
        task_counts.append(
            StayTaskProgress.objects.filter(request_id__in=req_ids, status='done', update_time__date=d).count()
        )

    risk_high = RiskAlert.objects.filter(request_id__in=req_ids, level='high').count()
    risk_medium = RiskAlert.objects.filter(request_id__in=req_ids, level='medium').count()
    risk_low = RiskAlert.objects.filter(request_id__in=req_ids, level='low').count()
    risk_critical = RiskAlert.objects.filter(request_id__in=req_ids, level='critical').count()

    # 仪表盘关键指标
    house_count = len(house_ids)
    agreement_count = StayAgreement.objects.filter(request_id__in=req_ids).count()
    request_count = len(req_ids)

    # 当前尚无账单表，先使用演示口径估算收入：
    # 已完成合同 699，进行中合同 399，已批准请求 199
    completed_count = StayAgreement.objects.filter(request_id__in=req_ids, status=StayAgreement.STATUS_COMPLETED).count()
    active_count = StayAgreement.objects.filter(request_id__in=req_ids, status=StayAgreement.STATUS_ACTIVE).count()
    approved_count = StayRequest.objects.filter(request_id__in=req_ids, status='approved').count()
    estimated_revenue = completed_count * 699 + active_count * 399 + approved_count * 199

    order_trend = []
    revenue_trend = []
    for d in days:
        day_orders = StayRequest.objects.filter(request_id__in=req_ids, create_time__date=d).count()
        day_completed = StayAgreement.objects.filter(request_id__in=req_ids, status=StayAgreement.STATUS_COMPLETED, owner_signed_at__date=d).count()
        day_active = StayAgreement.objects.filter(request_id__in=req_ids, status=StayAgreement.STATUS_ACTIVE, owner_signed_at__date=d).count()
        day_revenue = day_completed * 699 + day_active * 399 + (day_orders * 99)
        order_trend.append(day_orders)
        revenue_trend.append(day_revenue)

    return render(request, 'houses/statistics.html', {
        'user': user,
        'chart_labels': labels,
        'chart_labels_json': mark_safe(json.dumps(labels)),
        'chart_checkins_json': mark_safe(json.dumps(checkin_counts)),
        'chart_tasks_json': mark_safe(json.dumps(task_counts)),
        'order_trend_json': mark_safe(json.dumps(order_trend)),
        'revenue_trend_json': mark_safe(json.dumps(revenue_trend)),
        'risk_distribution_json': mark_safe(json.dumps([
            risk_critical, risk_high, risk_medium, risk_low,
        ])),
        'risk_high': risk_high,
        'risk_medium': risk_medium,
        'risk_low': risk_low,
        'risk_critical': risk_critical,
        'house_count': house_count,
        'agreement_count': agreement_count,
        'request_count': request_count,
        'estimated_revenue': estimated_revenue,
        'order_trend': order_trend,
        'revenue_trend': revenue_trend,
    })


def risk_alerts_view(request):
    user_id = request.session.get('user_id')
    if not user_id:
        return redirect('/houses/login/')
    user = User.objects.get(user_id=user_id)
    ctx = build_risk_alerts_page_context(user=user, request_get=request.GET)
    ctx["user"] = user
    ctx["trend_labels_json"] = mark_safe(json.dumps(ctx["trend_labels"]))
    ctx["trend_critical_json"] = mark_safe(json.dumps(ctx["trend_critical"]))
    ctx["trend_high_json"] = mark_safe(json.dumps(ctx["trend_high"]))
    ctx["trend_medium_json"] = mark_safe(json.dumps(ctx["trend_medium"]))
    ctx["trend_low_json"] = mark_safe(json.dumps(ctx["trend_low"]))
    return render(request, "houses/risk/alerts.html", ctx)

def login_view(request):
    if request.method == 'POST':
        action = request.POST.get('action')

        # ===== 登录逻辑 =====
        if action == 'login':
            username = request.POST.get('username')
            password = request.POST.get('password')

            try:
                user = User.objects.get(username=username)
                stored = user.password or ""
                ok = False
                try:
                    ok = check_password(password, stored)
                except Exception:
                    ok = False

                # 兼容旧明文密码：若明文匹配则允许登录并升级为哈希
                if (not ok) and stored == password:
                    ok = True
                    user.password = make_password(password)
                    user.save()

                if ok:
                    request.session['user_id'] = user.user_id
                    return redirect('/houses/my/')
                messages.error(request, "用户名或密码错误")
            except User.DoesNotExist:
                messages.error(request, "用户名或密码错误")

        # ===== 注册逻辑 =====
        elif action == 'register':
            username = request.POST.get('reg_username')
            password = request.POST.get('reg_password')
            role = request.POST.get('role') or 'sitter'

            # 检查用户名是否存在
            if User.objects.filter(username=username).exists():
                messages.error(request, "用户名已存在")
            else:
                User.objects.create(
                    username=username,
                    password=make_password(password),
                    role=role,
                    create_time=timezone.now()
                )
                messages.success(request, "注册成功，请登录")

    return render(request, "houses/auth/login.html")

def logout_view(request):
    request.session.flush()  # 清除 session
    return redirect('house_list')

def add_house(request):
    if request.method == "POST":
        user_id = request.session.get('user_id')

        if not user_id:
            return redirect('login')
        user = User.objects.get(user_id=user_id)
        if user.role != 'owner':
            messages.error(request, "只有房主可以新增房源")
            return redirect('/houses/my/')

        address = request.POST.get('address')
        description = request.POST.get('description')
        has_pet = int(request.POST.get('has_pet', 0))
        available_from = request.POST.get('available_from')
        available_to = request.POST.get('available_to')

        House.objects.create(
            owner_id=user_id,
            address=address,
            description=description,
            has_pet=has_pet,
            available_from=available_from,
            available_to=available_to,
            create_time=timezone.now()
        )

    return redirect('owner_listings')


def edit_house(request, house_id):
    user_id = request.session.get('user_id')
    if not user_id:
        return redirect('login')
    user = User.objects.get(user_id=user_id)
    if user.role != 'owner':
        messages.error(request, "只有房主可以编辑房源")
        return redirect('my_dashboard')

    house = get_object_or_404(House, house_id=house_id, owner_id=user_id)

    if request.method == 'POST':
        house.address = (request.POST.get('address') or '').strip()
        house.description = (request.POST.get('description') or '').strip() or None
        house.has_pet = int(request.POST.get('has_pet', 0))
        house.available_from = request.POST.get('available_from')
        house.available_to = request.POST.get('available_to')
        house.save()
        messages.success(request, "房源信息已更新")
        return redirect('owner_listings')

    return render(request, 'houses/house_edit.html', {'house': house})


def add_pet(request):
    if request.method != "POST":
        return redirect('my_dashboard')

    user_id = request.session.get('user_id')
    if not user_id:
        return redirect('login')

    user = User.objects.get(user_id=user_id)
    if user.role != 'owner':
        messages.error(request, "只有房主可以新增宠物")
        return redirect('my_dashboard')

    house_id_raw = request.POST.get('house_id')
    try:
        house_id = int(house_id_raw)
    except (TypeError, ValueError):
        messages.error(request, "请选择所属房源")
        return redirect('owner_dashboard')

    if not House.objects.filter(house_id=house_id, owner_id=user_id).exists():
        messages.error(request, "所选房源不存在或无权操作")
        return redirect('owner_dashboard')

    name = (request.POST.get('name') or '').strip()
    pet_type = (request.POST.get('type') or '').strip()
    if not name or not pet_type:
        messages.error(request, "请填写宠物名字与类型")
        return redirect('owner_dashboard')

    age_raw = (request.POST.get('age') or '').strip()
    age = int(age_raw) if age_raw.isdigit() else None

    description = (request.POST.get('description') or '').strip() or None

    Pet.objects.create(
        house_id=house_id,
        name=name[:50],
        type=pet_type[:50],
        age=age,
        description=description,
    )
    messages.success(request, "宠物已添加")
    return redirect('owner_dashboard')

def handle_request(request, request_id, action):
    user_id = request.session.get('user_id')
    if not user_id:
        return redirect('/houses/login/')
    user = User.objects.get(user_id=user_id)
    if user.role != 'owner':
        return redirect('/houses/my/')

    try:
        req = StayRequest.objects.get(request_id=request_id)
        house = House.objects.get(house_id=req.house_id)
        if house.owner_id != user_id:
            return redirect('/houses/my/')

        if action == 'approve':
            req.status = 'approved'
            req.save(update_fields=['status'])
            log_action(request=request, user_id=user_id, action="stay_request.approved", target_id=request_id, target_type="stay_request")

            # 审批状态优先落库，后续合同/入住状态异常不影响本次审批生效
            try:
                # 使用 get_or_create 避免重复生成合同
                agreement, created = StayAgreement.objects.get_or_create(
                    request_id=request_id,
                    defaults={
                        'signed_by_host': 0,
                        'signed_by_sitter': 0,
                        'status': 'pending',
                        'sitter_signed_at': None,
                        'owner_signed_at': None,
                        'pdf_path': '',
                        'sign_time': None
                    }
                )
                # 如果新创建了合同，或历史数据有合同记录但 PDF 未生成成功，则生成 PDF
                if created or not (agreement.pdf_path or "").strip():
                    owner = User.objects.get(user_id=house.owner_id)
                    sitter = User.objects.get(user_id=req.sitter_id)
                    pdf_path = generate_contract_pdf(agreement.agreement_id, req, house, owner, sitter)
                    agreement.pdf_path = pdf_path
                    agreement.save(update_fields=["pdf_path"])

                # ========== 创建入住状态（用于每日签到） ==========
                stay_status, _ = StayStatus.objects.get_or_create(
                    request_id=request_id,
                    defaults={
                        'current_status': 'active',
                        'checkin_required': 1,
                        'last_checkin_time': None,
                        'aborrmal_flag': 0,
                        'update_time': timezone.now()
                    }
                )
                # 如果已存在，确保状态正确（可选）
                if not stay_status.current_status == 'active':
                    stay_status.current_status = 'active'
                    stay_status.checkin_required = 1
                    stay_status.update_time = timezone.now()
                    stay_status.save()
                # =================================================
            except Exception as approve_side_effect_error:
                print("审批后置处理错误：", approve_side_effect_error)

        elif action == 'reject':
            req.status = 'rejected'
            log_action(request=request, user_id=user_id, action="stay_request.rejected", target_id=request_id, target_type="stay_request")
            req.save(update_fields=['status'])

    except Exception as e:
        print("审批错误：", e)

    return redirect('/houses/my/')

def _refresh_agreement_status(agreement, req):
    """
    pending -> sitter_signed -> owner_signed -> active -> completed
    """
    now = timezone.now()
    if agreement.signed_by_sitter and agreement.signed_by_host:
        # 双方均已签署
        if now.date() > req.end_date:
            agreement.status = StayAgreement.STATUS_COMPLETED
        elif req.start_date <= now.date() <= req.end_date:
            agreement.status = StayAgreement.STATUS_ACTIVE
        else:
            agreement.status = StayAgreement.STATUS_OWNER_SIGNED
    elif agreement.signed_by_sitter:
        agreement.status = StayAgreement.STATUS_SITTER_SIGNED
    elif agreement.signed_by_host:
        agreement.status = StayAgreement.STATUS_OWNER_SIGNED
    else:
        agreement.status = StayAgreement.STATUS_PENDING


def agreement_detail(request, agreement_id):
    user_id = request.session.get('user_id')
    if not user_id:
        return redirect('/houses/login/')

    agreement = get_object_or_404(StayAgreement, agreement_id=agreement_id)
    req = get_object_or_404(StayRequest, request_id=agreement.request_id)
    house = get_object_or_404(House, house_id=req.house_id)
    owner = get_object_or_404(User, user_id=house.owner_id)
    sitter = get_object_or_404(User, user_id=req.sitter_id)
    user = get_object_or_404(User, user_id=user_id)

    if user_id not in [owner.user_id, sitter.user_id]:
        messages.error(request, "你无权查看该合同")
        return redirect('/houses/my/')

    action = request.POST.get('action') if request.method == 'POST' else None
    if action == 'regenerate_pdf':
        try:
            pdf_path = generate_contract_pdf(agreement.agreement_id, req, house, owner, sitter)
            agreement.pdf_path = pdf_path
            agreement.save(update_fields=['pdf_path'])
            messages.success(request, "合同 PDF 已生成")
        except FileNotFoundError as e:
            messages.error(request, str(e))
        except Exception as e:
            logger.exception("regenerate_pdf failed agreement_id=%s", agreement_id)
            messages.error(request, f"生成 PDF 失败：{e}")
        return redirect('agreement_detail', agreement_id=agreement_id)

    if action == 'sitter_sign':
        if user_id != sitter.user_id:
            messages.error(request, "仅看护人可签署合同")
        elif agreement.signed_by_sitter:
            messages.info(request, "合同已签署，无需重复操作")
        else:
            agreement.signed_by_sitter = 1
            agreement.sitter_signed_at = timezone.now()
            log_action(request=request, user_id=user_id, action="stay_agreement.sitter_signed", target_id=agreement_id, target_type="stay_agreement")
            logger.info("Agreement %s signed by sitter %s", agreement_id, user_id)
    elif action == 'owner_confirm':
        if user_id != owner.user_id:
            messages.error(request, "仅房主可确认合同")
        elif not agreement.signed_by_sitter:
            messages.error(request, "请等待看护人先签署后再确认合同")
        elif agreement.signed_by_host:
            messages.info(request, "合同已确认，无需重复操作")
        else:
            agreement.signed_by_host = 1
            agreement.owner_signed_at = timezone.now()
            log_action(request=request, user_id=user_id, action="stay_agreement.owner_signed", target_id=agreement_id, target_type="stay_agreement")
            logger.info("Agreement %s confirmed by owner %s", agreement_id, user_id)

    if agreement.signed_by_sitter and agreement.signed_by_host and not agreement.sign_time:
        agreement.sign_time = timezone.now()

    _refresh_agreement_status(agreement, req)
    agreement.save()

    if request.method == 'POST':
        return redirect('agreement_detail', agreement_id=agreement_id)

    return render(request, 'houses/agreement_detail.html', {
        'agreement': agreement,
        'request_obj': req,
        'house': house,
        'owner': owner,
        'sitter': sitter,
        'is_owner': user_id == owner.user_id,
        'is_sitter': user_id == sitter.user_id,
        'MEDIA_URL': settings.MEDIA_URL,
    })


def sign_agreement(request, agreement_id):
    # 兼容旧版签署入口
    return redirect('agreement_detail', agreement_id=agreement_id)


def _resolve_contract_pdf_font_path():
    """返回可用于 ReportLab 中文渲染的 .ttf/.ttc 绝对路径，找不到则返回 None。"""
    from pathlib import Path

    explicit = (getattr(settings, "CONTRACT_PDF_FONT_PATH", None) or "").strip()
    candidates = []
    if explicit:
        candidates.append(Path(explicit))
    base = Path(settings.BASE_DIR)
    candidates.extend([
        base / "static" / "fonts" / "simhei.ttf",
        base / "static" / "fonts" / "SimHei.ttf",
        base / "static" / "fonts" / "NotoSansSC-Regular.ttf",
    ])
    for p in candidates:
        try:
            if p.is_file():
                return str(p.resolve())
        except OSError:
            continue
    return None


def generate_contract_pdf(agreement_id, request_obj, house, owner, sitter):
    """
    生成 PDF 合同，返回相对路径（如 'contracts/agreement_123.pdf'）
    """
    from reportlab.pdfgen import canvas
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from django.utils import timezone
    import os

    filename = f"agreement_{agreement_id}.pdf"
    contract_dir = os.path.join(settings.MEDIA_ROOT, 'contracts')
    os.makedirs(contract_dir, exist_ok=True)
    filepath = os.path.join(contract_dir, filename)

    font_path = _resolve_contract_pdf_font_path()
    if not font_path:
        raise FileNotFoundError(
            "未找到 PDF 中文字体。请将 simhei.ttf（或 NotoSansSC-Regular.ttf）放到项目 static/fonts/，"
            "或设置环境变量 CONTRACT_PDF_FONT_PATH 为字体文件的绝对路径。"
        )
    if "SimHei" not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont("SimHei", font_path))

    c = canvas.Canvas(filepath, pagesize=A4)
    width, height = A4

    # ================= 标题 =================
    c.setFont("SimHei", 20)
    c.drawCentredString(width / 2, height - 50, "HouseGuard+ 房屋代管电子合约")

    # ================= 正文 =================
    c.setFont("SimHei", 12)
    y = height - 100
    line_height = 22

    lines = [
        f"合同编号：{agreement_id}",
        f"签订日期：{timezone.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "甲方（房主）：",
        f"  用户名：{owner.username} (ID: {owner.user_id})",
        "",
        "乙方（看护人）：",
        f"  用户名：{sitter.username} (ID: {sitter.user_id})",
        "",
        "房屋信息：",
        f"  地址：{house.address}",
        f"  描述：{house.description or '无'}",
        f"  是否有宠物：{'是' if house.has_pet else '否'}",
        "",
        "代管期限：",
        f"  从 {request_obj.start_date} 至 {request_obj.end_date}",
        "",
        "双方承诺：",
        "1. 乙方将按照房主要求完成房屋及宠物的日常照料。",
        "2. 甲方保证房屋设施安全，并提供必要的使用说明。",
        "3. 双方应遵守平台规则，诚信交易。",
        "",
        "本合约自双方电子签署后生效。",
    ]

    for line in lines:
        # 自动换页
        if y < 60:
            c.showPage()
            c.setFont("SimHei", 12)
            y = height - 60

        c.drawString(40, y, line)
        y -= line_height

    # ================= 签名区 =================
    y -= 30
    c.drawString(40, y, "甲方签字：____________________")
    c.drawString(300, y, "乙方签字：____________________")

    y -= 40
    c.drawString(40, y, f"签署时间：{timezone.now().strftime('%Y-%m-%d')}")

    c.save()

    return f"contracts/{filename}"


def daily_checkin(request, request_id):
    """看护人每日签到"""
    user_id = request.session.get('user_id')
    if not user_id:
        return redirect('login')
    user = User.objects.get(user_id=user_id)
    if user.role != 'sitter':
        messages.error(request, '只有看护人可以签到')
        return redirect('/houses/my/')

    req = get_object_or_404(StayRequest, request_id=request_id)

    # 只有看护人可以签到
    if req.sitter_id != user_id:
        messages.error(request, '您没有权限为此入住请求签到')
        return redirect('my_dashboard')

    # 必须是已批准的申请
    if req.status != 'approved':
        messages.error(request, '该入住申请尚未批准，无法签到')
        return redirect('my_dashboard')

    today = timezone.now().date()
    if today < req.start_date or today > req.end_date:
        messages.error(request, '当前日期不在入住期间内，无法签到')
        return redirect('my_dashboard')

    # 防止重复签到（今天是否已签到）
    if StayCheckinLog.objects.filter(request_id=request_id, checkin_time__date=today).exists():
        messages.warning(request, '今天已经签到过了，无需重复签到')
        return redirect('my_dashboard')

    # 获取或创建 StayStatus（正常情况下已在批准时创建）
    stay_status, _ = StayStatus.objects.get_or_create(
        request_id=request_id,
        defaults={
            'current_status': 'active',
            'checkin_required': 1,
            'last_checkin_time': None,
            'aborrmal_flag': 0,
            'update_time': timezone.now()
        }
    )

    location = request.POST.get('location', '').strip()
    remark = request.POST.get('remark', '').strip()

    # 创建签到记录
    StayCheckinLog.objects.create(
        request_id=request_id,
        checkin_time=timezone.now(),
        location=location if location else None,
        remark=remark if remark else None
    )
    log_action(request=request, user_id=user_id, action="stay_checkin.created", target_id=request_id, target_type="stay_request")
    update_user_credit(
        user_id=user_id,
        action="daily_checkin",
        reason=f"请求{request_id} 每日签到",
        idempotency_key=f"daily_checkin:{request_id}:{today}",
    )

    # 更新入住状态中的最后签到时间
    stay_status.last_checkin_time = timezone.now()
    stay_status.aborrmal_flag = 0   # 正常签到，清除异常标志
    stay_status.update_time = timezone.now()
    stay_status.save()

    check_risk(request_id)
    messages.success(request, f'签到成功！签到时间：{timezone.now().strftime("%Y-%m-%d %H:%M:%S")}')
    return redirect('my_dashboard')


def task_checkin(request, request_id, task_id):
    """看护人对房屋任务进行每日签到。"""
    user_id = request.session.get('user_id')
    if not user_id:
        return redirect('login')
    user = User.objects.get(user_id=user_id)
    if user.role != 'sitter':
        messages.error(request, '只有看护人可以进行任务签到')
        return redirect('/houses/my/')

    if request.method != 'POST':
        return redirect('my_dashboard')

    req = get_object_or_404(StayRequest, request_id=request_id)

    if req.sitter_id != user_id:
        messages.error(request, '您没有权限为此任务签到')
        return redirect('my_dashboard')

    if req.status != 'approved':
        messages.error(request, '该入住申请尚未批准，无法进行任务签到')
        return redirect('my_dashboard')

    today = timezone.now().date()
    if today < req.start_date or today > req.end_date:
        messages.error(request, '当前日期不在入住期间内，无法进行任务签到')
        return redirect('my_dashboard')

    task = get_object_or_404(HouseTask, task_id=task_id, house_id=req.house_id)

    if StayTaskProgress.objects.filter(
        request_id=request_id,
        task_id=task_id,
        status='done',
        update_time__date=today
    ).exists():
        messages.warning(request, f'任务「{task.task_type}」今天已签到，无需重复提交')
        return redirect('my_dashboard')

    remark = request.POST.get('remark', '').strip()
    StayTaskProgress.objects.create(
        task_id=task.task_id,
        request_id=request_id,
        status='done',
        update_time=timezone.now(),
        remark=remark if remark else None
    )
    log_action(request=request, user_id=user_id, action="stay_task_progress.done", target_id=task_id, target_type="house_task")
    update_user_credit(
        user_id=user_id,
        action="task_completed",
        reason=f"请求{request_id} 完成任务{task_id}",
        idempotency_key=f"task_completed:{request_id}:{task_id}:{today}",
    )
    check_risk(request_id)

    messages.success(request, f'任务「{task.task_type}」签到成功')
    return redirect('my_dashboard')


def ai_score_assist(request, request_id):
    """使用 AI 生成建议评分与评语。"""
    user_id = request.session.get('user_id')
    if not user_id:
        return redirect('login')

    req = get_object_or_404(StayRequest, request_id=request_id)
    house = get_object_or_404(House, house_id=req.house_id)

    owner_id = house.owner_id
    sitter_id = req.sitter_id

    if user_id == sitter_id:
        target_id = owner_id
        relation = "看护人给房主评分"
    elif user_id == owner_id:
        target_id = sitter_id
        relation = "房主给看护人评分"
    else:
        messages.error(request, "无权限进行 AI 辅助评分")
        return redirect('my_dashboard')

    latest_checkin = StayCheckinLog.objects.filter(request_id=request_id).order_by('-checkin_time').first()
    latest_task = StayTaskProgress.objects.filter(request_id=request_id).order_by('-update_time').first()

    prompt = (
        f"请为以下代管关系给出建议评分（1-5分）和一句评语。\n"
        f"关系：{relation}\n"
        f"请求ID：{request_id}\n"
        f"入住时间：{req.start_date}~{req.end_date}\n"
        f"当前状态：{req.status}\n"
        f"最近入住签到：{latest_checkin.checkin_time if latest_checkin else '无'}\n"
        f"最近任务进度：{latest_task.update_time if latest_task else '无'}\n"
        "请输出严格 JSON：{\"score\": 1-5整数, \"comment\": \"不超过60字\"}"
    )

    ai_text, err = _call_deepseek(prompt)
    if err:
        messages.error(request, err)
        return redirect('my_dashboard')

    request.session[f'ai_rating_{request_id}_{target_id}'] = ai_text
    messages.success(request, "AI 评分建议已生成，请在互评区域查看并提交")
    return redirect('my_dashboard')


def submit_rating(request, request_id):
    """房主与看护人互评，并同步信用分变更记录。"""
    user_id = request.session.get('user_id')
    if not user_id:
        return redirect('login')
    if request.method != 'POST':
        return redirect('my_dashboard')

    req = get_object_or_404(StayRequest, request_id=request_id)
    house = get_object_or_404(House, house_id=req.house_id)
    owner_id = house.owner_id
    sitter_id = req.sitter_id

    if user_id == sitter_id:
        target_id = owner_id
    elif user_id == owner_id:
        target_id = sitter_id
    else:
        messages.error(request, "无权限评分")
        return redirect('my_dashboard')

    try:
        score = int(request.POST.get('score'))
        if score < 1 or score > 5:
            raise ValueError("invalid score")
    except Exception:
        messages.error(request, "评分必须为 1-5 分")
        return redirect('my_dashboard')

    comment = (request.POST.get('comment') or '').strip()
    ai_reference = request.session.get(f'ai_rating_{request_id}_{target_id}', '')

    old = Rating.objects.filter(request_id=request_id, rater_id=user_id).first()
    old_score = old.score if old else None

    if old:
        old.target_id = target_id
        old.score = score
        old.comment = comment or ai_reference or old.comment
        old.create_time = timezone.now()
        old.save()
    else:
        Rating.objects.create(
            request_id=request_id,
            rater_id=user_id,
            target_id=target_id,
            score=score,
            comment=comment or ai_reference or None,
            create_time=timezone.now()
        )
    log_action(request=request, user_id=user_id, action="rating.submitted", target_id=request_id, target_type="stay_request")

    new_delta = _rating_to_credit_delta(score)
    old_delta = _rating_to_credit_delta(old_score) if old_score is not None else 0
    delta_change = new_delta - old_delta
    if delta_change != 0:
        _add_credit_log(
            user_id=target_id,
            score_change=delta_change,
            reason=f"请求{request_id}互评变更: {old_score or '无'} -> {score}"
        )

    messages.success(request, "评分提交成功，信用分已更新")
    return redirect('my_dashboard')