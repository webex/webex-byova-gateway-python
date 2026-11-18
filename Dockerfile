# Webex Contact Center BYOVA Gateway - ECS-ready runtime image
#
# The Amazon Linux base is pinned to its linux/amd64 platform digest. The
# deployment must still pin the resulting application image by ECR digest in
# its task definition.

FROM public.ecr.aws/amazonlinux/amazonlinux:2023-minimal@sha256:478c519817ce1c2cdc64700e4395775143446f8706706906b942960f0394ff2e AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build

RUN microdnf update -y \
    && microdnf install -y python3.12 python3.12-pip \
    && microdnf clean all

RUN python3.12 -m venv /opt/venv
ENV PATH="/opt/venv/bin:${PATH}"

COPY requirements.txt ./

# PyPI's Linux torch wheel pulls CUDA libraries. Install the pinned CPU build
# first; it satisfies the compatible runtime requirement in requirements.txt.
RUN pip install --index-url https://download.pytorch.org/whl/cpu \
        "torch==2.11.0+cpu" "torchaudio==2.11.0+cpu" \
    && pip install -r requirements.txt \
    && pip check

COPY proto/ ./proto/
COPY src/ ./src/

# Generated modules are build products, not workstation state.
RUN python -m grpc_tools.protoc \
        -I./proto \
        --python_out=src/generated \
        --grpc_python_out=src/generated \
        proto/*.proto \
    && pip uninstall --yes pip setuptools wheel


FROM public.ecr.aws/amazonlinux/amazonlinux:2023-minimal@sha256:478c519817ce1c2cdc64700e4395775143446f8706706906b942960f0394ff2e AS runtime

RUN microdnf update -y \
    && microdnf install -y ca-certificates libgomp libsndfile python3.12 \
    && microdnf clean all \
    && mkdir -p /app \
    && chown 10001:10001 /app

ENV PATH="/opt/venv/bin:${PATH}" \
    HOME=/tmp \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUTF8=1 \
    PORT=50051 \
    WEBSOCKET_PORT=8765 \
    GATEWAY_CONFIG=config/config.yaml \
    BYOVA_STDOUT_ONLY_LOGGING=true

WORKDIR /app

COPY --from=builder --chown=10001:10001 /opt/venv /opt/venv
COPY --from=builder --chown=10001:10001 /build/src ./src
COPY --chown=10001:10001 main.py ./
COPY --chown=10001:10001 config/ ./config/
COPY --chown=10001:10001 audio/ ./audio/

USER 10001:10001

EXPOSE 50051 8765 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD ["python", "src/runtime/healthcheck.py"]

STOPSIGNAL SIGTERM
CMD ["python", "src/runtime/container_bootstrap.py"]
