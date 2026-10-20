FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 SETU_DB=/data/setu.sqlite3
WORKDIR /app
COPY . /app
RUN useradd --uid 10001 --create-home setu && mkdir /data && chown setu:setu /data
USER 10001:10001
VOLUME /data
EXPOSE 8000
ENTRYPOINT ["sh", "/app/entrypoint.sh"]
