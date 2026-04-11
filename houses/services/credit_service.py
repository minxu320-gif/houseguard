from django.db.models import Sum
from django.utils import timezone

from houses.models import UserCredit


ACTION_RULES = {
    "task_completed": 5,
    "daily_checkin": 2,
    "missed_checkin": -10,
}


def get_credit_total(user_id):
    return UserCredit.objects.filter(user_id=user_id).aggregate(total=Sum("score_change"))["total"] or 0


def update_user_credit(*, user_id, action, reason, idempotency_key=None):
    """
    Add a credit delta row in UserCredit.
    - idempotency_key: if provided, will avoid duplicate entries by matching reason contains key.
    """
    if action not in ACTION_RULES:
        raise ValueError(f"Unknown credit action: {action}")

    delta = ACTION_RULES[action]
    if idempotency_key:
        if UserCredit.objects.filter(user_id=user_id, reason__contains=idempotency_key).exists():
            return 0

    UserCredit.objects.create(
        user_id=user_id,
        score_change=delta,
        reason=reason if not idempotency_key else f"{reason} [{idempotency_key}]",
        create_time=timezone.now(),
    )
    return delta

