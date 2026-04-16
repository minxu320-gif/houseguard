"""
仪表盘相关业务逻辑处理模块
负责聚合数据并附加权限信息，保持视图层简洁
"""

from django.conf import settings
from django.db.models import Sum

from houses.models import House, StayAgreement, StayRequest, UserCredit


def build_agreements_with_perms(agreements, user_id):
    """
    为协议列表附加签署权限判断，避免在视图层产生 N+1 查询问题

    参数:
        agreements: StayAgreement 的查询集或列表
        user_id: 当前登录用户的 ID

    返回:
        字典列表，每个元素包含：
        - agreement: 协议对象本身
        - can_sign_by_sitter: 当前用户是否可作为看护人签署
        - can_sign_by_host: 当前用户是否可作为房主签署
    """
    # 强制转换为列表，确保后续操作稳定
    agreement_list = list(agreements)
    if not agreement_list:
        return []

    # 第一步：收集所有涉及的请求ID，批量查询对应的 StayRequest 记录
    request_id_list = [agreement.request_id for agreement in agreement_list]
    request_queryset = StayRequest.objects.filter(request_id__in=request_id_list)
    # 构建字典映射，key 为请求ID，value 为请求对象，方便 O(1) 查找
    request_dict = {req.request_id: req for req in request_queryset}

    # 第二步：从请求对象中提取所有涉及的房源ID，批量查询 House 记录
    house_id_set = {req.house_id for req in request_dict.values()}
    house_queryset = House.objects.filter(house_id__in=house_id_set)
    house_dict = {house.house_id: house for house in house_queryset}

    # 第三步：遍历协议列表，组装返回结果
    result_list = []
    for agreement in agreement_list:
        # 获取关联的请求对象
        request_obj = request_dict.get(agreement.request_id)
        if not request_obj:
            # 如果关联的请求不存在，跳过该协议（数据异常）
            continue

        # 获取关联的房源对象
        house_obj = house_dict.get(request_obj.house_id)
        if not house_obj:
            # 如果房源不存在，跳过
            continue

        # 判断签署权限：
        # - 看护人签署权限：当前用户是请求中的看护人，且协议尚未被看护人签署
        can_sitter_sign = (user_id == request_obj.sitter_id and not agreement.signed_by_sitter)
        # - 房主签署权限：当前用户是房源的拥有者，且协议尚未被房主签署
        can_owner_sign = (user_id == house_obj.owner_id and not agreement.signed_by_host)

        result_item = {
            "agreement": agreement,
            "can_sign_by_sitter": can_sitter_sign,
            "can_sign_by_host": can_owner_sign,
        }
        result_list.append(result_item)

    return result_list


def owner_credit_total(user_id):
    """
    获取指定房主的当前信用总分

    参数:
        user_id: 用户ID

    返回:
        整数类型的信用总分，若无记录则返回 0
    """
    # 聚合该用户所有信用变动记录的分数总和
    aggregate_result = UserCredit.objects.filter(user_id=user_id).aggregate(
        total_score=Sum("score_change")
    )
    total_score = aggregate_result.get("total_score") or 0
    return total_score


def media_url():
    """
    获取配置文件中定义的媒体文件访问 URL 前缀
    便于模板或其他模块统一引用
    """
    return settings.MEDIA_URL