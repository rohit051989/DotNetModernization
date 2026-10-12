"""The WCF client matrix probe (29-ENTRY-POINT-AND-OUTBOUND-INVENTORIES.md C11).

For each matrix entry the SOAP backend compatibility report relies on, a
minimal .NET 10 WCF client (steps/step-003-fingerprinting/probes/WcfClientProbe)
runs in a Linux container and calls a real service with that binding, security
mode and credential type. The outcome is evidence, not a verdict:

- the full result is written to probes/evidence/, and its sha256 recorded;
- a probe record is appended to the ``probes`` list of each entry it bears on,
  in the runtime matrix (wcf-client-support) and the platform matrix
  (wcf-client-platform). Each record says what its evidence covers: the WCF
  client package version and the .NET runtime it ran against (``covers``);
- no verdict and no confirmation is changed. A person confirms the entry, now
  with the probe result in front of them; a probe that contradicts its entry
  keeps the report a draft until a person revises the entry.

When a Linux probe fails, two controls attribute it: the same scenario with the
System.Security.Cryptography.Xml WCF brings by itself (the probe pins a newer
one), and the same client binary on the Windows host. A failure that passes on
Windows is the platform's, not the runtime's.

Certificates are files in a scratch folder (the plan's ``certificates``),
written by ``WcfClientProbe make-certificates`` (``--make-certificates``). The
client pins the server's certificate by the thumbprint of server.cer and
presents client.pfx; nothing is read from or written to a certificate store.

What cannot be probed here is recorded as such, never guessed: Windows
credentials on NetTcp negotiate Kerberos, and no Kerberos environment is
available to the probe. It is an open item for onboarding (OPEN_ITEM).

Services are not started here — Start-ProbeServices.ps1 and the plan's notes.
If no Linux container runtime is available, the probe stops and says so; it
never simulates one.

    python -m app.estate.wcf_probe --plan runs\\probes\\probe-plan.json [--make-certificates]
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from app.estate import wcf_matrix

REPO = Path(__file__).resolve().parents[3]
PROBE_PROJECT = REPO / "steps" / "step-003-fingerprinting" / "probes" / "WcfClientProbe"
EVIDENCE_DIR = REPO / "steps" / "step-003-fingerprinting" / "probes" / "evidence"
WORK_DIR = REPO / "backend" / "runs" / "probes"

# Each scenario, and the entries it bears on: the specific entries of matrices 1.1.0.
SCENARIOS = [
    {"scenario": "basicHttp-None-None",
     "support": "net10.0/basicHttpBinding/None/None", "platform": "net10.0/linux/basicHttpBinding/None/None"},
    {"scenario": "basicHttp-Transport-None",
     "support": "net10.0/basicHttpBinding/Transport/None", "platform": "net10.0/linux/basicHttpBinding/Transport/None"},
    {"scenario": "netTcp-Transport-None",
     "support": "net10.0/netTcpBinding/Transport/None", "platform": "net10.0/linux/netTcpBinding/Transport/None"},
    {"scenario": "netTcp-Transport-Certificate",
     "support": "net10.0/netTcpBinding/Transport/Certificate", "platform": "net10.0/linux/netTcpBinding/Transport/Certificate"},
    {"scenario": "wsHttp-TransportWithMessageCredential-Certificate",
     "support": "net10.0/wsHttpBinding/TransportWithMessageCredential/Certificate",
     "platform": "net10.0/linux/wsHttpBinding/TransportWithMessageCredential/Certificate"},
]

OPEN_ITEM = ("Probe it in the client's environment: from a Linux container holding a keytab for a test identity, call a "
             "non-production NetTcp service that uses Windows credentials. An onboarding task: it needs the client's identity "
             "team (a service principal name for the service, a keytab for the caller, the domain's krb5.conf).")

NOT_PROBED = [
    {"support": "net10.0/netTcpBinding/Transport/Windows", "platform": "net10.0/linux/netTcpBinding/*/Windows",
     "reason": "needs Kerberos: a Windows credential on NetTcp negotiates Kerberos on Linux, which needs a KDC, "
               "a service principal name and a keytab or ticket for the caller; no Kerberos environment is "
               "available to the probe, so the outcome is not guessed",
     "openItem": OPEN_ITEM},
]


def _run(command: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace", **kwargs)


def linux_container_runtime() -> str | None:
    """Why no Linux container runtime is available, or None when one is."""
    if shutil.which("docker") is None:
        return "docker is not installed"
    info = _run(["docker", "info", "--format", "{{.OSType}}"])
    if info.returncode != 0:
        return f"docker is not running: {info.stderr.strip()[:200]}"
    if info.stdout.strip() != "linux":
        return f"docker runs {info.stdout.strip()} containers, not linux"
    return None


def image_digest(image: str) -> str:
    """The image pinned by digest, pulled if missing: every probe names exactly what ran."""
    inspect = _run(["docker", "image", "inspect", image, "--format", "{{index .RepoDigests 0}}"])
    if inspect.returncode != 0:
        subprocess.run(["docker", "pull", image], check=True)
        inspect = _run(["docker", "image", "inspect", image, "--format", "{{index .RepoDigests 0}}"])
    return inspect.stdout.strip()


def wcf_client_package(project: Path = PROBE_PROJECT / "WcfClientProbe.csproj") -> str:
    """The WCF client package version the probe is built against, from its project file."""
    match = re.search(r'<PackageReference Include="System\.ServiceModel\.Primitives" Version="([^"]+)"',
                      project.read_text(encoding="utf-8"))
    if not match:
        raise SystemExit(f"{project.name} has no System.ServiceModel.Primitives package reference")
    return match.group(1)


def covers(result: dict, package: str, os_name: str) -> dict:
    """What a probe's evidence covers: the WCF client package version and the
    runtime it ran against. The assembly that ran must be that package's."""
    ran = (result.get("wcfClient") or "").split("+")[0] or None
    if ran and ran != package:
        raise SystemExit(f"the probe ran WCF client {ran}, but the project references {package}")
    return {"wcfClient": package, "runtime": (result.get("framework") or "").removeprefix(".NET ").strip() or None, "os": os_name}


