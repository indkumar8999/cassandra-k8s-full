SHELL := /bin/bash

DOCKERHUB_USER ?= your-dockerhub-user
IMAGE_TAG ?= 0.1.0
SIMULATOR_IMAGE ?= docker.io/$(DOCKERHUB_USER)/cassandra-simulator:$(IMAGE_TAG)
LEARNER_IMAGE ?= docker.io/$(DOCKERHUB_USER)/cassandra-ubl-learner:$(IMAGE_TAG)
CHAOS_IMAGE ?= docker.io/$(DOCKERHUB_USER)/cassandra-chaos-injector:$(IMAGE_TAG)
ORCH_IMAGE ?= docker.io/$(DOCKERHUB_USER)/cassandra-orchestrator:$(IMAGE_TAG)

.PHONY: build-images tag-images push-images deploy-core deploy-monitoring deploy-mvp deploy-strict run-demo collect-report collect-ablation cleanup-mvp demo-preflight show-images rebuild-multipass-2g rebuild-multipass-pressure auto-scale-on-alarm

build-images:
	docker build -t cassandra-simulator:latest ./simulator
	docker build -t cassandra-ubl-learner:latest ./ubl-learner
	docker build -t cassandra-chaos-injector:latest ./chaos-injector
	docker build -t cassandra-orchestrator:latest ./orchestrator

tag-images:
	docker tag cassandra-simulator:latest $(SIMULATOR_IMAGE)
	docker tag cassandra-ubl-learner:latest $(LEARNER_IMAGE)
	docker tag cassandra-chaos-injector:latest $(CHAOS_IMAGE)
	docker tag cassandra-orchestrator:latest $(ORCH_IMAGE)

push-images: tag-images
	docker push $(SIMULATOR_IMAGE)
	docker push $(LEARNER_IMAGE)
	docker push $(CHAOS_IMAGE)
	docker push $(ORCH_IMAGE)

show-images:
	@echo "SIMULATOR_IMAGE=$(SIMULATOR_IMAGE)"
	@echo "LEARNER_IMAGE=$(LEARNER_IMAGE)"
	@echo "CHAOS_IMAGE=$(CHAOS_IMAGE)"
	@echo "ORCH_IMAGE=$(ORCH_IMAGE)"

deploy-core:
	kubectl apply -f k8s/namespace.yaml
	kubectl apply -f k8s/cassandra/
	kubectl apply -f k8s/simulator/

deploy-monitoring:
	kubectl apply -f monitoring/cassandra-jmx-configmap.yaml
	kubectl patch statefulset cassandra -n cassandra-lab --patch-file monitoring/cassandra-statefulset-patch.yaml
	kubectl apply -f monitoring/cassandra-podmonitor.yaml
	kubectl apply -f monitoring/simulator-podmonitor.yaml
	kubectl apply -f monitoring/ubl-learner-podmonitor.yaml

deploy-mvp:
	kubectl apply -f k8s/ubl-learner/
	kubectl apply -f k8s/chaos-injector/
	kubectl apply -f k8s/orchestrator/orchestrator-config.yaml

deploy-strict: deploy-core deploy-monitoring deploy-mvp demo-preflight
	@echo "strict deployment complete"

demo-preflight:
	bash ./scripts/demo_preflight.sh

run-demo:
	python3 ./orchestrator/run_scenario.py --output-dir ./artifacts

collect-report:
	python3 ./reporting/generate_report.py --run-dir $$(ls -dt ./artifacts/* | head -1)

collect-ablation:
	python3 ./reporting/generate_report.py --runs-root ./artifacts

cleanup-mvp:
	bash ./scripts/cleanup_mvp.sh

# Destructive: deletes cp1+w1+w2+w3 and recreates k3s (default 4G RAM/VM; VM_MEMORY=2G for minimal hosts).
rebuild-multipass-2g:
	bash ./scripts/rebuild_multipass_k3s_2g.sh

# Destructive: same rebuild but 2G RAM per VM — higher fractional utilization; heavier OOM risk under stress (demo/pressure profile).
rebuild-multipass-pressure:
	VM_MEMORY=2G bash ./scripts/rebuild_multipass_k3s_2g.sh

elastic-cassandra-replicas:
	bash ./scripts/cassandra_elastic_replicas.sh

# Back-compat alias (was wait_for_alarm_and_scale.sh only; now full D+F cycle).
auto-scale-on-alarm: elastic-cassandra-replicas
