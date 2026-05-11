#!/usr/bin/env python3
"""
=============================================================================
Deploy Jina Embeddings V5 to Vertex AI Endpoint
=============================================================================

This script deploys the vLLM container (built from the Dockerfile) to a Vertex AI
Online Endpoint. It handles:

1. Creating a Vertex AI Model resource from the container image in Artifact Registry
2. Creating a Vertex AI Endpoint
3. Deploying the model to the endpoint with the specified GPU configuration

The endpoint serves the OpenAI-compatible /v1/embeddings API via vLLM.

Usage:
    # Deploy with 1 GPU (baseline test)
    python deploy_vertex.py --config config.yaml --gpu-count 1

    # Deploy with 2 GPUs (scaling test)
    python deploy_vertex.py --config config.yaml --gpu-count 2

What happens under the hood:
    1. We register a Vertex AI Model pointing to our container image in AR
    2. We create a Vertex AI Endpoint (a network-addressable resource)
    3. We deploy the model to the endpoint on a G4 machine with RTX Pro 6000 GPU(s)
    4. Vertex AI pulls the container, starts it on a GPU VM, and routes traffic to it
    5. The endpoint URL is printed — use it to send /v1/embeddings requests

Notes:
    - For the 2-GPU config, we override the container CMD to set --tensor-parallel-size 2
    - Deployment takes ~10-15 minutes (VM provisioning + model download + startup)
    - The endpoint is created with 1 replica (no autoscaling) for benchmarking
=============================================================================
"""

import argparse
import sys
import yaml
from google.cloud import aiplatform


def load_config(config_path: str) -> dict:
    """Load and return the YAML configuration file."""
    with open(config_path, "r") as f:
        return yaml.safe_load(f)


def get_container_image_uri(config: dict) -> str:
    """
    Construct the full container image URI from config.

    Format: <REGION>-docker.pkg.dev/<PROJECT_ID>/<REPO>/<IMAGE>:<TAG>

    This URI points to the vLLM container image we built and pushed to
    Google Artifact Registry.
    """
    gcp = config["gcp"]
    ar = gcp["artifact_registry"]
    return (
        f"{gcp['region']}-docker.pkg.dev/"
        f"{gcp['project_id']}/"
        f"{ar['repository']}/"
        f"{ar['image_name']}:{ar['image_tag']}"
    )


def get_hardware_config(config: dict, gpu_count: int) -> dict:
    """
    Get the hardware configuration for the specified GPU count.

    Returns the 'single_gpu' or 'dual_gpu' config block from config.yaml.
    """
    if gpu_count == 1:
        return config["hardware"]["single_gpu"]
    elif gpu_count == 2:
        return config["hardware"]["dual_gpu"]
    else:
        raise ValueError(f"Unsupported gpu_count: {gpu_count}. Must be 1 or 2.")


def build_container_args(config: dict, hw_config: dict) -> list[str]:
    """
    Build the vLLM server command-line arguments.

    These are passed as the container CMD, overriding the Dockerfile defaults.
    This is necessary because the tensor-parallel-size must match the GPU count,
    and we want to set it dynamically based on the deployment configuration.

    Returns a list of arguments like:
        ["--model", "jinaai/jina-embeddings-v5-text-small", ...]
    """
    model_config = config["model"]
    return [
        "--model", model_config["hf_model_id"],
        "--host", "0.0.0.0",
        "--port", str(model_config["serving_port"]),
        "--max-model-len", str(model_config["max_model_len"]),
        "--dtype", model_config["dtype"],
        "--tensor-parallel-size", str(hw_config["tensor_parallel_size"]),
        "--trust-remote-code",
        "--max-num-seqs", "512",
        "--gpu-memory-utilization", "0.95",
        "--enforce-eager",
        "--max-num-batched-tokens", "65536",
        "--disable-log-requests",
        "--disable-log-stats",
    ]


def upload_model(config: dict, hw_config: dict) -> aiplatform.Model:
    """
    Upload (register) the model to Vertex AI Model Registry.

    This doesn't upload any model weights — it registers a pointer to our
    container image and tells Vertex AI how to run it. The actual model weights
    are downloaded by vLLM from HuggingFace when the container starts.

    The key configuration here is:
    - container_image_uri: Points to our vLLM container in Artifact Registry
    - container_predict_route: Where Vertex AI sends prediction requests (/v1/embeddings)
    - container_health_route: Where Vertex AI checks if the container is ready (/health)
    - container_ports: Which port the container listens on (8000)
    - container_args: Override CMD to set tensor-parallel-size for multi-GPU
    """
    model_config = config["model"]
    image_uri = get_container_image_uri(config)
    container_args = build_container_args(config, hw_config)

    display_name = f"{model_config['display_name']}-{hw_config['display_name_suffix']}"

    print(f"\n📦 Uploading model to Vertex AI Model Registry...")
    print(f"   Display name: {display_name}")
    print(f"   Container image: {image_uri}")
    print(f"   Predict route: {model_config['predict_route']}")
    print(f"   Health route: {model_config['health_route']}")
    print(f"   Container args: {' '.join(container_args)}")

    model = aiplatform.Model.upload(
        display_name=display_name,
        serving_container_image_uri=image_uri,
        serving_container_predict_route=model_config["predict_route"],
        serving_container_health_route=model_config["health_route"],
        serving_container_ports=[model_config["serving_port"]],
        serving_container_args=container_args,
    )

    print(f"   ✅ Model registered: {model.resource_name}")
    return model


