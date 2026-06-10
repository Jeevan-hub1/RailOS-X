FROM python:3.11-slim

# Non-root user for security (Task 3.6 / container security policy)
RUN groupadd --gid 1000 railos && \
    useradd --uid 1000 --gid railos --no-create-home --shell /bin/false railos

WORKDIR /app

# Copy shared library and adapter source
COPY shared/ /app/shared/
COPY ntes/ /app/ntes/

# Install dependencies
RUN pip install --no-cache-dir -r /app/ntes/requirements.txt

USER 1000

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

EXPOSE 8080

CMD ["python", "-m", "ntes.ntes_adapter"]
