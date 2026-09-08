FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN DATABASE_URL=sqlite:///tmp.db python manage.py collectstatic --noinput

EXPOSE 8001

CMD sh -c "python manage.py migrate && (celery -A config worker --loglevel=info --pool=solo &) && python manage.py runserver --noreload 0.0.0.0:8000"