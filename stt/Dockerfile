# nemo-stt — Nemotron cache-aware streaming ASR server image (Plan 09-01).
#
# Base on a CUDA-12.8+ Blackwell-capable NeMo image. This matters: the Kokoro
# precedent (docker-compose.yml:122-124) documents that stock PyTorch builds ship
# sm_50..sm_90 kernels only and crash on Blackwell (RTX 50-series, sm_120) at
# startup with "no kernel image is available for execution on the device". A
# CUDA-12.8 base is REQUIRED; the operator confirms sm_120 kernel execution on the
# real RTX 5090 at the 09-STT-VERIFY GPU gate. nvcr.io/nvidia/nemo:25.11 ships NeMo
# + an sm_120-capable torch preinstalled (alt: nvcr.io/nvidia/pytorch:25.11-py3 +
# pip install nemo_toolkit[asr] — uncomment the line in requirements.txt).
FROM nvcr.io/nvidia/nemo:25.11

WORKDIR /app

# Single-sourced model tag (no hardcoded literal in this Dockerfile body — the
# Compose build.args supplies it from the single-sourced STT_MODEL env, AGENTS.md).
ARG STT_MODEL

# Server deps the base image does not already ship (torch/CUDA/NeMo come from the
# base — see requirements.txt). Use pip (this base is not uv-managed).
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY server.py ./

# Bake the ~2.4 GB .nemo into the image at build (the NeMo equivalent of
# agent/Dockerfile's `download-files`) so the container starts offline-capable
# with no first-run download (local-first). References ARG STT_MODEL → no
# hardcoded tag.
RUN python -c "import nemo.collections.asr as a; a.models.ASRModel.from_pretrained('${STT_MODEL}')"

# Runtime tag == bake tag so the loaded model never drifts from the baked weights.
ENV STT_MODEL=${STT_MODEL}

EXPOSE 8000

# Generous start_period — the model load is slow. Use a python urllib probe (NOT
# curl, which is not guaranteed in the NeMo base image — a missing-curl check
# would never pass and the agent would hang forever on service_healthy). This is
# the SAME command the Compose healthcheck uses (docker-compose.yml).
HEALTHCHECK --start-period=180s --interval=10s --timeout=5s --retries=30 \
    CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health').status==200 else 1)"]

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000"]