def thumbprint(certificate: Path) -> str:
    """SHA-1 of a DER certificate: what the client pins."""
    return hashlib.sha1(certificate.read_bytes()).hexdigest().upper()


def publish(output: Path, pin_cryptography_xml: bool = True) -> Path:
    """Publish the probe client. The unpinned variant is built from a copy:
    two builds of one project directory share obj/."""
    project = PROBE_PROJECT
    if not pin_cryptography_xml:
        project = WORK_DIR / "variant-unpinned"
        shutil.rmtree(project, ignore_errors=True)
        project.mkdir(parents=True)
        for name in ("WcfClientProbe.csproj", "Program.cs"):
            shutil.copy2(PROBE_PROJECT / name, project / name)
    command = ["dotnet", "publish", str(project / "WcfClientProbe.csproj"), "-c", "Release", "-o", str(output), "--nologo",
               "-v", "quiet", f"-p:PinCryptographyXml={'true' if pin_cryptography_xml else 'false'}"]
    done = _run(command)
    if done.returncode != 0:
        raise SystemExit(f"publishing the probe failed:\n{done.stdout}\n{done.stderr}")
    return output


def make_certificates(build: Path, directory: Path) -> None:
    """The probe's certificates, as files only (WcfClientProbe make-certificates)."""
    done = _run(["dotnet", str(build / "WcfClientProbe.dll"), "make-certificates", str(directory)])
    if done.returncode != 0:
        raise SystemExit(f"making the certificates failed:\n{done.stdout}\n{done.stderr}")
    print(done.stdout.strip())


def _arguments(scenario: str, target: dict, certs: dict, pfx: str | None) -> list[str]:
    arguments = [scenario, target["address"]]
    if target.get("serverCertificate"):
        arguments += ["--server-thumbprint", certs["serverThumbprint"]]
    if pfx and target.get("clientCertificate"):
        arguments += ["--client-pfx", pfx, "--client-pfx-password-env", "PROBE_PFX_PASSWORD"]
    return arguments


