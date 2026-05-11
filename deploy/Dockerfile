# =============================================================================
# Dockerfile: vLLM Serving Container for Jina Embeddings V5 Text Small
# =============================================================================
#
# This container runs vLLM as an OpenAI-compatible embedding server, serving
# the jinaai/jina-embeddings-v5-text-small model.
#
# vLLM is used as the serving framework because:
# 1. It supports embedding models natively via the /v1/embeddings endpoint
# 2. It handles dynamic batching automatically (groups incoming requests into
#    efficient GPU batches without client-side coordination)
# 3. It supports tensor parallelism across multiple GPUs (needed for 2-GPU test)
# 4. It's the framework commonly used for serving (vLLM v0.15.1)
#
# The model (jina-embeddings-v5-text-small) is a ~230M parameter embedding model
# with a 32k token context window. At BF16 precision, it fits comfortably on a
# single RTX Pro 6000 (48GB VRAM), leaving room for large batch processing.
#
# Build:
#   docker build -t <REGION>-docker.pkg.dev/<PROJECT>/<REPO>/jina-v5-vllm:latest .
#
# Run locally (for testing):
#   docker run --gpus all -p 8000:8000 jina-v5-vllm:latest
#
# =============================================================================

# Use the official vLLM OpenAI-compatible server image
# This image includes vLLM, PyTorch, CUDA runtime, and the OpenAI API server
FROM vllm/vllm-openai:v0.20.1

# Set environment variables for optimal GPU performance
# NCCL is used for multi-GPU communication when tensor_parallel_size > 1
ENV NCCL_DEBUG=WARN
# Disable tokenizer parallelism to avoid fork-related warnings in vLLM
ENV TOKENIZERS_PARALLELISM=false

# Expose the default vLLM serving port
# Vertex AI will send prediction requests to this port
EXPOSE 8000

# Health check endpoint — Vertex AI uses this to determine if the container is ready
# vLLM exposes /health which returns 200 when the model is loaded and ready
HEALTHCHECK --interval=30s --timeout=10s --start-period=300s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# =============================================================================
# vLLM Server Launch Configuration
# =============================================================================
#
# Key parameters explained:
#
# --model: The HuggingFace model ID. vLLM downloads it on first start.
#          In production, you'd bake the weights into the image or use a
#          GCS-mounted volume to avoid download time on cold start.
#
# --task: "embed" tells vLLM to run in embedding mode (not text generation).
#         This enables the /v1/embeddings endpoint and disables /v1/completions.
#
# --host 0.0.0.0: Listen on all interfaces (required for container networking).
#
# --port 8000: Default port. Vertex AI custom containers must serve on 8080
#              by default, but this is configurable in the deployment script
#              via the predict_route and health_route settings.
#
# --max-model-len 32768: Match Jina V5's maximum context window (32k tokens).
#         This pre-allocates KV cache for the maximum sequence length.
#
# --dtype bfloat16: Use BF16 precision (default for this model).
#         The model weights are stored in BF16 on HuggingFace, so no
#         quantization conversion is needed. This gives the best quality
#         while being efficient on modern GPUs (RTX Pro 6000 supports BF16).
#
# --tensor-parallel-size: Set via environment variable at deploy time.
#         1 for single-GPU, 2 for dual-GPU. This splits the model across
#         GPUs for parallel inference. For a 230M param model, this mainly
#         helps with throughput (parallel batch processing) rather than
#         fitting the model in memory.
#
# --disable-log-requests: Reduces log noise during benchmarking.
#         Each request would otherwise print input/output details.
#
# Note: vLLM automatically handles dynamic batching. Incoming requests are
# queued and grouped into batches that maximize GPU utilization. The
# --max-num-seqs parameter controls the maximum batch size (default: 256).
# We don't override it here — we'll test different concurrency levels from
# the client side and let vLLM's scheduler optimize batching.
# =============================================================================

ENTRYPOINT ["python3", "-m", "vllm.entrypoints.openai.api_server"]

CMD ["--model", "jinaai/jina-embeddings-v5-text-small", \
     "--task", "embed", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--max-model-len", "32768", \
     "--dtype", "bfloat16", \
     "--tensor-parallel-size", "1", \
     "--disable-log-requests"]
