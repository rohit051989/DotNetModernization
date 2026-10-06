"""Writes signal-registry-1.8.0.json from 1.7.0.

1.8.0 (additive): step 4 (entry-point-inventory) becomes a signal producer,
like step 6. Its architecture signals say what a project exposes or hosts,
resolved across projects — a WCF service assembled from a contracts
project, an implementation project, a ServiceHost project and a folder of
.svc files with no project file is one service step 3 cannot see whole.
Run from this folder:  python make_signal_registry_1_8_0.py
"""
import json
from pathlib import Path

HERE = Path(__file__).parent
registry = json.loads((HERE / "signal-registry-1.7.0.json").read_text(encoding="utf-8"))
registry["registry_version"] = "1.8.0"

PRODUCER = "EntryPointInventory"
SOURCE = " Emitted by lifecycle step 4 (entry-point-inventory) from its resolved entry points, application origin only."


def signal(name, category, description, value):
    return {
        "name": name,
        "category": category,
        "type": "ENTRY_POINT",
        "description": description + SOURCE,
        "extractor": PRODUCER,
        "evidence_kind": "FILE",
        "value_semantics": value,
    }


registry["signals"] += [
    signal("EXPOSES_WCF_SERVICE", "ENTRY_POINT",
           "The project implements a WCF service contract — wherever the contract is declared and however the service is hosted.",
           "the service contract; one row per contract per implementing file, evidence the implementing class and its operations."),
    signal("WCF_SERVICE_HOSTING", "HOSTING_INDICATOR",
           "Where a service this project implements is hosted: a ServiceHost, an IIS .svc file or CoreWCF, in which project or folder "
           "(a folder of .svc files with no project file is named as such). On the implementing project.",
           "'<ServiceHost|IIS .svc|CoreWCF> in <project or folder>', or 'no host found'; one row per host per file."),
    signal("HOSTS_WCF_SERVICE", "HOSTING_INDICATOR",
           "The project constructs a ServiceHost (or CoreWCF host) for, or holds the .svc file of, a WCF service — the process "
           "the service runs in, not the code that implements it.",
           "the hosted service contract; one row per contract per hosting file, evidence the host construction or .svc file."),
    signal("EXPOSES_HTTP_API", "ENTRY_POINT",
           "The project exposes HTTP endpoints: MVC or Web API controller actions, or minimal APIs.",
           "the controller or handler type; one row per type per file."),
    signal("EXPOSES_ASMX_SERVICE", "ENTRY_POINT",
           "The project exposes an ASMX web service ([WebMethod] on a WebService).",
           "the service path (/Catalog/PicUploader.asmx); one row per service per file."),
    signal("EXPOSES_GRPC_SERVICE", "ENTRY_POINT",
           "The project implements a gRPC service (a generated Service.ServiceBase subclass).",
           "the gRPC service name; one row per service per file."),
    signal("EXPOSES_WEBFORMS_UI", "ENTRY_POINT",
           "The project serves Web Forms pages (.aspx with a code-behind Page class).",
           "the page path (/About.aspx); one row per page."),
]

out = HERE / "signal-registry-1.8.0.json"
out.write_text(json.dumps(registry, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
print(f"wrote {out.name}: {len(registry['signals'])} signals")
