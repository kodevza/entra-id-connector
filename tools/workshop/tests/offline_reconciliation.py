#!/usr/bin/env python3
# SPDX-License-Identifier: CDDL-1.1
"""Run the reconciliation regression against disposable, offline OpenIDM."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import uuid

from mock_entra import BASE, CLIENT, GROUPS, SECRET, TENANT, USERS

TESTS = Path(__file__).resolve().parent
ROOT = TESTS.parents[2]
HOME = "/opt/openidm"
IDM_IMAGE = os.getenv("TEST_OPENIDM_IMAGE", "openidentityplatform/openidm:latest")
MOCK_IMAGE = os.getenv("TEST_PYTHON_IMAGE", "python:3.12-alpine")
MAVEN_IMAGE = "maven:3.9.11-eclipse-temurin-17"


def docker(*args, **kwargs):
    return subprocess.run(("docker", *args), check=True, text=True, **kwargs)


def build_fixture_bundle(work):
    # Use the real connector and its existing test transport constructor.
    # Production sources and artifacts stay outside the temporary build.
    shutil.copytree(ROOT / "src", work / "src")
    shutil.copy(ROOT / "pom.xml", work)
    source = work / "src/main/java/eu/soft4pm/openicf/entra/CloudClient.java"
    code = source.read_text()
    start = code.index("        this(config, URI.create(")
    end = code.index("\n    }", start)
    source.write_text(code[:start] + f'''        this(config, URI.create("{BASE}/token"),
                URI.create("{BASE}/graph/"), URI.create("{BASE}/arm/"));''' + code[end:])
    if shutil.which("mvn"):
        subprocess.run(("mvn", "-B", "-ntp", "-q", "-DskipTests", "package"), cwd=work, check=True)
    else:
        docker("run", "--rm", "--user", f"{os.getuid()}:{os.getgid()}",
               "--entrypoint", "sh", "-v", f"{work}:/work", "-w", "/work",
               "-v", "openidm-entra-maven-cache:/cache:ro", MAVEN_IMAGE,
               "-ec", "mkdir maven-cache; if [ -d /cache/repository ]; then "
               "cp -r /cache/repository/. maven-cache/; fi; "
               "mvn -B -ntp -q -Dmaven.repo.local=/work/maven-cache -DskipTests package")
    return next((work / "target").glob("entra-id-connector-*.jar"))


def configure(work, idm):
    def example(name):
        return json.loads((ROOT / f"openidm/{name}.example.json").read_text().replace(
            "REPLACE_WITH_TENANT_UUID", TENANT))

    def read(name):
        path = work / f"{name}.json"
        docker("cp", f"{idm}:{HOME}/conf/{path.name}", str(path))
        return json.loads(path.read_text())

    def write(name, value):
        path = work / f"{name}.json"
        path.write_text(json.dumps(value, indent=2))
        docker("cp", str(path), f"{idm}:{HOME}/conf/{path.name}")

    sys.path.insert(0, str(TESTS.parent))
    from identity_config import build_mapping, extend_managed

    managed = read("managed")
    objects = {"entraGroup", "entraServicePrincipal"}
    managed["objects"].extend(o for o in example("managed-entra")["objects"] if o["name"] in objects)
    extend_managed(managed)
    write("managed", managed)

    repo = read("repo.orientdb")
    classes = repo["dbStructure"]["orientdbClass"]
    example_classes = example("repo.orientdb-entra")["dbStructure"]["orientdbClass"]
    classes.update({f"managed_{name}": example_classes[f"managed_{name}"] for name in objects})
    write("repo.orientdb", repo)

    group_mapping = next(m for m in example("sync-entra")["mappings"] if m["target"] == "managed/entraGroup")
    principal_mapping = next(m for m in example("sync-entra")["mappings"]
                             if m["target"] == "managed/entraServicePrincipal")
    write("sync", {"mappings": [group_mapping, build_mapping(TENANT), principal_mapping]})
    docker("cp", str(ROOT / "openidm/script/entra"), f"{idm}:{HOME}/script/")

    provisioner = example("provisioner.openicf-entra")
    provisioner["configurationProperties"].update(clientId=CLIENT, clientSecret=SECRET)
    types = provisioner["objectTypes"]
    provisioner["objectTypes"] = {types[k]["id"]: types[k] for k in ("account", "group", "servicePrincipal")}
    write("provisioner.openicf-entra", provisioner)


def main():
    idm = f"openidm-recon-{uuid.uuid4().hex[:12]}"
    mock = f"{idm}-mock"
    images = (IDM_IMAGE, MOCK_IMAGE) if shutil.which("mvn") else (IDM_IMAGE, MOCK_IMAGE, MAVEN_IMAGE)
    for image in images:
        docker("image", "inspect", image, stdout=subprocess.DEVNULL)
    with tempfile.TemporaryDirectory(prefix="openidm-offline-") as temp:
        work = Path(temp)
        work.chmod(0o755)
        bundle = build_fixture_bundle(work)
        try:
            docker("create", "--name", idm, "--network", "none", IDM_IMAGE)
            docker("cp", str(bundle), f"{idm}:{HOME}/bundle/{bundle.name}")
            configure(work, idm)
            docker("start", idm)
            docker("run", "-d", "--name", mock, "--network", f"container:{idm}",
                   "--mount", f"type=bind,src={TESTS},dst=/tests,readonly",
                   MOCK_IMAGE, "python3", "/tests/mock_entra.py")
            for _ in range(120):
                ready = subprocess.run((
                    "docker", "exec", idm, "sh", "-c",
                    f"grep -q 'entra route enabled' {HOME}/logs/openidm0.log.0 && "
                    "curl -fsS -H 'X-OpenIDM-Username: openidm-admin' "
                    "-H 'X-OpenIDM-Password: openidm-admin' "
                    "http://127.0.0.1:8080/openidm/info/ping | grep -q ACTIVE_READY",
                ), capture_output=True)
                if ready.returncode == 0:
                    break
                time.sleep(1)
            else:
                raise TimeoutError("OpenIDM did not activate the test connector")
            credentials = ("-e", "OPENIDM_URL=http://127.0.0.1:8080/openidm",
                           "-e", "OPENIDM_PASSWORD=openidm-admin")
            docker("exec", *credentials,
                   "-e", f"EXPECTED_ENTRA_GROUPS={len(GROUPS)}",
                   "-e", f"EXPECTED_ENTRA_USERS={len(USERS)}",
                   mock, "python3", "/tests/live_reconciliation.py")
            docker("exec", *credentials, mock, "python3", "/tests/offline_principal.py")
            docker("exec", *credentials, mock, "python3", "/tests/live_identity.py",
                   "--url", "http://127.0.0.1:8080/openidm", "--tenant", TENANT)
        except (subprocess.CalledProcessError, TimeoutError):
            subprocess.run(("docker", "logs", "--tail", "40", mock), check=False)
            subprocess.run(("docker", "logs", "--tail", "60", idm), check=False)
            raise
        finally:
            subprocess.run(("docker", "rm", "-f", mock, idm), capture_output=True)


if __name__ == "__main__":
    main()
