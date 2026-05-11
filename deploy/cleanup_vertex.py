#!/usr/bin/env python3
"""
=============================================================================
Cleanup Vertex AI Resources After Benchmarking
=============================================================================

This script tears down all Vertex AI resources created during the benchmark:
1. Undeploys models from endpoints (stops the GPU VMs)
2. Deletes endpoints
3. Deletes model resources from the Model Registry

This is important because deployed endpoints incur per-hour GPU costs even
when idle. Always run this after benchmarking is complete.

Usage:
    # Clean up all benchmark resources (searches by display name pattern)
    python cleanup_vertex.py --config config.yaml

    # Clean up a specific endpoint by ID
    python cleanup_vertex.py --config config.yaml --endpoint-id <ENDPOINT_ID>

    # Dry run — show what would be deleted without actually deleting
    python cleanup_vertex.py --config config.yaml --dry-run

Cost Warning:
    A single G4 instance with RTX Pro 6000 costs ~$2-4/hour.
    If you forget to clean up after benchmarking, you'll be charged
    for every hour the endpoint remains deployed. Always clean up!
=============================================================================
"""

import argparse
import yaml
from google.cloud import aiplatform


def load_config(config_path: str) -> dict:
    """Load and return the YAML configuration file."""
    with open(config_path, "r") as f:
        return yaml.safe_load(f)


def cleanup_endpoint(endpoint: aiplatform.Endpoint, dry_run: bool = False) -> None:
    """
    Undeploy all models from an endpoint and delete the endpoint.

    Steps:
    1. List all deployed models on the endpoint
    2. Undeploy each model (this shuts down the GPU VMs)
    3. Delete the endpoint resource itself

    The undeploy step is what actually stops the billing — the endpoint
    resource itself doesn't cost anything, but the deployed model on a
    GPU VM does.
    """
    print(f"\n🔍 Endpoint: {endpoint.display_name}")
    print(f"   Resource: {endpoint.resource_name}")

    # Get all deployed models on this endpoint
    deployed_models = endpoint.gca_resource.deployed_models

    if deployed_models:
        for deployed_model in deployed_models:
            print(f"   📦 Deployed model: {deployed_model.id}")
            print(f"      Machine: {deployed_model.dedicated_resources.machine_spec.machine_type}")
            print(f"      GPUs: {deployed_model.dedicated_resources.machine_spec.accelerator_count}× "
                  f"{deployed_model.dedicated_resources.machine_spec.accelerator_type}")

            if not dry_run:
                print(f"      ⏳ Undeploying (stopping GPU VMs)...")
                endpoint.undeploy(deployed_model_id=deployed_model.id)
                print(f"      ✅ Undeployed")
            else:
                print(f"      [DRY RUN] Would undeploy")
    else:
        print(f"   No deployed models found")

    if not dry_run:
        print(f"   ⏳ Deleting endpoint...")
        endpoint.delete()
        print(f"   ✅ Endpoint deleted")
    else:
        print(f"   [DRY RUN] Would delete endpoint")


def cleanup_models(config: dict, dry_run: bool = False) -> None:
    """
    Delete model resources from the Vertex AI Model Registry.

    These are the model registrations (pointers to our container image),
    not the actual model weights. Deleting them is free and just cleans
    up the Model Registry.
    """
    model_display_name = config["model"]["display_name"]

    print(f"\n🔍 Searching for models matching: {model_display_name}*")

    models = aiplatform.Model.list(
        filter=f'display_name="{model_display_name}*"',
    )

    # Also search with suffix patterns
    for suffix in ["1gpu", "2gpu"]:
        name = f"{model_display_name}-{suffix}"
        suffix_models = aiplatform.Model.list(
            filter=f'display_name="{name}"',
        )
        models.extend(suffix_models)

    # Deduplicate by resource name
    seen = set()
    unique_models = []
    for model in models:
        if model.resource_name not in seen:
            seen.add(model.resource_name)
            unique_models.append(model)

    if not unique_models:
        print(f"   No matching models found")
        return

    for model in unique_models:
        print(f"\n   📦 Model: {model.display_name}")
        print(f"      Resource: {model.resource_name}")

        if not dry_run:
            print(f"      ⏳ Deleting model...")
            model.delete()
            print(f"      ✅ Model deleted")
        else:
            print(f"      [DRY RUN] Would delete model")


def main():
    parser = argparse.ArgumentParser(
        description="Clean up Vertex AI resources after benchmarking",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Clean up all benchmark resources
  python cleanup_vertex.py --config config.yaml

  # Clean up a specific endpoint
  python cleanup_vertex.py --config config.yaml --endpoint-id 1234567890

  # Preview what would be deleted
  python cleanup_vertex.py --config config.yaml --dry-run
        """,
    )
    parser.add_argument(
        "--config",
        type=str,
        required=True,
        help="Path to config.yaml file",
    )
    parser.add_argument(
        "--endpoint-id",
        type=str,
        default=None,
        help="Specific endpoint ID to clean up (optional — if not set, finds all)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be deleted without actually deleting",
    )

    args = parser.parse_args()

    # Load configuration
    config = load_config(args.config)

    # Initialize Vertex AI SDK
    print(f"🔧 Initializing Vertex AI...")
    print(f"   Project: {config['gcp']['project_id']}")
    print(f"   Region: {config['gcp']['region']}")

    if args.dry_run:
        print(f"\n   ⚠️  DRY RUN MODE — nothing will be deleted")

    aiplatform.init(
        project=config["gcp"]["project_id"],
        location=config["gcp"]["region"],
    )

    # Clean up endpoints
    if args.endpoint_id:
        # Clean up specific endpoint
        print(f"\n🎯 Cleaning up specific endpoint: {args.endpoint_id}")
        endpoint = aiplatform.Endpoint(endpoint_name=args.endpoint_id)
        cleanup_endpoint(endpoint, dry_run=args.dry_run)
    else:
        # Find all endpoints matching our naming pattern
        model_display_name = config["model"]["display_name"]
        print(f"\n🔍 Searching for endpoints matching: {model_display_name}*")

        endpoints = aiplatform.Endpoint.list(
            filter=f'display_name="{model_display_name}*"',
        )

        # Also search with suffix patterns
        for suffix in ["1gpu", "2gpu"]:
            name = f"{model_display_name}-endpoint-{suffix}"
            suffix_endpoints = aiplatform.Endpoint.list(
                filter=f'display_name="{name}"',
            )
            endpoints.extend(suffix_endpoints)

        # Deduplicate
        seen = set()
        unique_endpoints = []
        for ep in endpoints:
            if ep.resource_name not in seen:
                seen.add(ep.resource_name)
                unique_endpoints.append(ep)

        if not unique_endpoints:
            print(f"   No matching endpoints found")
        else:
            print(f"   Found {len(unique_endpoints)} endpoint(s)")
            for endpoint in unique_endpoints:
                cleanup_endpoint(endpoint, dry_run=args.dry_run)

    # Clean up models from registry
    cleanup_models(config, dry_run=args.dry_run)

    if args.dry_run:
        print(f"\n⚠️  DRY RUN complete. Run again without --dry-run to actually delete.")
    else:
        print(f"\n✅ Cleanup complete! All benchmark resources have been removed.")
        print(f"   GPU billing has stopped.")


if __name__ == "__main__":
    main()
