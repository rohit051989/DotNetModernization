"""The deployment mechanisms a repository already has on OpenShift (36-COPILOT-ENHANCED-CONVERSION Part N).

A working mechanism is kept, never replaced, unless a decision says so. Conversion 2 of AccountsApi.Net10 replaced
the vault-init container in deploy/openshift/deployment-template.yaml with Vault Agent annotations, because nothing
told it the secrets were already delivered. The input generator reads this to choose `keep-existing-vault-delivery`
and to name the mechanism; the verifier reads it to count a vault reference the mechanism delivers as carried.

Vault delivery is recognised in any YAML file of the repository (manifests, templates, charts). Configuration
files (appsettings*.json) are never read here: they hold the references, not the delivery.

- `vault-init-container`: an init container whose name or image names vault (it writes the secrets before the
  application starts);
- `vault-agent-injector`: the `vault.hashicorp.com/agent-inject` annotations;
- `csi-secrets-store`: a SecretProviderClass with the vault provider;
- `external-secrets`: an ExternalSecret or SecretStore that reads from vault.

A secret is delivered when its name (the text after `vault:`) appears in a file that holds a mechanism, or in a
file that file's ConfigMap or annotations name: AccountsApi's mapping is a ConfigMap in the same template.
"""
import re
from dataclasses import dataclass, field
from pathlib import Path

SUFFIXES = (".yaml", ".yml")
SKIP_DIRS = {".git", "bin", "obj", "node_modules"}

MECHANISMS = (
    ("vault-init-container", re.compile(r"initContainers:(?:.|\n)*?(?:name|image):\s*[\"']?[^\n]*vault", re.I)),
    ("vault-agent-injector", re.compile(r"vault\.hashicorp\.com/agent-inject", re.I)),
    ("csi-secrets-store", re.compile(r"kind:\s*SecretProviderClass(?:.|\n)*?provider:\s*[\"']?vault", re.I)),
    ("external-secrets", re.compile(r"kind:\s*(?:ExternalSecret|ClusterSecretStore|SecretStore)\b(?:.|\n)*?vault", re.I)),
)
DESCRIPTIONS = {
    "vault-init-container": "an init container that writes the vault secrets before the application starts",
    "vault-agent-injector": "the Vault Agent injector annotations",
    "csi-secrets-store": "a CSI secrets store with the vault provider",
    "external-secrets": "an external-secrets sync from vault",
}


@dataclass
class VaultDelivery:
    file: str                       # repository-relative
    kind: str                       # one of MECHANISMS
    text: str = field(repr=False)   # the file's text, for the secret names it delivers

    @property
    def description(self) -> str:
        return DESCRIPTIONS[self.kind]

    def delivers(self, secret: str) -> bool:
        return re.search(rf"(^|[^A-Za-z0-9_.-]){re.escape(secret)}($|[^A-Za-z0-9_.-])", self.text) is not None


def vault_delivery(files: dict[str, str]) -> list[VaultDelivery]:
    """Every vault delivery mechanism in `files` ({repository path: text}), in path order."""
    found = []
    for path, text in sorted(files.items()):
        if not path.lower().endswith(SUFFIXES):
            continue
        for kind, pattern in MECHANISMS:
            if pattern.search(text):
                found.append(VaultDelivery(path, kind, text))
    return found


def read_tree(root: Path) -> dict[str, str]:
    """{repository path: text} for every YAML file under a working tree."""
    out = {}
    for f in sorted(root.rglob("*")):
        rel = f.relative_to(root)
        if f.is_file() and f.name.lower().endswith(SUFFIXES) and not SKIP_DIRS & set(rel.parts[:-1]):
            try:
                out[rel.as_posix()] = f.read_text(encoding="utf-8-sig", errors="replace")
            except OSError:
                continue
    return out


def read_commit(root: Path, commit: str, paths: list[str]) -> dict[str, str]:
    """{repository path: text} for the YAML files among `paths` at `commit` of the repository at `root`."""
    import subprocess

    out = {}
    for p in paths:
        if not p.lower().endswith(SUFFIXES) or SKIP_DIRS & set(p.split("/")[:-1]):
            continue
        done = subprocess.run(["git", "-C", str(root), "show", f"{commit}:{p}"], capture_output=True)
        if done.returncode == 0:
            out[p] = done.stdout.decode("utf-8-sig", errors="replace")
    return out
