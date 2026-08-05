#!/usr/bin/env python3
"""Validate rendered Kubernetes manifests (e.g. `helm template` output) for
the baseline safety requirements from docs/pull-request-automation.md:

  - every container declares CPU + memory requests and limits
  - no container runs privileged
  - every container image has an explicit, non-"latest" tag
  - a security context is set (pod- or container-level)

Usage:
    helm template helm/dabba | python3 .github/scripts/check_k8s_manifests.py
"""

import sys

import yaml

WORKLOAD_KINDS = {"Deployment", "StatefulSet", "DaemonSet", "Job", "CronJob", "Pod"}


def _pod_spec(doc: dict) -> dict:
    kind = doc.get("kind")
    if kind == "CronJob":
        return (
            doc.get("spec", {})
            .get("jobTemplate", {})
            .get("spec", {})
            .get("template", {})
            .get("spec", {})
        )
    if kind == "Pod":
        return doc.get("spec", {})
    return doc.get("spec", {}).get("template", {}).get("spec", {})


def check_document(doc: dict) -> list:
    if not isinstance(doc, dict) or doc.get("kind") not in WORKLOAD_KINDS:
        return []

    name = doc.get("metadata", {}).get("name", "<unnamed>")
    kind = doc["kind"]
    errors = []

    pod_spec = _pod_spec(doc)
    pod_security_context = pod_spec.get("securityContext") or {}

    containers = list(pod_spec.get("containers", [])) + list(
        pod_spec.get("initContainers", [])
    )
    if not containers:
        return errors

    for container in containers:
        cname = container.get("name", "<unnamed container>")
        where = f"{kind}/{name} container '{cname}'"

        resources = container.get("resources") or {}
        requests = resources.get("requests") or {}
        limits = resources.get("limits") or {}
        for field, bucket in (("cpu", requests), ("memory", requests), ("cpu", limits), ("memory", limits)):
            bucket_name = "requests" if bucket is requests else "limits"
            if field not in bucket:
                errors.append(f"{where}: missing resources.{bucket_name}.{field}")

        image = container.get("image", "")
        if not image:
            errors.append(f"{where}: missing container image")
        elif ":" not in image.split("/")[-1]:
            errors.append(f"{where}: image '{image}' has no explicit tag")
        elif image.rsplit(":", 1)[-1] in ("latest", ""):
            errors.append(f"{where}: image '{image}' must not use the 'latest' tag")

        container_security_context = container.get("securityContext") or {}
        if container_security_context.get("privileged") is True:
            errors.append(f"{where}: must not run as a privileged container")

        if not container_security_context and not pod_security_context:
            errors.append(f"{where}: no pod- or container-level securityContext set")

    return errors


def main() -> int:
    text = sys.stdin.read()
    if not text.strip():
        print("No manifests provided on stdin.")
        return 0

    errors = []
    for doc in yaml.safe_load_all(text):
        if doc:
            errors.extend(check_document(doc))

    if errors:
        print("Kubernetes manifest validation failed:", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    print("Kubernetes manifest validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
