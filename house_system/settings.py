"""
Django 项目配置文件 - 房屋代管系统
"""

import importlib.util
import os
import sys
from pathlib import Path

import pymysql
from django.core.exceptions import ImproperlyConfigured

# 使用 PyMySQL 作为 MySQLdb 的替代驱动（适用于未安装 mysqlclient 的环境）
pymysql.install_as_MySQLdb()

# 修复 PyMySQL 版本检查问题：Django 5.2+ 要求 mysqlclient>=2.2.1，
# 而 PyMySQL 模拟的 MySQLdb 版本较低，手动提升版本号避免报错
import MySQLdb

if MySQLdb.version_info < (2, 2, 1):
    MySQLdb.version_info = (2, 2, 1, "final", 0)

# 项目根目录
BASE_DIR = Path(__file__).resolve().parent.parent

# 尝试加载 .env 文件中的环境变量（开发环境常用）
try:
    from dotenv import load_dotenv

    load_dotenv(BASE_DIR / ".env")
except ImportError:
    # 生产环境可能未安装 python-dotenv，忽略即可
    pass

# 静态文件收集目录（collectstatic 后文件存放位置）
STATIC_ROOT = os.path.join(BASE_DIR, "staticfiles")
# 用户上传文件存放目录
MEDIA_ROOT = os.path.join(BASE_DIR, "media")

# 判断当前是否在运行单元测试
RUNNING_TESTS = "test" in sys.argv

# ---------- 安全相关配置 ----------
# DEBUG 模式：从环境变量读取，默认关闭（生产安全）
DEBUG = os.getenv("DJANGO_DEBUG", "False").lower() in ("1", "true", "yes")

# SECRET_KEY 处理：生产环境必须由环境变量提供，测试和本地开发提供后备值
SECRET_KEY = (os.getenv("DJANGO_SECRET_KEY") or "").strip()
if not SECRET_KEY:
    if RUNNING_TESTS:
        # 单元测试场景使用固定测试密钥
        SECRET_KEY = "test-secret-key-not-for-production"
    elif DEBUG and os.getenv("DJANGO_INSECURE_DEV", "").lower() in ("1", "true", "yes"):
        # 仅限本地开发且明确允许不安全模式时使用默认开发密钥
        SECRET_KEY = "django-insecure-local-dev-only-change-me"
    else:
        raise ImproperlyConfigured(
            "必须设置环境变量 DJANGO_SECRET_KEY。本地开发调试时如需临时绕过，请设置 DJANGO_INSECURE_DEV=1。"
        )

# ALLOWED_HOSTS 处理：生产环境必须显式配置，DEBUG 模式提供默认值
raw_hosts = (os.getenv("DJANGO_ALLOWED_HOSTS") or "").strip()
if raw_hosts:
    # 按逗号拆分并去除空白
    ALLOWED_HOSTS = [host.strip() for host in raw_hosts.split(",") if host.strip()]
elif DEBUG:
    # DEBUG 模式下允许本地常用地址
    ALLOWED_HOSTS = ["localhost", "127.0.0.1", "[::1]", "0.0.0.0"]
else:
    raise ImproperlyConfigured("当 DEBUG=False 时，必须通过环境变量 DJANGO_ALLOWED_HOSTS 设置允许的主机名。")

# ---------- 应用注册 ----------
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "houses.apps.HousesConfig",  # 自定义房产应用
]

# ---------- 中间件配置 ----------
# 检测是否安装了 whitenoise，用于静态文件服务优化
whitenoise_installed = importlib.util.find_spec("whitenoise") is not None

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
]

# 如果安装了 whitenoise，则插入其静态文件中间件（推荐放在 SecurityMiddleware 之后）
if whitenoise_installed:
    MIDDLEWARE.append("whitenoise.middleware.WhiteNoiseMiddleware")

MIDDLEWARE.extend([
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
])

ROOT_URLCONF = "house_system.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],  # 项目级模板目录
        "APP_DIRS": True,                  # 允许从各 app 的 templates 目录加载模板
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "houses.context_processors.hg_session_user",  # 自定义上下文处理器，注入会话用户信息
            ],
        },
    },
]

WSGI_APPLICATION = "house_system.wsgi.application"

# ---------- 数据库配置 ----------
if RUNNING_TESTS:
    # 单元测试强制使用内存 SQLite，提高测试速度且不污染开发/生产数据
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": ":memory:",
        }
    }
