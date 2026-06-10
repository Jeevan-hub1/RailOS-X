# RailOS Delta Lake Init Image
# Base: PySpark 3.5 + delta-spark 3.2 + S3A connector for MinIO
#
# Build:
#   docker build -t railos/delta-init:1.0.0 .
# Run (local test):
#   docker run --rm \
#     -e MINIO_ENDPOINT=http://localhost:9000 \
#     -e MINIO_ACCESS_KEY=minioadmin \
#     -e MINIO_SECRET_KEY=minioadmin \
#     -e DELTA_BUCKET=railos-delta-lake \
#     railos/delta-init:1.0.0

FROM python:3.11-slim AS base

# Java is required by PySpark
RUN apt-get update && apt-get install -y --no-install-recommends \
        openjdk-17-jre-headless \
        curl \
    && rm -rf /var/lib/apt/lists/*

ENV JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64
ENV PYSPARK_PYTHON=python3

# ── Python deps ───────────────────────────────────────────────────────────────
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Download hadoop-aws + aws-sdk JARs needed for S3A (MinIO)
# Versions must match the Hadoop version bundled with PySpark 3.5
ENV HADOOP_VERSION=3.3.4
ENV AWS_SDK_VERSION=1.12.262

RUN mkdir -p /opt/spark/jars && \
    curl -fsSL \
      "https://repo1.maven.org/maven2/org/apache/hadoop/hadoop-aws/${HADOOP_VERSION}/hadoop-aws-${HADOOP_VERSION}.jar" \
      -o /opt/spark/jars/hadoop-aws-${HADOOP_VERSION}.jar && \
    curl -fsSL \
      "https://repo1.maven.org/maven2/com/amazonaws/aws-java-sdk-bundle/${AWS_SDK_VERSION}/aws-java-sdk-bundle-${AWS_SDK_VERSION}.jar" \
      -o /opt/spark/jars/aws-java-sdk-bundle-${AWS_SDK_VERSION}.jar

# ── App ───────────────────────────────────────────────────────────────────────
COPY init_delta_tables.py /app/init_delta_tables.py

WORKDIR /app

ENV PYSPARK_SUBMIT_ARGS="\
  --jars /opt/spark/jars/hadoop-aws-${HADOOP_VERSION}.jar,/opt/spark/jars/aws-java-sdk-bundle-${AWS_SDK_VERSION}.jar \
  --packages io.delta:delta-spark_2.12:3.2.0 \
  pyspark-shell"

CMD ["python", "init_delta_tables.py"]
