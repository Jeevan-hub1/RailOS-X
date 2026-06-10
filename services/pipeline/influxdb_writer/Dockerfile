FROM python:3.11-slim
RUN groupadd -g 1000 railos && useradd -u 1000 -g railos -m railos
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY influxdb_writer.py .
USER railos
EXPOSE 8080
CMD ["python", "influxdb_writer.py"]
