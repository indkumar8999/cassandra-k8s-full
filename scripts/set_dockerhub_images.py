#!/usr/bin/env python3
import argparse
from pathlib import Path


TARGET_FILES = [
    "k8s/simulator/simulator-deployment.yaml",
    "k8s/ubl-learner/ubl-learner-deployment.yaml",
    "k8s/chaos-injector/chaos-injector-deployment.yaml",
    "k8s/orchestrator/orchestrator-job.yaml",
]


def update_file(path: Path, user: str, tag: str) -> None:
    text = path.read_text(encoding="utf-8")
    text = text.replace("docker.io/your-dockerhub-user/", f"docker.io/{user}/")
    text = text.replace(":0.1.0", f":{tag}")
    path.write_text(text, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Set Docker Hub image user and tag across K8s manifests.")
    parser.add_argument("--user", required=True, help="Docker Hub username")
    parser.add_argument("--tag", required=True, help="Image tag to apply")
    parser.add_argument("--root", default=".", help="Repository root that contains k8s/")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    for rel in TARGET_FILES:
        path = root / rel
        update_file(path, args.user, args.tag)
        print(f"updated {path}")


if __name__ == "__main__":
    main()