def run_linux(build: Path, image: str, scenario: str, target: dict, certs: dict) -> tuple[list, dict]:
    """One probe in a Linux container. A service on this machine is addressed
    as localhost — the name its certificate carries — through the probe's TCP
    relay to host.docker.internal. The certificate folder is mounted read-only."""
    address = urlparse(target["address"])
    command = ["docker", "run", "--rm", "-v", f"{build}:/probe:ro"]
    if target.get("clientCertificate"):
        command += ["-v", f"{certs['directory']}:/certs:ro", "-e", "PROBE_PFX_PASSWORD"]
    command += [image, "dotnet", "/probe/WcfClientProbe.dll", *_arguments(scenario, target, certs, "/certs/client.pfx")]
    if address.hostname == "localhost":
        command += ["--relay", str(address.port)]
    return command, _result(command, certs["password"])


def run_windows(build: Path, scenario: str, target: dict, certs: dict) -> tuple[list, dict]:
    """The same client binary on the Windows host: the control that tells a
    Linux failure from a runtime one."""
    command = ["dotnet", str(build / "WcfClientProbe.dll"),
               *_arguments(scenario, target, certs, str(certs["directory"] / "client.pfx"))]
    return command, _result(command, certs["password"])


def _result(command: list[str], password: str) -> dict:
    env = {**os.environ, "PROBE_PFX_PASSWORD": password}
    done = _run(command, env=env, timeout=300)
    lines = [line for line in done.stdout.splitlines() if line.startswith("{")]
    if not lines:
        return {"outcome": "error", "error": f"the probe printed no result (exit {done.returncode})",
                "detail": (done.stdout + done.stderr)[-4000:]}
    return json.loads(lines[-1])


def _summary(result: dict) -> str:
    if result.get("outcome") == "passed":
        return f"{result.get('operation')} returned {result.get('response')!r}"
    return result.get("error") or "no result"


