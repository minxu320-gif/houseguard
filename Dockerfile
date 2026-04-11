FROM registry.cn-hangzhou.aliyuncs.com/library/python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY requirements.txt /app/

RUN pip install --upgrade pip && pip install --no-cache-dir -r requirements.txt \
    && python -c "import whitenoise; print('whitenoise OK', whitenoise.__version__)"

COPY . /app/

EXPOSE 8000

CMD ["gunicorn", "house_system.wsgi:application", "--bind", "0.0.0.0:8000"]
