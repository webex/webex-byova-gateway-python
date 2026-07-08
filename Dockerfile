# Webex Contact Center BYOVA Gateway - container image
#
# Builds a minimal image that runs the gRPC gateway. The listen port is taken
# from $PORT at runtime (Cloud Run injects it). gRPC stubs are regenerated from
# the proto definitions during the build so the image is reproducible even when
# the generated *_pb2.py files are not checked in.

FROM python:3.12-slim AS base

# libsndfile1 is required at runtime by the soundfile package.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUTF8=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8080 \
    GATEWAY_CONFIG=config/config.cloudrun.yaml

WORKDIR /app

# Install Python dependencies first to maximize layer caching.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application source.
COPY . .

# Regenerate gRPC stubs from the proto definitions.
RUN python -m grpc_tools.protoc \
        -I./proto \
        --python_out=src/generated \
        --grpc_python_out=src/generated \
        proto/*.proto

# Run as an unprivileged user (defense in depth).
RUN useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app
USER appuser

# Documentational; Cloud Run overrides via $PORT.
EXPOSE 8080

CMD ["python", "main.py"]
