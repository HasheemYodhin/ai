import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from check_k8s_manifests import check_document  # noqa: E402


def _deployment(**overrides):
    doc = {
        "kind": "Deployment",
        "metadata": {"name": "dabba"},
        "spec": {
            "template": {
                "spec": {
                    "securityContext": {"runAsNonRoot": True},
                    "containers": [
                        {
                            "name": "dabba",
                            "image": "dabba:1.2.3",
                            "resources": {
                                "requests": {"cpu": "250m", "memory": "512Mi"},
                                "limits": {"cpu": "1", "memory": "1Gi"},
                            },
                            "securityContext": {
                                "allowPrivilegeEscalation": False,
                                "privileged": False,
                            },
                        }
                    ],
                }
            }
        },
    }
    doc.update(overrides)
    return doc


def test_valid_deployment_has_no_errors():
    assert check_document(_deployment()) == []


def test_missing_resource_limits_fails():
    doc = _deployment()
    del doc["spec"]["template"]["spec"]["containers"][0]["resources"]["limits"]["memory"]
    errors = check_document(doc)
    assert any("resources.limits.memory" in e for e in errors)


def test_missing_resource_requests_fails():
    doc = _deployment()
    doc["spec"]["template"]["spec"]["containers"][0]["resources"] = {}
    errors = check_document(doc)
    assert any("resources.requests.cpu" in e for e in errors)
    assert any("resources.limits.cpu" in e for e in errors)


def test_latest_tag_fails():
    doc = _deployment()
    doc["spec"]["template"]["spec"]["containers"][0]["image"] = "dabba:latest"
    errors = check_document(doc)
    assert any("latest" in e for e in errors)


def test_missing_tag_fails():
    doc = _deployment()
    doc["spec"]["template"]["spec"]["containers"][0]["image"] = "dabba"
    errors = check_document(doc)
    assert any("no explicit tag" in e for e in errors)


def test_privileged_container_fails():
    doc = _deployment()
    doc["spec"]["template"]["spec"]["containers"][0]["securityContext"]["privileged"] = True
    errors = check_document(doc)
    assert any("privileged" in e for e in errors)


def test_no_security_context_fails():
    doc = _deployment()
    doc["spec"]["template"]["spec"]["securityContext"] = {}
    doc["spec"]["template"]["spec"]["containers"][0]["securityContext"] = {}
    errors = check_document(doc)
    assert any("securityContext" in e for e in errors)


def test_non_workload_kind_is_ignored():
    assert check_document({"kind": "Service", "metadata": {"name": "x"}}) == []


def test_cronjob_uses_job_template_pod_spec():
    doc = {
        "kind": "CronJob",
        "metadata": {"name": "nightly"},
        "spec": {
            "jobTemplate": {
                "spec": {
                    "template": {
                        "spec": {
                            "containers": [
                                {"name": "job", "image": "dabba:1.0.0"}
                            ]
                        }
                    }
                }
            }
        },
    }
    errors = check_document(doc)
    assert any("resources.requests.cpu" in e for e in errors)