elif DEBUG and os.getenv("DJANGO_USE_SQLITE", "").lower() in ("1", "true", "yes"):
    # 开发环境下允许显式指定使用 SQLite（方便本地快速启动，无需 MySQL）
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }
else:
    # 正常 MySQL 配置
    # 密码处理：DEBUG 模式且未提供密码时，使用早期项目默认密码 114514（兼容团队习惯）
    # 生产环境（DEBUG=False）密码必须由环境变量提供，拒绝默认值保证安全
    if DEBUG:
        mysql_password = (os.getenv("MYSQL_PASSWORD") or "").strip() or "114514"
    else:
        mysql_password = (os.getenv("MYSQL_PASSWORD") or "").strip()
        if not mysql_password:
            raise ImproperlyConfigured(
                "生产环境下必须设置非空的 MYSQL_PASSWORD 环境变量。"
                "若需使用 SQLite 本地调试，请设置 DEBUG=true 和 DJANGO_USE_SQLITE=1。"
            )

    # MySQL 连接选项
    mysql_options = {
        "charset": "utf8mb4",
        "init_command": "SET sql_mode='STRICT_TRANS_TABLES'",  # 启用严格模式保证数据完整性
    }

    # SSL 配置：根据环境变量决定是否禁用 SSL
    # 调试模式下默认禁用 SSL，避免本地 MySQL 配置复杂；生产环境默认开启（除非显式指定禁用）
    ssl_disabled_env = os.getenv("DJANGO_MYSQL_SSL_DISABLED", "").strip().lower()
    if ssl_disabled_env in ("1", "true", "yes"):
        mysql_options["ssl_disabled"] = True
    elif DEBUG and ssl_disabled_env not in ("0", "false", "no"):
        # DEBUG 模式下未显式设置 SSL 行为时，默认禁用 SSL 便于本地开发
        mysql_options["ssl_disabled"] = True

    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.mysql",
            "NAME": os.getenv("MYSQL_DATABASE", "houseguard"),
            "USER": os.getenv("MYSQL_USER", "root"),
            "PASSWORD": mysql_password,
            "HOST": os.getenv("MYSQL_HOST", "127.0.0.1"),
            "PORT": os.getenv("MYSQL_PORT", "3306"),
            "OPTIONS": mysql_options,
        }
    }

# ---------- 密码验证规则 ----------
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# ---------- 国际化配置 ----------
LANGUAGE_CODE = "zh-hans"        # 简体中文
TIME_ZONE = "Asia/Shanghai"      # 上海时区
USE_I18N = True
USE_TZ = True

# ---------- 静态文件与媒体文件 ----------
STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]  # 开发阶段额外的静态文件目录

# 开发环境未执行 collectstatic 时，WhiteNoise 仍能从 finder 提供静态文件（仅当 whitenoise 已安装）
if whitenoise_installed:
    WHITENOISE_USE_FINDERS = DEBUG

MEDIA_URL = "/media/"
MEDIA_ROOT = os.path.join(BASE_DIR, "media")

# 默认主键字段类型
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ---------- 业务相关自定义配置 ----------
# 合同 PDF 生成时使用的中文字体路径（ReportLab 需要）
CONTRACT_PDF_FONT_PATH = (os.getenv("CONTRACT_PDF_FONT_PATH") or "").strip()

# DeepSeek / OpenAI 兼容 API 配置（用于智能对话等功能）
DEEPSEEK_API_URL = os.getenv("DEEPSEEK_API_URL", "https://api.deepseek.com").rstrip("/")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-reasoner")
DEEPSEEK_API_KEY = (os.getenv("DEEPSEEK_API_KEY", "") or os.getenv("AI_API_KEY", "")).strip()

# 请求超时设置，deepseek-reasoner 模型响应较慢，默认 120 秒
try:
    DEEPSEEK_REQUEST_TIMEOUT = int(os.getenv("DEEPSEEK_REQUEST_TIMEOUT", "120"))
except ValueError:
    DEEPSEEK_REQUEST_TIMEOUT = 120

# ---------- Session 与 CSRF 安全加固 ----------
SESSION_COOKIE_HTTPONLY = True          # 防止 JavaScript 读取 session cookie
SESSION_COOKIE_SAMESITE = "Lax"         # 防止跨站请求伪造
# 是否仅通过 HTTPS 传输 cookie：生产环境默认开启，DEBUG 模式默认关闭（便于本地 HTTP 调试）
SESSION_COOKIE_SECURE = os.getenv(
    "DJANGO_SESSION_COOKIE_SECURE", "true" if not DEBUG else "false"
).lower() in ("1", "true", "yes")

CSRF_COOKIE_HTTPONLY = True
CSRF_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SECURE = SESSION_COOKIE_SECURE

# CSRF 可信来源（用于跨域请求）
csrf_trusted_origins_raw = (os.getenv("DJANGO_CSRF_TRUSTED_ORIGINS", "") or "").strip()
if csrf_trusted_origins_raw:
    CSRF_TRUSTED_ORIGINS = [
        origin.strip() for origin in csrf_trusted_origins_raw.split(",") if origin.strip()
    ]
else:
    CSRF_TRUSTED_ORIGINS = []

# 如果应用部署在 HTTPS 代理之后，设置正确的请求头处理
if os.getenv("DJANGO_BEHIND_HTTPS_PROXY", "").lower() in ("1", "true", "yes"):
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    USE_X_FORWARDED_HOST = True

# 非 DEBUG 模式下启用额外安全头部
if not DEBUG:
    SECURE_CONTENT_TYPE_NOSNIFF = True
    X_FRAME_OPTIONS = "DENY"

# ---------- 缓存配置 ----------
redis_url = (os.getenv("REDIS_URL") or "").strip()
if redis_url:
    # 如果提供了 Redis 连接地址，则使用 Redis 作为缓存后端
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": redis_url,
        }
    }
else:
    # 默认使用本地内存缓存（适合单进程开发环境）
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "houseguard-local",
        }
    }