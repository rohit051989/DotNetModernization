"""Writes signal-registry-1.13.0.json from 1.12.0.

1.13.0 (additive), the binding a WCF service is exposed on:
- WCF_SERVICE_BINDING_CONFIG (ConfigurationExtractor): the binding of an <endpoint> under system.serviceModel/services,
  the service-side counterpart of WCF_CLIENT_BINDING_CONFIG.
- WCF_SERVICE_BINDING_USAGE (ApiUsageExtractor): a WCF binding constructed in a file that hosts a service (ServiceHost,
  AddServiceEndpoint, CoreWCF's service builder), the service-side counterpart of WCF_CLIENT_BINDING_USAGE.
WCF_CLIENT_BINDING_USAGE also recognises NetMsmqBinding, MsmqIntegrationBinding and NetPeerTcpBinding, and a
CustomBinding's non-HTTP transport element (System.ServiceModel.Channels.TcpTransportBindingElement ...).
A client or service endpoint on a <customBinding> with a non-HTTP transport records customBinding:<transport>
(customBinding:tcpTransport ...) instead of customBinding, and a <service> with no endpoint of its own records the
binding of each non-HTTP default endpoint (its net.tcp/net.pipe/net.msmq base address through <protocolMapping>).
Run from this folder:  python make_signal_registry_1_13_0.py
"""
import json
from pathlib import Path

HERE = Path(__file__).parent
registry = json.loads((HERE / "signal-registry-1.12.0.json").read_text(encoding="utf-8"))
registry["registry_version"] = "1.13.0"

for entry in registry["signals"]:
    if entry["name"] == "WCF_CLIENT_BINDING_USAGE":
        entry["description"] = entry["description"].replace(
            "(new NetTcpBinding(), new BasicHttpBinding() ...)",
            "(new NetTcpBinding(), new BasicHttpBinding(), new NetNamedPipeBinding(), new NetMsmqBinding() ..., or a "
            "CustomBinding's non-HTTP transport: new TcpTransportBindingElement() ...)")
        entry["value_semantics"] = entry["value_semantics"].replace(
            "e.g. System.ServiceModel.NetTcpBinding;",
            "e.g. System.ServiceModel.NetTcpBinding, or System.ServiceModel.Channels.TcpTransportBindingElement for a "
            "CustomBinding's transport;")
    if entry["name"] == "WCF_CLIENT_BINDING_CONFIG":
        entry["value_semantics"] = entry["value_semantics"].replace(
            "the binding type, e.g. netTcpBinding;",
            "the binding type, e.g. netTcpBinding; customBinding:<transport> (customBinding:tcpTransport, "
            "customBinding:namedPipeTransport, customBinding:msmqTransport ...) for a customBinding built on a non-HTTP "
            "transport;")

registry["signals"] += [
    {
        "name": "WCF_SERVICE_BINDING_CONFIG",
        "category": "ENDPOINT_INDICATOR",
        "type": "CONFIG_ELEMENT",
        "description": "The binding type of an <endpoint> under system.serviceModel/services: the binding this code exposes a "
                       "WCF service on. The service-side counterpart of WCF_CLIENT_BINDING_CONFIG. A <service> with no "
                       "<endpoint> of its own gets WCF 4 default endpoints: each net.tcp, net.pipe or net.msmq base address "
                       "records the binding <protocolMapping> gives its scheme (netTcpBinding, netNamedPipeBinding, "
                       "netMsmqBinding by default).",
        "extractor": "ConfigurationExtractor",
        "evidence_kind": "FILE",
        "value_semantics": "the binding type, e.g. netTcpBinding; customBinding:<transport> (customBinding:tcpTransport ...) "
                           "for a customBinding built on a non-HTTP transport; one row per distinct binding per file.",
    },
    {
        "name": "WCF_SERVICE_BINDING_USAGE",
        "category": "ENDPOINT_INDICATOR",
        "type": "API_INVOCATION",
        "description": "A WCF binding constructed in code that hosts a service: only in a file that mentions ServiceHost or "
                       "AddServiceEndpoint (System.ServiceModel self-hosting, or CoreWCF's "
                       "serviceBuilder.AddServiceEndpoint<TService, TContract>(binding, path)). The service-side counterpart "
                       "of WCF_CLIENT_BINDING_USAGE.",
        "extractor": "ApiUsageExtractor",
        "evidence_kind": "FILE",
        "value_semantics": "the fully qualified binding type, e.g. System.ServiceModel.NetTcpBinding or CoreWCF.NetTcpBinding, "
                           "or a CustomBinding's non-HTTP transport, e.g. CoreWCF.Channels.TcpTransportBindingElement; "
                           "one row per distinct binding per file. Syntax-only: confidence 0.8.",
    },
]

out = HERE / "signal-registry-1.13.0.json"
out.write_text(json.dumps(registry, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
print(f"wrote {out.name}: {len(registry['signals'])} signals")
