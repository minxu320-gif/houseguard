from django.db import models


class House(models.Model):
    house_id = models.BigAutoField(primary_key=True)
    owner_id = models.BigIntegerField()
    address = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)
    has_pet = models.IntegerField()
    available_from = models.DateField()
    available_to = models.DateField()
    create_time = models.DateTimeField()

    class Meta:
        db_table = "house"
        verbose_name = "房源"
        verbose_name_plural = "房源"
        indexes = [
            models.Index(fields=["owner_id", "create_time"], name="house_owner_ct_idx"),
        ]

    def __str__(self):
        return f"{self.address[:40]}…" if len(self.address) > 40 else self.address


class HouseTask(models.Model):
    task_id = models.BigAutoField(primary_key=True)
    house_id = models.BigIntegerField()
    task_type = models.CharField(max_length=50)
    description = models.TextField(blank=True, null=True)
    frequency = models.CharField(max_length=6)

    class Meta:
        db_table = "house_task"
        verbose_name = "房源任务"
        verbose_name_plural = "房源任务"
        indexes = [
            models.Index(fields=["house_id"], name="house_task_house_idx"),
        ]

    def __str__(self):
        return f"{self.task_type} (#{self.task_id})"


class Pet(models.Model):
    pet_id = models.BigAutoField(primary_key=True)
    house_id = models.BigIntegerField()
    name = models.CharField(max_length=50)
    type = models.CharField(max_length=50)
    age = models.IntegerField(blank=True, null=True)
    description = models.TextField(blank=True, null=True)

    class Meta:
        db_table = "pet"
        verbose_name = "宠物"
        verbose_name_plural = "宠物"

    def __str__(self):
        return f"{self.name} ({self.type})"


class Rating(models.Model):
    rating_id = models.BigAutoField(primary_key=True)
    request_id = models.BigIntegerField()
    rater_id = models.BigIntegerField()
    target_id = models.BigIntegerField()
    score = models.IntegerField()
    comment = models.TextField(blank=True, null=True)
    create_time = models.DateTimeField()

    class Meta:
        db_table = "rating"
        verbose_name = "评价"
        verbose_name_plural = "评价"

    def __str__(self):
        return f"{self.score} 星 · 申请 {self.request_id}"


class RiskAlert(models.Model):
    alert_id = models.BigAutoField(primary_key=True)
    house_id = models.BigIntegerField(db_index=True)
    request_id = models.BigIntegerField(blank=True, null=True, db_index=True)
    alert_type = models.CharField(max_length=50)
    level = models.CharField(max_length=16, db_index=True)
    message = models.CharField(max_length=255)
    create_time = models.DateTimeField(db_index=True)

    class Meta:
        db_table = "risk_alert"
        verbose_name = "风险告警"
        verbose_name_plural = "风险告警"
        indexes = [
            models.Index(fields=["house_id", "create_time"], name="risk_alert_house_ct_idx"),
            models.Index(fields=["request_id", "create_time"], name="risk_alert_req_ct_idx"),
            models.Index(fields=["level", "create_time"], name="risk_alert_level_ct_idx"),
        ]

    def __str__(self):
        return f"[{self.level}] {self.message[:50]}"


class SensorData(models.Model):
    data_id = models.BigAutoField(primary_key=True)
    house_id = models.BigIntegerField()
    sensor_type = models.CharField(max_length=50)
    value = models.CharField(max_length=100)
    record_time = models.DateTimeField()

    class Meta:
        db_table = "sensor_data"
        verbose_name = "传感器数据"
        verbose_name_plural = "传感器数据"

    def __str__(self):
        return f"{self.sensor_type}={self.value} @房源{self.house_id}"


class Statistics(models.Model):
    stat_id = models.BigAutoField(primary_key=True)
    stat_type = models.CharField(max_length=30)
    target_id = models.BigIntegerField(blank=True, null=True)
    metric = models.CharField(max_length=50)
    metric_value = models.DecimalField(max_digits=10, decimal_places=2)
    stat_date = models.DateField()
    create_time = models.DateTimeField()

    class Meta:
        db_table = "statistics"
        verbose_name = "统计记录"
        verbose_name_plural = "统计记录"

    def __str__(self):
        return f"{self.stat_type} / {self.metric} = {self.metric_value}"


class StayAgreement(models.Model):
    STATUS_PENDING = "pending"
    STATUS_SITTER_SIGNED = "sitter_signed"
    STATUS_OWNER_SIGNED = "owner_signed"
    STATUS_ACTIVE = "active"
    STATUS_COMPLETED = "completed"
    STATUS_CHOICES = [
        (STATUS_PENDING, "待签署"),
        (STATUS_SITTER_SIGNED, "看护人已签署"),
        (STATUS_OWNER_SIGNED, "房主已确认"),
        (STATUS_ACTIVE, "履约中"),
        (STATUS_COMPLETED, "已完成"),
    ]

    agreement_id = models.BigAutoField(primary_key=True)
    request_id = models.BigIntegerField()
    signed_by_host = models.IntegerField()
    signed_by_sitter = models.IntegerField()
    status = models.CharField(max_length=20, default=STATUS_PENDING, choices=STATUS_CHOICES)
    sitter_signed_at = models.DateTimeField(blank=True, null=True)
    owner_signed_at = models.DateTimeField(blank=True, null=True)
    pdf_path = models.CharField(max_length=255)
    sign_time = models.DateTimeField(blank=True, null=True)

    class Meta:
        db_table = "stay_agreement"
        verbose_name = "托管协议"
        verbose_name_plural = "托管协议"

    def __str__(self):
        return f"协议 {self.agreement_id} · 申请 {self.request_id} · {self.get_status_display()}"


