# nemo-stt — GPU STT server image.
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

RUN apt-get update \
    && apt-get install -y --no-install-recommends bash bzip2 ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

# Single-sourced model tag (default: non-streaming Parakeet; no hardcoded literal in this Dockerfile body — the
# Compose build.args supplies it from the single-sourced STT_MODEL env, AGENTS.md).
ARG STT_MODEL
# Revision pin (15a Item 2a). No default literal here (mirrors ARG STT_MODEL) — the
# single-sourced value comes from Compose build.args (${STT_MODEL_REVISION:-main}), so a
# bare `docker build` without the arg fails LOUD at snapshot_download rather than silently
# baking `main`. Operator pins the March-2026 commit SHA so the baked weights never drift.
ARG STT_MODEL_REVISION

# Server deps the base image does not already ship (torch/CUDA/NeMo come from the
# base — see requirements.txt). Use pip (this base is not uv-managed).
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# server.py imports the selected backend by STT_ENGINE/STT_RUNTIME.
COPY server.py backend_common.py backend_nemo.py backend_parakeet.py backend_parakeet_nemo.py ./

# Bake the GPU STT .nemo into the image at build (the NeMo equivalent of
# agent/Dockerfile's `download-files`) so the container starts offline-capable
# with no first-run download (local-first). References ARG STT_MODEL → no
# hardcoded tag.
# Snapshot-download the EXACT pinned commit into the HF cache (huggingface_hub has a
# documented `revision` arg; NeMo's from_pretrained does not), printing the resolved
# commit so the operator can confirm the baked snapshot matches the intended SHA.
RUN python -c "from huggingface_hub import snapshot_download; p=snapshot_download(repo_id='${STT_MODEL}', revision='${STT_MODEL_REVISION}'); print('baked snapshot commit dir:', p)"
# Bake the .nemo from the pinned cache. HF_HUB_OFFLINE forces resolution from the cache
# populated above instead of re-fetching `main`, so the baked weights == the pinned commit.
RUN HF_HUB_OFFLINE=1 python -c "import nemo.collections.asr as a; a.models.ASRModel.from_pretrained('${STT_MODEL}')"

# Runtime tag == bake tag so the loaded model never drifts from the baked weights.
# (STT_MODEL_REVISION is build-only — the pin is already baked into the offline cache
# below; a runtime ENV for it would be dead state, so it is intentionally not set.)
ENV STT_MODEL=${STT_MODEL}
# Runtime loads ONLY from the baked, pinned cache — never re-resolves a newer main.
ENV HF_HUB_OFFLINE=1

# Sherpa-onnx int8 bundle baked offline for CPU Parakeet and legacy hybrid correction;
# GPU buffered uses backend_parakeet_nemo.py with the baked STT_MODEL instead.
ENV STT_PARAKEET_MODEL=/models/parakeet-tdt-0.6b-v2-onnx-int8
COPY fetch_parakeet_onnx.sh ./fetch_parakeet_onnx.sh
RUN bash ./fetch_parakeet_onnx.sh "${STT_PARAKEET_MODEL}"

EXPOSE 8000

# Generous start_period — the model load is slow. Use a python urllib probe (NOT
# curl, which is not guaranteed in the NeMo base image — a missing-curl check
# would never pass and the agent would hang forever on service_healthy). This is
# the SAME command the Compose healthcheck uses (docker-compose.yml).
HEALTHCHECK --start-period=180s --interval=10s --timeout=5s --retries=30 \
    CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health').status==200 else 1)"]

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000"]