def write_evidence(stamp: str, scenario: str, where: str, record: dict) -> tuple[str, str]:
    """The evidence file is committed: this machine's repository path becomes
    <repo>, as no committed file carries a machine path."""
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    path = EVIDENCE_DIR / f"{stamp}-{scenario}-{where}.json"
    text = json.dumps(record, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    text = text.replace(json.dumps(str(REPO))[1:-1], "<repo>")
    path.write_text(text, encoding="utf-8", newline="\n")
    return path.relative_to(REPO).as_posix(), hashlib.sha256(text.encode("utf-8")).hexdigest()


def append_probes(kind: str, additions: dict[str, list[dict]]) -> None:
    """Append probe records to entries' ``probes`` lists. Nothing else in the
    matrix changes: not a verdict, not a confirmation."""
    path = wcf_matrix.path_of(kind)
    matrix = json.loads(path.read_text(encoding="utf-8"))
    ids = {e["id"] for e in matrix["entries"]}
    missing = sorted(set(additions) - ids)
    if missing:
        raise SystemExit(f"{path.name} has no entries {missing}")
    for entry in matrix["entries"]:
        for record in additions.get(entry["id"], []):
            if record["outcome"] == "not_probed" and any(p.get("outcome") == "not_probed" and p.get("reason") == record["reason"]
                                                         for p in entry.get("probes", [])):
                continue  # already recorded; a reason that has not changed is not new evidence
            entry.setdefault("probes", []).append(record)
    path.write_text(json.dumps(matrix, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Probe the WCF client matrix entries with a .NET 10 client in a Linux container.")
    parser.add_argument("--plan", required=True, help="the probe plan: the services' addresses and the certificate folder")
    parser.add_argument("--only", nargs="*", help="scenarios to run (default: every scenario the plan has a service for)")
    parser.add_argument("--no-controls", action="store_true", help="skip the controls that attribute a Linux failure")
    parser.add_argument("--make-certificates", action="store_true",
                        help="write new probe certificates to the plan's certificate folder first (files only)")
    options = parser.parse_args()

    plan_path = Path(options.plan).resolve()
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    why_not = linux_container_runtime()
    if why_not:
        print(f"No Linux container runtime is available on this machine ({why_not}). Nothing was probed or recorded.")
        sys.exit(2)

    build = publish(WORK_DIR / "WcfClientProbe")
    directory = (plan_path.parent / plan.get("certificates", "certs")).resolve()
    if options.make_certificates:
        make_certificates(build, directory)
    certs = {"directory": directory, "password": (directory / "pfx.password").read_text(encoding="utf-8").strip(),
             "serverThumbprint": thumbprint(directory / "server.cer")}
    image = image_digest(plan.get("image", "mcr.microsoft.com/dotnet/runtime:10.0"))
    package = wcf_client_package()
    now = datetime.now(timezone.utc)
    stamp, probed_on = now.strftime("%Y%m%dT%H%M%SZ"), now.strftime("%Y-%m-%d")
    additions: dict[str, dict[str, list]] = {"support": {}, "platform": {}}
    unpinned = None

    for scenario in SCENARIOS:
        name = scenario["scenario"]
        target = plan.get("scenarios", {}).get(name)
        if not target or (options.only and name not in options.only):
            continue
        command, result = run_linux(build, image, name, target, certs)
        evidence, sha = write_evidence(stamp, name, "linux", {
            "scenario": name, "where": "linux-container", "image": image, "service": target.get("service"),
            "serverThumbprint": certs["serverThumbprint"] if target.get("serverCertificate") else None,
            "command": command, "result": result})
        print(f"{name}: {result.get('outcome')} — {_summary(result)}")
        record = {
            "probedOn": probed_on, "scenario": name, "where": "linux-container", "outcome": result.get("outcome"),
            "summary": _summary(result), "service": target.get("service"), "address": target["address"],
            "covers": covers(result, package, "linux"),
            "client": {"image": image, "os": result.get("os"), "framework": result.get("framework"),
                       "wcfClient": result.get("wcfClient"), "cryptographyXml": result.get("cryptographyXml")},
            "certificates": "files (make-certificates); no certificate store",
            "evidence": evidence, "sha256": sha,
        }
        if result.get("outcome") != "passed" and not options.no_controls:
            unpinned = unpinned or publish(WORK_DIR / "WcfClientProbe-unpinned", pin_cryptography_xml=False)
            controls = []
            for where, (control_command, control) in (
                    ("linux-container-unpinned-cryptography-xml", run_linux(unpinned, image, name, target, certs)),
                    ("windows-host", run_windows(build, name, target, certs))):
                control_evidence, control_sha = write_evidence(stamp, name, where, {
                    "scenario": name, "where": where, "image": image if where.startswith("linux") else None,
                    "service": target.get("service"), "command": control_command, "result": control})
                print(f"  control {where}: {control.get('outcome')} — {_summary(control)}")
                controls.append({"where": where, "outcome": control.get("outcome"), "summary": _summary(control),
                                 "os": control.get("os"), "cryptographyXml": control.get("cryptographyXml"),
                                 "covers": covers(control, package, "windows" if where == "windows-host" else "linux"),
                                 "evidence": control_evidence, "sha256": control_sha})
            record["controls"] = controls
            # Linux fails, Windows passes with the same binary: the platform's failure, not the runtime's.
            windows = next(c for c in controls if c["where"] == "windows-host")
            record["attribution"] = "platform" if windows["outcome"] == "passed" else "undetermined"
        additions["support"].setdefault(scenario["support"], []).append(record)
        additions["platform"].setdefault(scenario["platform"], []).append(record)

    for item in NOT_PROBED:
        record = {"probedOn": probed_on, "outcome": "not_probed", "reason": item["reason"], "openItem": item["openItem"]}
        print(f"{item['support']}, {item['platform']}: not probed — needs Kerberos (open item: the client's identity team)")
        additions["support"].setdefault(item["support"], []).append(record)
        additions["platform"].setdefault(item["platform"], []).append(record)

    for kind in ("support", "platform"):
        append_probes(kind, additions[kind])
    print("Probe records appended. No verdict and no confirmation was changed: a person confirms each entry.")


if __name__ == "__main__":
    main()