class StayCheckinLog(models.Model):
    check_id = models.BigAutoField(primary_key=True)
    request_id = models.BigIntegerField()
    checkin_time = models.DateTimeField()
    location = models.CharField(max_length=255, blank=True, null=True)
    remark = models.CharField(max_length=255, blank=True, null=True)

    class Meta:
        db_table = "stay_checkin_log"
        verbose_name = "签到记录"
        verbose_name_plural = "签到记录"

    def __str__(self):
        return f"申请 {self.request_id} · {self.checkin_time}"


class StayMatchScore(models.Model):
    score_id = models.BigAutoField(primary_key=True)
    request_id = models.BigIntegerField()
    total_score = models.DecimalField(max_digits=5, decimal_places=2)
    experience_score = models.DecimalField(max_digits=5, decimal_places=2, blank=True, null=True)
    credit_score = models.DecimalField(max_digits=5, decimal_places=2, blank=True, null=True)
    time_match_score = models.DecimalField(max_digits=5, decimal_places=2, blank=True, null=True)
    remark = models.CharField(max_length=255, blank=True, null=True)

    class Meta:
        db_table = "stay_match_score"
        verbose_name = "匹配得分"
        verbose_name_plural = "匹配得分"

    def __str__(self):
        return f"申请 {self.request_id} · 总分 {self.total_score}"


class StayRequest(models.Model):
    request_id = models.BigAutoField(primary_key=True)
    house_id = models.BigIntegerField()
    sitter_id = models.BigIntegerField()
    start_date = models.DateField()
    end_date = models.DateField()
    status = models.CharField(max_length=30)
    reason = models.TextField(blank=True, null=True)
    create_time = models.DateTimeField()

    class Meta:
        db_table = "stay_request"
        verbose_name = "托管申请"
        verbose_name_plural = "托管申请"
        indexes = [
            models.Index(fields=["house_id", "status"], name="stay_req_house_st_idx"),
            models.Index(fields=["sitter_id", "status"], name="stay_req_sitter_st_idx"),
        ]

    def __str__(self):
        return f"申请 {self.request_id} · 房源 {self.house_id} · {self.status}"


class StayStatus(models.Model):
    status_id = models.BigAutoField(primary_key=True)
    request_id = models.BigIntegerField()
    current_status = models.CharField(max_length=30)
    checkin_required = models.IntegerField()
    last_checkin_time = models.DateTimeField(blank=True, null=True)
    aborrmal_flag = models.IntegerField()
    update_time = models.DateTimeField()

    class Meta:
        db_table = "stay_status"
        verbose_name = "托管状态"
        verbose_name_plural = "托管状态"

    def __str__(self):
        return f"申请 {self.request_id} · {self.current_status}"


class StayTaskProgress(models.Model):
    progress_id = models.BigAutoField(primary_key=True)
    task_id = models.BigIntegerField()
    request_id = models.BigIntegerField()
    status = models.CharField(max_length=5)
    update_time = models.DateTimeField()
    remark = models.CharField(max_length=255, blank=True, null=True)

    class Meta:
        db_table = "stay_task_progress"
        verbose_name = "任务进度"
        verbose_name_plural = "任务进度"

    def __str__(self):
        return f"任务 {self.task_id} · {self.status}"


class SystemLog(models.Model):
    log_id = models.BigAutoField(primary_key=True)
    user_id = models.BigIntegerField(blank=True, null=True)
    role = models.CharField(max_length=20, blank=True, null=True)
    action = models.CharField(max_length=100)
    target_type = models.CharField(max_length=50, blank=True, null=True)
    target_id = models.BigIntegerField(blank=True, null=True)
    ip_address = models.CharField(max_length=50, blank=True, null=True)
    log_level = models.CharField(max_length=7)
    create_time = models.DateTimeField()

    class Meta:
        db_table = "system_log"
        verbose_name = "系统日志"
        verbose_name_plural = "系统日志"

    def __str__(self):
        return f"{self.create_time} · {self.action}"


class User(models.Model):
    user_id = models.BigAutoField(primary_key=True)
    username = models.CharField(unique=True, max_length=50)
    password = models.CharField(max_length=255)
    role = models.CharField(max_length=20)
    create_time = models.DateTimeField()

    class Meta:
        db_table = "user"
        verbose_name = "用户"
        verbose_name_plural = "用户"

    def __str__(self):
        return self.username


class UserCredit(models.Model):
    log_id = models.BigAutoField(primary_key=True)
    user_id = models.BigIntegerField()
    score_change = models.IntegerField()
    reason = models.CharField(max_length=255, blank=True, null=True)
    create_time = models.DateTimeField()

    class Meta:
        db_table = "user_credit"
        verbose_name = "信誉流水"
        verbose_name_plural = "信誉流水"

    def __str__(self):
        return f"用户 {self.user_id} · {self.score_change:+d}"


class UserProfile(models.Model):
    user_id = models.BigIntegerField(primary_key=True)
    real_name = models.CharField(max_length=50, blank=True, null=True)
    gender = models.CharField(max_length=6, blank=True, null=True)
    phone = models.CharField(max_length=20, blank=True, null=True)
    email = models.CharField(max_length=100, blank=True, null=True)
    id_number = models.CharField(max_length=50, blank=True, null=True)
    experience_level = models.IntegerField(blank=True, null=True)
    bio = models.TextField(blank=True, null=True)

    class Meta:
        db_table = "user_profile"
        verbose_name = "用户资料"
        verbose_name_plural = "用户资料"

    def __str__(self):
        return self.real_name or f"用户 {self.user_id}"
