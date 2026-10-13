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

**Where evidence lives** (C10, the probe evidence boundary). The platform ships
to each client as code, the matrices with it; each client's data lives only in
that client's database. A plan declares its owner: ``"platformSample": true``
for the platform's own sample services, or ``"engagement": "<id>"`` for a
client's environment, and a plan that declares neither is refused.

- platform samples: evidence files under probes/evidence/, shipped with the
  matrices, and probe records appended to the matrix entries — platform
  knowledge;
- a client engagement: the evidence goes to the database with the engagement
  (engagement_matrix.record_evidence), and nothing is written to a matrix file.
  The SOAP report applies the engagement's probes, and any confirmation a
  person makes on them (engagement_matrix.record_decision), on top of the
  shipped matrix.

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
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from app import models
from app.estate import engagement_matrix, wcf_matrix

REPO = Path(__file__).resolve().parents[3]
PROBE_PROJECT = REPO / "steps" / "step-003-fingerprinting" / "probes" / "WcfClientProbe"
EVIDENCE_DIR = REPO / "steps" / "step-003-fingerprinting" / "probes" / "evidence"
WORK_DIR = REPO / "backend" / "runs" / "probes"

PLATFORM_SAMPLE = "platform-sample"

# Each scenario, and the entries it bears on: the specific entries of matrices 1.1.0.
SCENARIOS = [
    {"scenario": "basicHttp-None-None",
     "support": "net10.0/basicHttpBinding/None/None", "platform": "net10.0/linux/basicHttpBinding/None/None"},
    {"scenario": "basicHttp-Transport-None",
     "support": "net10.0/basicHttpBinding/Transport/None", "platform": "net10.0/linux/basicHttpBinding/Transport/None"},
    # basicHttpsBinding: the same HTTPS service, called through the BasicHttpsBinding client type; with a
    # client certificate, against a TLS endpoint that requires and pins one. Both bear on the platform
    # matrix's one basicHttps entry, a wildcard.
    {"scenario": "basicHttps-Transport-None",
     "support": "net10.0/basicHttpsBinding/Transport/None", "platform": "net10.0/linux/basicHttpsBinding/*/*"},
    {"scenario": "basicHttps-Transport-Certificate",
     "support": "net10.0/basicHttpsBinding/Transport/Certificate", "platform": "net10.0/linux/basicHttpsBinding/*/*"},
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


def evidence_owner(plan: dict) -> str | None:
    """The engagement a plan's evidence belongs to, or None for the platform's
    own samples. A plan must say which: evidence never lands in the platform's
    source by default."""
    engagement, sample = plan.get("engagement"), plan.get("platformSample") is True
    if bool(engagement) == sample:
        raise SystemExit("the probe plan must declare its evidence owner: \"platformSample\": true for the platform's own "
                         "sample services, or \"engagement\": \"<id>\" for a client's environment — not both, not neither")
    return engagement or None


def write_evidence(stamp: str, scenario: str, where: str, record: dict) -> tuple[str, str]:
    """A platform sample's evidence file, shipped under probes/evidence/ with this
    machine's repository path as <repo>; returns its repository path and sha256.
    A client's evidence never comes here: it goes to the database
    (engagement_matrix.record_evidence)."""
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    path = EVIDENCE_DIR / f"{stamp}-{scenario}-{where}.json"
    text = json.dumps({**record, "source": PLATFORM_SAMPLE}, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    text = text.replace(json.dumps(str(REPO))[1:-1], "<repo>")
    path.write_text(text, encoding="utf-8", newline="\n")
    return path.relative_to(REPO).as_posix(), hashlib.sha256(text.encode("utf-8")).hexdigest()


class Evidence:
    """Where one run's evidence goes: the platform's evidence folder, or the engagement's rows in the database."""

    def __init__(self, engagement: str | None, stamp: str, probed_on: str):
        self.engagement, self.stamp, self.probed_on = engagement, stamp, probed_on
        self.db = None
        if engagement:
            from app.db import SessionLocal
            self.db = SessionLocal()
            if self.db.get(models.Engagement, engagement) is None:
                raise SystemExit(f"no engagement {engagement!r} in this deployment's database")

    def write(self, scenario: str, where: str, document: dict, result: dict, entries: list[str], package: str,
              attribution: str | None = None, control_of: str | None = None) -> tuple[str, str]:
        if not self.engagement:
            return write_evidence(self.stamp, scenario, where, document)
        evidence_id = f"{self.stamp}-{scenario}-{where}"
        sha = engagement_matrix.record_evidence(
            self.db, self.engagement, evidence_id, document, scenario=scenario, where=where,
            outcome=result.get("outcome") or "error", matrix_entries=entries,
            probed_on=date.fromisoformat(self.probed_on), error_type=_error_type(result), attribution=attribution,
            covers=covers(result, package, "windows" if where == "windows-host" else "linux"), control_of=control_of)
        return evidence_id, sha

    def close(self, commit: bool) -> None:
        if self.db is not None:
            if commit:
                self.db.commit()
            self.db.close()


def _error_type(result: dict) -> str | None:
    """The exception's type alone: its message may name the client's hosts."""
    if result.get("outcome") == "passed":
        return None
    return (result.get("error") or "").split(":", 1)[0].strip() or None


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
    engagement = evidence_owner(plan)
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

    evidence = Evidence(engagement, stamp, probed_on)
    done = False
    try:
        for scenario in SCENARIOS:
            name = scenario["scenario"]
            target = plan.get("scenarios", {}).get(name)
            if not target or (options.only and name not in options.only):
                continue
            entries = [scenario["support"], scenario["platform"]]
            command, result = run_linux(build, image, name, target, certs)
            document = {"scenario": name, "where": "linux-container", "image": image, "service": target.get("service"),
                        "serverThumbprint": certs["serverThumbprint"] if target.get("serverCertificate") else None,
                        "command": command, "result": result}
            print(f"{name}: {result.get('outcome')} — {_summary(result)}")
            controls, attribution = [], None
            if result.get("outcome") != "passed" and not options.no_controls:
                unpinned = unpinned or publish(WORK_DIR / "WcfClientProbe-unpinned", pin_cryptography_xml=False)
                for where, (control_command, control) in (
                        ("linux-container-unpinned-cryptography-xml", run_linux(unpinned, image, name, target, certs)),
                        ("windows-host", run_windows(build, name, target, certs))):
                    print(f"  control {where}: {control.get('outcome')} — {_summary(control)}")
                    controls.append((where, control_command, control))
                # Linux fails, Windows passes with the same binary: the platform's failure, not the runtime's.
                windows = next(c for w, _, c in controls if w == "windows-host")
                attribution = "platform" if windows.get("outcome") == "passed" else "undetermined"
            ref, sha = evidence.write(name, "linux", document, result, entries, package, attribution)
            control_records = []
            for where, control_command, control in controls:
                control_ref, control_sha = evidence.write(
                    name, where, {"scenario": name, "where": where, "image": image if where.startswith("linux") else None,
                                  "service": target.get("service"), "command": control_command, "result": control},
                    control, entries, package, control_of=f"{stamp}-{name}-linux")
                control_records.append({"where": where, "outcome": control.get("outcome"), "summary": _summary(control),
                                        "errorType": _error_type(control), "os": control.get("os"),
                                        "cryptographyXml": control.get("cryptographyXml"),
                                        "covers": covers(control, package, "windows" if where == "windows-host" else "linux"),
                                        "evidence": control_ref, "sha256": control_sha})
            if engagement:
                continue  # the engagement's rows are the record: nothing goes into a matrix file
            record = {
                "probedOn": probed_on, "scenario": name, "where": "linux-container", "outcome": result.get("outcome"),
                "summary": _summary(result), "errorType": _error_type(result), "service": target.get("service"),
                "address": target["address"], "covers": covers(result, package, "linux"),
                "client": {"image": image, "os": result.get("os"), "framework": result.get("framework"),
                           "wcfClient": result.get("wcfClient"), "cryptographyXml": result.get("cryptographyXml")},
                "certificates": "files (make-certificates); no certificate store",
                "source": PLATFORM_SAMPLE, "evidence": ref, "sha256": sha,
            }
            if control_records:
                record["controls"], record["attribution"] = control_records, attribution
            additions["support"].setdefault(scenario["support"], []).append(record)
            additions["platform"].setdefault(scenario["platform"], []).append(record)
        done = True
    finally:
        evidence.close(commit=done)

    if engagement:
        print(f"Evidence stored with engagement {engagement} in this deployment's database. No matrix file was changed: "
              f"a person confirms entries for this engagement on it (engagement_matrix.record_decision).")
        return

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


# ---------- the probe evidence boundary (C10) ----------

ENGAGEMENT_KEYS = {"engagement", "engagement_id", "engagementId"}


def _engagement_mentions(value, path: str = "") -> list[str]:
    """Every place a document attributes something to an engagement."""
    found = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key in ENGAGEMENT_KEYS and item:
                found.append(f"{path}.{key}={item}")
            found += _engagement_mentions(item, f"{path}.{key}")
    elif isinstance(value, list):
        for i, item in enumerate(value):
            found += _engagement_mentions(item, f"{path}[{i}]")
    return found


def evidence_boundary_violations(matrices: dict[str, dict], evidence_files: dict[str, dict]) -> list[str]:
    """Where a client's data has crossed into what the platform ships.

    - matrices (file name -> matrix) hold platform knowledge only: no probe
      attributed to an engagement or referencing an engagement's evidence, every
      probe a platform sample's with its evidence in the platform's folder, and
      every confirmation resting on that evidence alone;
    - evidence_files (repository path -> content), the platform's evidence
      folder: nothing attributed to an engagement, and every file a platform
      sample's that some matrix entry references."""
    platform_folder = EVIDENCE_DIR.relative_to(REPO).as_posix() + "/"
    problems, referenced = [], set()
    for name, matrix in matrices.items():
        for entry in matrix.get("entries", []):
            for probe in entry.get("probes", []):
                where = f"{name} {entry['id']} {probe.get('scenario') or probe.get('outcome')}"
                if probe.get("source") not in (None, PLATFORM_SAMPLE) or "evidenceRef" in probe:
                    problems.append(f"{where}: a client engagement's probe in a shipped matrix")
                for mention in _engagement_mentions(probe):
                    problems.append(f"{where}: attributed to an engagement ({mention})")
                for record in [probe, *probe.get("controls", [])]:
                    if record.get("evidence"):
                        referenced.add(record["evidence"])
                        if not record["evidence"].startswith(platform_folder):
                            problems.append(f"{where}: evidence {record['evidence']} is outside {platform_folder}")
            confirmation = entry.get("confirmation") or {}
            if confirmation.get("status") == "confirmed":
                for mention in _engagement_mentions(confirmation):
                    problems.append(f"{name} {entry['id']}: a client's confirmation in a shipped matrix ({mention})")
                for path in confirmation.get("evidence") or []:
                    if not path.startswith(platform_folder):
                        problems.append(f"{name} {entry['id']}: confirmed on evidence outside {platform_folder}: {path}")
        for decision in matrix.get("decisions", []):
            for mention in _engagement_mentions(decision):
                problems.append(f"{name} decision {decision.get('id')}: attributed to an engagement ({mention})")
    for path, content in evidence_files.items():
        for mention in _engagement_mentions(content):
            problems.append(f"{path}: platform evidence attributed to an engagement ({mention})")
        if content.get("source") not in (None, PLATFORM_SAMPLE):
            problems.append(f"{path}: source {content.get('source')!r} is not the platform's samples")
        if path not in referenced:
            problems.append(f"{path}: no matrix entry references it as a platform sample's evidence")
    return problems


def platform_files() -> tuple[dict[str, dict], dict[str, dict]]:
    """Every matrix file, and every file in the platform's evidence folder."""
    matrices = {p.name: json.loads(p.read_text(encoding="utf-8")) for p in sorted(wcf_matrix.MATRIX_DIR.glob("wcf-client-*-*.json"))}
    evidence = {p.relative_to(REPO).as_posix(): json.loads(p.read_text(encoding="utf-8"))
                for p in sorted(EVIDENCE_DIR.glob("*"))}
    return matrices, evidence