def create_endpoint(config: dict, hw_config: dict) -> aiplatform.Endpoint:
    """
    Create a Vertex AI Endpoint.

    An Endpoint is a network-addressable resource that receives prediction requests.
    Think of it as a load balancer that routes traffic to deployed model instances.

    For benchmarking, we create a dedicated endpoint per GPU configuration
    so we can test them independently.
    """
    model_config = config["model"]
    display_name = f"{model_config['display_name']}-endpoint-{hw_config['display_name_suffix']}"

    print(f"\n🌐 Creating Vertex AI Endpoint...")
    print(f"   Display name: {display_name}")

    endpoint = aiplatform.Endpoint.create(display_name=display_name)

    print(f"   ✅ Endpoint created: {endpoint.resource_name}")
    return endpoint


def deploy_model(
    model: aiplatform.Model,
    endpoint: aiplatform.Endpoint,
    config: dict,
    hw_config: dict,
) -> None:
    """
    Deploy the model to the endpoint on a GPU-equipped machine.

    This is where we specify:
    - machine_type: The VM type (e.g., g2-standard-8 for 1 GPU)
    - accelerator_type: The GPU type (NVIDIA_L4 for G2 instances)
    - accelerator_count: Number of GPUs (1 or 2)
    - min/max_replica_count: Both set to 1 for benchmarking (fixed capacity)

    Deployment takes ~10-15 minutes because Vertex AI needs to:
    1. Provision a VM with the requested GPU(s)
    2. Pull the container image from Artifact Registry
    3. Start the container and wait for the health check to pass
    4. The health check passes when vLLM has loaded the model and is ready to serve

    For the model download, vLLM pulls weights from HuggingFace on first start.
    In production, you'd want to bake weights into the image or use a GCS volume.
    """
    endpoint_config = config["endpoint"]

    print(f"\n🚀 Deploying model to endpoint...")
    print(f"   Machine type: {hw_config['machine_type']}")
    print(f"   Accelerator: {hw_config['accelerator_count']}× {hw_config['accelerator_type']}")
    print(f"   Replicas: {endpoint_config['min_replica_count']} (fixed for benchmarking)")
    print(f"   ⏳ This will take ~10-15 minutes...")

    model.deploy(
        endpoint=endpoint,
        machine_type=hw_config["machine_type"],
        accelerator_type=hw_config["accelerator_type"],
        accelerator_count=hw_config["accelerator_count"],
        min_replica_count=endpoint_config["min_replica_count"],
        max_replica_count=endpoint_config["max_replica_count"],
        traffic_percentage=endpoint_config["traffic_percentage"],
        deploy_request_timeout=endpoint_config["deploy_timeout"],
    )

    print(f"\n   ✅ Model deployed successfully!")
    print(f"\n{'='*60}")
    print(f"   ENDPOINT READY FOR BENCHMARKING")
    print(f"{'='*60}")
    print(f"   Endpoint ID: {endpoint.name}")
    print(f"   Endpoint Resource: {endpoint.resource_name}")
    print(f"   GPU Config: {hw_config['accelerator_count']}× {hw_config['accelerator_type']}")
    print(f"\n   To run benchmarks:")
    print(f"   python benchmark/run_benchmark.py \\")
    print(f"       --config deploy/config.yaml \\")
    print(f"       --endpoint-id {endpoint.name}")
    print(f"\n   To send a test request:")
    print(f"   curl -X POST \\")
    print(f"     -H 'Authorization: Bearer $(gcloud auth print-access-token)' \\")
    print(f"     -H 'Content-Type: application/json' \\")
    print(f"     -d '{{\"input\": [\"Hello world\"], \"model\": \"jinaai/jina-embeddings-v5-text-small\"}}' \\")
    print(f"     https://{config['gcp']['region']}-aiplatform.googleapis.com/v1/{endpoint.resource_name}:rawPredict")
    print(f"{'='*60}")


def main():
    parser = argparse.ArgumentParser(
        description="Deploy Jina Embeddings V5 to Vertex AI Endpoint",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Deploy with 1 GPU (baseline)
  python deploy_vertex.py --config config.yaml --gpu-count 1

  # Deploy with 2 GPUs (scaling test)
  python deploy_vertex.py --config config.yaml --gpu-count 2
        """,
    )
    parser.add_argument(
        "--config",
        type=str,
        required=True,
        help="Path to config.yaml file",
    )
    parser.add_argument(
        "--gpu-count",
        type=int,
        choices=[1, 2],
        required=True,
        help="Number of GPUs to deploy (1 for baseline, 2 for scaling test)",
    )

    args = parser.parse_args()

    # Load configuration
    config = load_config(args.config)
    hw_config = get_hardware_config(config, args.gpu_count)

    # Initialize Vertex AI SDK
    # This sets the project and region for all subsequent API calls
    print(f"🔧 Initializing Vertex AI...")
    print(f"   Project: {config['gcp']['project_id']}")
    print(f"   Region: {config['gcp']['region']}")

    aiplatform.init(
        project=config["gcp"]["project_id"],
        location=config["gcp"]["region"],
    )

    # Step 1: Upload model to Model Registry
    model = upload_model(config, hw_config)

    # Step 2: Create endpoint
    endpoint = create_endpoint(config, hw_config)

    # Step 3: Deploy model to endpoint
    deploy_model(model, endpoint, config, hw_config)

    print(f"\n✅ Deployment complete! Ready for benchmarking.")


if __name__ == "__main__":
    main()
