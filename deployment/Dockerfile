FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv/pagdoc
COPY backend/requirements.lock /tmp/requirements.lock
RUN pip install --no-cache-dir -r /tmp/requirements.lock && useradd --create-home --uid 10001 pagdoc && install -d -m 0700 -o pagdoc -g pagdoc /var/lib/pagdoc-files
COPY backend /srv/pagdoc/backend
COPY operacion.html /srv/pagdoc/operacion.html
COPY assets /srv/pagdoc/assets
USER pagdoc
WORKDIR /srv/pagdoc/backend
EXPOSE 8000
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
