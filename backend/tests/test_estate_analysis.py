"""dependency-and-context-map's analysis — 31-DEPENDENCY-AND-CONTEXT-MAP.md. Pure
functions over plain rows, so no database: each test builds the rows it needs."""

import json
import unittest
import uuid

from app.estate import analysis

R_WCF, R_SHOP, R_PAY = uuid.UUID(int=1), uuid.UUID(int=2), uuid.UUID(int=3)
SLUG = {R_WCF: "wcf", R_SHOP: "shop", R_PAY: "pay"}


def call(cid, repo, project, mechanism="soap_client", host="localhost", port=None, path=None, contract=None, binding=None,
         verdict="compatible", usage="used", credential=None, placeholder=None, envs=None):
    return {
        "id": cid, "repository_id": repo, "repository_slug": SLUG[repo], "project_id": f"{SLUG[repo]}-{project}",
        "project_path": f"src/{project}/{project}.csproj", "mechanism": mechanism, "usage": usage, "scheme": "net.tcp",
        "host": host, "port": port, "path": path, "resolution": "resolved" if host else "unresolved", "placeholder": placeholder,
        "linux_verdict": verdict, "linux_reasons": [],
        "detail": {"block": {"contract": contract, "binding": binding, "clientCredentialType": credential}},
        "environment_bindings": envs or [],
    }


def wcf_operation(eid, repo, project, contract, addresses):
    return {
        "id": eid, "repository_id": repo, "repository_slug": SLUG[repo], "project_id": f"{SLUG[repo]}-{project}",
        "project_path": f"src/{project}/{project}.csproj", "kind": "wcf_operation", "origin": "application",
        "handler_type": contract[1:], "handler_member": "Op",
        "detail": {"contract": contract, "endpoints": [{"address": a, "binding": "netTcpBinding"} for a in addresses]},
    }


def asmx_method(eid, repo, project, service_path, method):
    return {
        "id": eid, "repository_id": repo, "repository_slug": SLUG[repo], "project_id": f"{SLUG[repo]}-{project}",
        "project_path": f"src/{project}/{project}.csproj", "kind": "asmx_web_method", "origin": "application",
        "handler_type": "FundsTransferWS", "handler_member": method, "detail": {"servicePath": service_path, "method": method},
    }


# Platform matrix entries, as outbound-invocation-inventory records them on an environment binding.
PIPE, TCP, TCP_WINDOWS = ("net10.0/linux/netNamedPipeBinding/*/*", "net10.0/linux/netTcpBinding/*/*",
                          "net10.0/linux/netTcpBinding/*/Windows")


def platform_env(entry, environment="PROD"):
    return {"environment": environment, "platformMatrixEntry": entry}


def http_route(eid, repo, project, route):
    return {
        "id": eid, "repository_id": repo, "repository_slug": SLUG[repo], "project_id": f"{SLUG[repo]}-{project}",
        "project_path": f"src/{project}/{project}.csproj", "kind": "http_minimal_api", "origin": "application",
        "handler_type": "Endpoint", "handler_member": None, "detail": {"routeTemplate": route, "mappedTemplate": route},
    }


class RegisterTests(unittest.TestCase):
    def test_a_service_the_estate_serves_is_internal_and_linked_to_its_entry_point(self):
        """The WCF sample: the TestClient calls services its own repository hosts."""
        calls = [
            call("c1", R_WCF, "TestClient", port=8101, path="/Utility", contract="IUtilityService", binding="netTcpBinding", verdict="incompatible"),
            call("c2", R_WCF, "TestClient", port=8443, path="/Utility", contract="IUtilityService", binding="basicHttpBinding"),
        ]
        eps = [wcf_operation("ep-b", R_WCF, "Services", "IUtilityService", ["net.tcp://localhost:{port}/Utility", "https://localhost:{port}/Utility"]),
               wcf_operation("ep-a", R_WCF, "Services", "IUtilityService", ["net.tcp://localhost:{port}/Utility"])]
        register = analysis.build_register(calls, eps)
        host = register["hosts"][0]
        # NetTcp itself works from Linux: nothing in the platform matrix asks its owner to change.
        self.assertEqual((host["host"], host["classification"], host["requiresBackendChange"]), ("localhost@wcf", "internal", False))
        service = host["services"][0]
        self.assertEqual(service["ports"], [8101, 8443])
        target = service["internalTargets"][0]
        # Linked to the lowest entry point id of the contract: stable across rescans.
        self.assertEqual((target["entryPointId"], target["sameRepository"]), ("ep-a", True))

    def test_one_real_host_is_one_conversation_whatever_the_port(self):
        calls = [
            call("c1", R_SHOP, "Web", host="WSSE0.bank.example.", port=443, path="/AccountService.svc", contract="IAccountService"),
            call("c2", R_PAY, "Api", host="wsse0.bank.example", port=8443, path="/PaymentService.svc", contract="IPaymentService"),
        ]
        register = analysis.build_register(calls, [])
        self.assertEqual(len(register["hosts"]), 1)
        host = register["hosts"][0]
        self.assertEqual((host["host"], host["classification"], host["callingRepositoryCount"], host["ports"]),
                         ("wsse0.bank.example", "external", 2, [443, 8443]))
        self.assertEqual([s["path"] for s in host["services"]], ["/accountservice.svc", "/paymentservice.svc"])

    def test_what_the_owner_must_change_comes_from_the_platform_matrix_entry(self):
        """Who changes what is the platform matrix entry's fix, keyed by
        credential: named pipes need the owner; NetTcp with a Windows
        credential is Kerberos on our side or another credential on theirs,
        not yet known which; NetTcp with a certificate needs nobody."""
        pipe = call("c1", R_SHOP, "Web", host="svc.example", binding="netNamedPipeBinding", envs=[platform_env(PIPE)])
        kerberos = call("c2", R_SHOP, "Web", host="tcp.example", binding="netTcpBinding", credential="Windows",
                        envs=[platform_env(TCP_WINDOWS)])
        tcp = call("c3", R_SHOP, "Web", host="other.example", binding="netTcpBinding", credential="Certificate", envs=[platform_env(TCP)])
        self.assertTrue(analysis.backend_change_reasons(pipe))
        self.assertEqual(analysis.backend_change_reasons(kerberos), [])
        self.assertIn("Kerberos configuration on our side", analysis.possible_backend_change_reasons(kerberos)[0])
        self.assertEqual((analysis.backend_change_reasons(tcp), analysis.possible_backend_change_reasons(tcp)), ([], []))
        register = analysis.build_register([pipe, kerberos, tcp], [])
        by_host = {h["host"]: h for h in register["hosts"]}
        self.assertTrue(by_host["svc.example"]["requiresBackendChange"])
        self.assertEqual((by_host["tcp.example"]["requiresBackendChange"], len(by_host["tcp.example"]["possibleBackendChangeReasons"])),
                         (False, 1))
        self.assertFalse(by_host["other.example"]["requiresBackendChange"])
        # Backend change sorts first.
        self.assertEqual(register["hosts"][0]["host"], "svc.example")

    def test_a_platform_entry_a_probe_contradicts_is_under_review_not_a_backend_change(self):
        """Until a reviewer revises it, a contradicted entry's verdict is not a
        verdict and its fix is not a change anyone is asked to make: the host
        lists it under review, counted apart."""
        from unittest import mock
        from app.estate import wcf_matrix
        pipe_entry = {"id": PIPE, "verdict": "incompatible", "fix": {"who": "backend_owner", "change": "offer another binding"},
                      "probes": [{"probedOn": "2026-10-12", "scenario": "pipe", "outcome": "passed"}]}
        envs = [{**platform_env(PIPE), "linuxVerdict": "incompatible"}]
        pipe = call("c1", R_SHOP, "Web", host="svc.example", binding="netNamedPipeBinding", verdict="incompatible", envs=envs)
        with mock.patch.object(wcf_matrix, "entries", lambda kind, version=None: {PIPE: pipe_entry}):
            self.assertEqual([], analysis.backend_change_reasons(pipe))
            host = analysis.build_register([pipe], [])["hosts"][0]
        self.assertEqual((False, [PIPE], None, {"PROD": "under_review"}),
                         (host["requiresBackendChange"], host["underReview"], host["worstVerdict"], host["verdictByEnvironment"]))

    def test_backend_change_is_split_by_who_owns_the_service(self):
        """C2: an internal host's change is a service inside this migration;
        an external host's is another team's — worded differently."""
        internal = call("c1", R_WCF, "TestClient", port=8101, path="/Utility", contract="IUtilityService", binding="netNamedPipeBinding",
                        envs=[platform_env(PIPE)])
        external = call("c2", R_SHOP, "Web", host="svc.bank.example", path="/Pay.svc", contract="IPay", binding="netNamedPipeBinding",
                        envs=[platform_env(PIPE)])
        eps = [wcf_operation("ep", R_WCF, "Services", "IUtilityService", ["net.tcp://localhost:{port}/Utility"])]
        rows = {h["host"]: h for h in analysis.build_register([internal, external], eps)["hosts"]}

        ours, theirs = rows["localhost@wcf"], rows["svc.bank.example"]
        self.assertEqual((ours["requiresBackendChange"], ours["backendChangeOwner"]), (True, analysis.THIS_MIGRATION))
        self.assertEqual((theirs["requiresBackendChange"], theirs["backendChangeOwner"]), (True, analysis.ANOTHER_TEAM))
        self.assertIn("inside this migration", ours["backendChangeReasons"][0])
        self.assertIn("another team owns the service", theirs["backendChangeReasons"][0])
        self.assertEqual(ours["services"][0]["backendChangeOwner"], analysis.THIS_MIGRATION)

    def test_a_soap_caller_matches_an_asmx_service_by_path_and_web_methods(self):
        """wcf calls FundsTransferWS through a generated proxy; wcf-backend
        serves it as an .asmx. No WCF contract to match: the .asmx path (the
        application may sit in a virtual directory) and every web method the
        call invokes, Async suffix and all, must be the service's."""
        eps = [asmx_method("ep-2", R_PAY, "FundsTransferWS", "/FundsTransferWS.asmx", "Ping"),
               asmx_method("ep-1", R_PAY, "FundsTransferWS", "/FundsTransferWS.asmx", "Transfer")]
        funds = {**call("c1", R_WCF, "Services", host="ftmt.corp.example.com", path="/FundsTransferWS/FundsTransferWS.asmx",
                        contract="FundsTransferWSSoap", binding="basicHttpBinding"),
                 "operations": [{"operation": "TransferAsync"}, {"operation": "Ping"}]}
        servers, how = analysis.match_servers(funds, analysis.build_servers(eps))
        self.assertEqual(([s["repository_slug"] for s in servers], how), (["pay"], "ASMX service path and web methods"))
        self.assertEqual(servers[0]["entry_point_id"], "ep-1")

        # A real host name, yet a service in the estate: internal, linked to the ASMX entry point.
        host = analysis.build_register([funds], eps)["hosts"][0]
        target = host["services"][0]["internalTargets"][0]
        self.assertEqual((host["host"], host["classification"]), ("ftmt.corp.example.com", "internal"))
        self.assertEqual((target["repositorySlug"], target["entryPointId"], target["served"]), ("pay", "ep-1", "/fundstransferws.asmx"))

        # A method the service does not have: not this service.
        unknown = {**funds, "operations": [{"operation": "Refund"}]}
        self.assertEqual(analysis.match_servers(unknown, analysis.build_servers(eps)), ([], None))
        # Another .asmx whose name merely ends the same way: not this service.
        other = {**funds, "path": "/OtherFundsTransferWS.asmx"}
        self.assertEqual(analysis.match_servers(other, analysis.build_servers(eps)), ([], None))

    def test_asmx_paths_allow_a_virtual_directory(self):
        self.assertTrue(analysis.asmx_path_matches("/fundstransferws/fundstransferws.asmx", "/FundsTransferWS.asmx"))
        self.assertTrue(analysis.asmx_path_matches("/FundsTransferWS.asmx/", "FundsTransferWS.asmx"))
        self.assertFalse(analysis.asmx_path_matches("/otherfundstransferws.asmx", "/fundstransferws.asmx"))
        self.assertFalse(analysis.asmx_path_matches(None, "/fundstransferws.asmx"))

    def test_unused_clients_are_excluded_and_unresolved_endpoints_listed_apart(self):
        calls = [
            call("c1", R_SHOP, "Web", host=None, placeholder="config:API_URL", mechanism="http_client"),
            call("c2", R_SHOP, "Web", host="dead.example", usage="unused"),
            call("c3", R_SHOP, "Web", host="live.example"),
        ]
        register = analysis.build_register(calls, [])
        self.assertEqual([h["host"] for h in register["hosts"]], ["live.example"])
        self.assertEqual(register["unusedExcluded"], 1)
        self.assertEqual([u["placeholder"] for u in register["unresolved"]], ["config:API_URL"])

    def test_http_routes_match_only_local_addresses_and_a_matched_port_carries_its_server(self):
        eps = [http_route("e1", R_SHOP, "PublicApi", "api/catalog-items/{id}"), http_route("e2", R_SHOP, "PublicApi", "api/brands")]
        calls = [
            call("c1", R_SHOP, "Web", mechanism="http_client", port=5099, path="/api/catalog-items/7"),
            call("c2", R_SHOP, "Admin", mechanism="http_client", port=5099, path="/unknown/route"),
            call("c3", R_SHOP, "Web", mechanism="http_client", host="api.partner.example", path="/api/brands"),
        ]
        register = analysis.build_register(calls, eps)
        by_host = {h["host"]: h for h in register["hosts"]}
        self.assertEqual(by_host["localhost@shop"]["classification"], "internal")
        # c2 matched no route, but its port is the one c1 resolved to PublicApi.
        self.assertEqual(by_host["localhost@shop"]["callingProjectCount"], 2)
        # A real host with a familiar path is still someone else's.
        self.assertEqual(by_host["api.partner.example"]["classification"], "external")

    def test_an_unmatched_local_address_is_grouped_by_port_not_into_one_localhost(self):
        calls = [call("c1", R_SHOP, "Web", mechanism="database", port=5433), call("c2", R_PAY, "Api", mechanism="http_client", port=44315)]
        self.assertEqual(sorted(h["host"] for h in analysis.build_register(calls, [])["hosts"]), ["localhost:44315", "localhost:5433"])

    def test_verdict_by_environment_takes_the_worst_per_environment(self):
        envs = [{"environment": "Production", "linuxVerdict": "incompatible"}, {"environment": "Docker", "linuxVerdict": "compatible"}]
        host = analysis.build_register([call("c1", R_SHOP, "Web", host="db.example", mechanism="database", envs=envs)], [])["hosts"][0]
        self.assertEqual(host["verdictByEnvironment"], {"Docker": "compatible", "Production": "incompatible"})


class PackageEstateTests(unittest.TestCase):
    def use(self, repo, project, package, version, outcome="upgrade_safe", **flags):
        return {"repository_slug": repo, "project_path": project, "package_id": package, "current_version": version,
                "recommended_version": "13.0.4", "outcome": outcome, "breaking_members": flags.pop("members", []), **flags}

    def test_sorted_by_repository_count_with_estate_and_cross_repository_drift(self):
        rows = analysis.build_package_estate([
            self.use("a", "A.csproj", "Newtonsoft.Json", "12.0.1"),
            self.use("b", "B.csproj", "newtonsoft.json", "13.0.2"),
            self.use("a", "A.csproj", "Serilog", "2.0.0"), self.use("a", "A2.csproj", "Serilog", "2.1.0"),
            self.use("a", "A.csproj", "Polly", "7.0.0"), self.use("b", "B.csproj", "Polly", "7.0.0"),
        ])
        by_id = {r["packageId"]: r for r in rows}
        self.assertEqual(rows[0]["repositoryCount"], 2)
        self.assertEqual((by_id["Newtonsoft.Json"]["estateDrift"], by_id["Newtonsoft.Json"]["crossRepositoryDrift"]), (True, True))
        # Two versions inside one repository: estate drift, but no repository disagrees with another.
        self.assertEqual((by_id["Serilog"]["estateDrift"], by_id["Serilog"]["crossRepositoryDrift"]), (True, False))
        self.assertEqual((by_id["Polly"]["estateDrift"], by_id["Polly"]["crossRepositoryDrift"]), (False, False))
        self.assertEqual(by_id["Newtonsoft.Json"]["versionsInUse"], {"12.0.1": 1, "13.0.2": 1})

    def test_breaking_members_are_the_union_across_uses(self):
        m1 = {"type": "T", "member": "A", "change": "member_removed"}
        m2 = {"type": "T", "member": "B", "change": "signature_changed"}
        row = analysis.build_package_estate([
            self.use("a", "A.csproj", "Lib", "1.0", outcome="upgrade_breaking", members=[m1]),
            self.use("b", "B.csproj", "Lib", "1.0", outcome="upgrade_breaking", members=[m1, m2]),
        ])[0]
        self.assertEqual(row["breakingMembers"], [m1, m2])
        self.assertEqual(row["outcomes"], {"upgrade_breaking": 2})


class GraphTests(unittest.TestCase):
    def project(self, pid, repo, name):
        return {"id": pid, "repository_id": repo, "repository_slug": SLUG[repo], "relative_path": f"src/{name}/{name}.csproj",
                "name": name, "assembly_name": name, "root_namespace": name}

    def test_a_package_naming_another_repositorys_project_is_a_cross_repository_edge_and_shared_library(self):
        projects = [self.project("common", R_WCF, "Rbc.Common"), self.project("web", R_SHOP, "Web"), self.project("api", R_PAY, "Api")]
        packages = [{"project_id": "web", "package_name": "rbc.common"}, {"project_id": "api", "package_name": "Rbc.Common"}]
        graph = analysis.build_graph(projects, [], packages, client_feed_packages={"rbc.common"})
        self.assertEqual([(e["from"], e["to"], e["kind"], e["crossRepository"], e["clientFeed"]) for e in graph["edges"]],
                         [("api", "common", "internal_package", True, True), ("web", "common", "internal_package", True, True)])
        self.assertEqual([(s["projectId"], s["consumerRepositoryCount"]) for s in graph["sharedLibraries"]], [("common", 2)])

    def test_cycles_are_found_and_marked_cross_repository(self):
        projects = [self.project("a", R_WCF, "A"), self.project("b", R_SHOP, "B"), self.project("c", R_SHOP, "C")]
        references = [{"source_project_id": "b", "referenced_project_id": "c"}]
        packages = [{"project_id": "a", "package_name": "B"}, {"project_id": "c", "package_name": "A"}]
        graph = analysis.build_graph(projects, references, packages, set())
        self.assertEqual([(c["members"], c["crossRepository"]) for c in graph["cycles"]], [(["a", "b", "c"], True)])

    def test_a_framework_entry_point_declared_in_another_repository_is_reconciled(self):
        projects = [self.project("common", R_WCF, "Rbc.Common")]
        eps = [{"id": "ep1", "repository_id": R_SHOP, "origin": "framework", "handler_type": "Rbc.Common.Web.AuditModule"},
               {"id": "ep2", "repository_id": R_SHOP, "origin": "framework", "handler_type": "System.Web.Handlers.Transfer"}]
        out = analysis.reconcile_origins(eps, projects)
        self.assertEqual([(r["entryPointId"], r["reconciledOrigin"]) for r in out], [("ep1", "application")])


class ContextMapTests(unittest.TestCase):
    def test_dsl_names_external_hosts_and_is_deterministic(self):
        calls = [call("c1", R_SHOP, "Web", host="wsse0.bank.example", binding="netTcpBinding", verdict="incompatible"),
                 call("c2", R_PAY, "Api", host="wsse0.bank.example", binding="netTcpBinding")]
        hosts = analysis.build_register(calls, [])["hosts"]
        first = analysis.build_context_map('Client "A"', ["shop", "pay"], hosts)
        second = analysis.build_context_map('Client "A"', ["pay", "shop"], list(reversed(hosts)))
        self.assertEqual(first, second)
        dsl = first["dsl"]
        self.assertIn('softwareSystem "wsse0.bank.example" "External"', dsl)
        self.assertIn('"Backend change"', dsl)
        self.assertIn('group "Client \\"A\\" estate"', dsl)
        self.assertEqual(dsl.count("{"), dsl.count("}"))
        self.assertEqual(sum(1 for r in first["relationships"] if r["to"].startswith("ext_")), 2)

    def test_register_is_deterministic_whatever_the_input_order(self):
        calls = [call(f"c{i}", R_SHOP if i % 2 else R_PAY, f"P{i}", host=f"h{i % 3}.example", port=i) for i in range(9)]
        a = analysis.build_register(calls, [])
        b = analysis.build_register(list(reversed(calls)), [])
        self.assertEqual(json.dumps(a, sort_keys=True, default=str), json.dumps(b, sort_keys=True, default=str))


def binding(environment, source_file, host, port=443):
    """One environment_bindings entry as step 5 writes it."""
    return {"environment": environment, "sourceFile": source_file, "keyPath": "Services:Orders", "scheme": "https",
            "host": host, "port": port, "path": "/api/orders", "resolution": "resolved", "linuxVerdict": "compatible"}


class ProductionGroupingTests(unittest.TestCase):
    """C1: one service, one row — whichever host each environment file names."""

    def calls(self):
        # Two environment files in shop point the one Orders service at
        # different hosts; pay's default file names its test host.
        shop = call("c1", R_SHOP, "Web", mechanism="http_client", host="orders-dev.corp.example", path="/api/orders",
                    envs=[binding("Development", "src/Web/appsettings.Development.json", "orders-dev.corp.example"),
                          binding("Production", "src/Web/appsettings.Production.json", "orders.corp.example")])
        pay = call("c2", R_PAY, "Api", mechanism="http_client", host="orders-test.corp.example", path="/api/orders",
                   envs=[binding("default", "src/Api/appsettings.json", "orders-test.corp.example"),
                         binding("Production", "src/Api/appsettings.Production.json", "ORDERS.corp.example")])
        return [shop, pay]

    def test_grouped_by_the_production_host_with_other_environments_beneath(self):
        register = analysis.build_register(self.calls(), [], production_environment="Production")
        host = analysis.build_register(self.calls(), [], production_environment="production")["hosts"][0]
        self.assertEqual(len(register["hosts"]), 1)
        row = register["hosts"][0]
        self.assertEqual({**row, "productionEnvironment": None}, {**host, "productionEnvironment": None})  # the setting's case does not matter
        self.assertEqual((row["host"], row["groupedBy"], row["groupingNote"], row["callingRepositoryCount"]),
                         ("orders.corp.example", "production_environment", None, 2))
        self.assertEqual(row["otherHosts"], [{"host": "orders-dev.corp.example", "environments": ["Development"]},
                                             {"host": "orders-test.corp.example", "environments": ["default"]}])

    def test_without_the_setting_the_raw_hosts_split_the_service_and_each_row_says_so(self):
        rows = analysis.build_register(self.calls(), [])["hosts"]
        self.assertEqual(sorted(r["host"] for r in rows), ["orders-dev.corp.example", "orders-test.corp.example"])
        self.assertTrue(all(r["groupedBy"] == "host" and "No production environment" in r["groupingNote"] for r in rows))

    def test_an_annotated_raw_host_is_carried_to_the_production_row_that_took_its_calls(self):
        """C4: setting a production environment must not orphan a conversation record."""
        as_found = analysis.build_register(self.calls(), [])
        grouped = analysis.build_register(self.calls(), [], production_environment="Production")
        carried = analysis.carry_annotations(grouped, as_found, ["orders-dev.corp.example", "orders.corp.example", "gone.example"])
        # orders-dev's calls moved to orders.corp; orders.corp is itself a row; gone.example was never called.
        self.assertEqual(carried, {"orders-dev.corp.example": ["orders.corp.example"]})
        # Without the setting nothing moves, so nothing is carried.
        self.assertEqual(analysis.carry_annotations(as_found, as_found, ["orders-dev.corp.example"]), {})

    def test_a_call_with_no_production_binding_falls_back_to_its_host_and_the_row_says_so(self):
        lonely = call("c3", R_WCF, "Client", mechanism="http_client", host="legacy.corp.example", path="/x",
                      envs=[binding("Development", "src/Client/appsettings.Development.json", "legacy.corp.example")])
        rows = {r["host"]: r for r in analysis.build_register(self.calls() + [lonely], [], production_environment="Production")["hosts"]}
        self.assertEqual(rows["legacy.corp.example"]["groupedBy"], "host")
        self.assertEqual(rows["legacy.corp.example"]["groupingNote"], "No 'Production' binding: grouped by the host as found.")
        self.assertEqual(rows["orders.corp.example"]["groupedBy"], "production_environment")


def op(operation=None, verb=None, path=None, resolution="resolved", line=10, reason=None):
    return {"operation": operation, "verb": verb, "path": path, "member": operation, "resolution": resolution, "reason": reason,
            "callSite": {"filePath": "src/Client/Program.cs", "lineStart": line, "lineEnd": line}}


def wcf_op(eid, repo, project, contract, operation, address):
    ep = wcf_operation(eid, repo, project, contract, [address])
    ep["detail"]["operation"] = operation
    ep["handler_member"] = operation
    return ep


def http_action(eid, repo, project, verb, route):
    ep = http_route(eid, repo, project, route)
    ep["detail"]["verb"] = verb
    return ep


class IntegrationTests(unittest.TestCase):
    def test_soap_operations_match_by_contract_and_operation_and_same_repository_is_flagged(self):
        """The WCF TestClient: Ping and GetServerTimeUtc on the Utility channel."""
        client = call("c1", R_WCF, "TestClient", port=8101, path="/Utility", contract="IUtilityService", binding="netTcpBinding")
        client["operations"] = [op("Ping", line=12), op("GetServerTimeUtc", line=13), op("Shutdown", line=14)]
        eps = [wcf_op("ep-ping", R_WCF, "Services", "IUtilityService", "Ping", "net.tcp://localhost:{port}/Utility"),
               wcf_op("ep-time", R_WCF, "Services", "IUtilityService", "GetServerTimeUtc", "net.tcp://localhost:{port}/Utility"),
               wcf_op("ep-echo", R_WCF, "Services", "IUtilityService", "Echo", "net.tcp://localhost:{port}/Utility")]
        result = analysis.build_integration([client], eps)
        self.assertEqual([(e["operation"], e["entryPointId"], e["matchMethod"], e["sameRepository"]) for e in result["edges"]],
                         [("IUtilityService.Ping", "ep-ping", "contract_operation_and_path", True),
                          ("IUtilityService.GetServerTimeUtc", "ep-time", "contract_operation_and_path", True)])
        self.assertEqual([u["operation"] for u in result["unmatched"]], ["IUtilityService.Shutdown"])
        status = {e["entryPointId"]: e["internalCaller"] for e in result["entryPoints"]}
        # Never "unused": Echo may be called from outside the estate.
        self.assertEqual(status, {"ep-ping": "internal_caller_found", "ep-time": "internal_caller_found",
                                  "ep-echo": "no_internal_caller_found"})
        self.assertNotIn("unused", json.dumps(result))

    def test_an_async_client_method_is_the_operation(self):
        client = call("c1", R_SHOP, "Web", path="/Catalog.svc", contract="ICatalogService")
        client["operations"] = [op("GetItemsAsync")]
        eps = [wcf_op("ep", R_WCF, "Services", "ICatalogService", "GetItems", "http://localhost/Catalog.svc")]
        edge = analysis.build_integration([client], eps)["edges"][0]
        self.assertEqual((edge["entryPointId"], edge["sameRepository"], edge["matchMethod"]), ("ep", False, "contract_operation_and_path"))

    def test_http_by_verb_and_route_on_a_local_address_preferring_the_exact_verb_and_most_literal_route(self):
        client = call("c1", R_SHOP, "Admin", mechanism="http_client", port=5099, path="/api/{…}")
        client["operations"] = [op(verb="GET", path="/api/catalog-items", line=5), op(verb="DELETE", path="/api/catalog-items/{…}", resolution="partial", line=6)]
        eps = [http_action("ep-list", R_SHOP, "PublicApi", "GET", "api/catalog-items"),
               http_action("ep-any", R_SHOP, "PublicApi", "ANY", "api/{controller}"),
               http_action("ep-del", R_SHOP, "PublicApi", "DELETE", "api/catalog-items/{id}"),
               http_action("ep-post", R_SHOP, "PublicApi", "POST", "api/catalog-items")]
        result = analysis.build_integration([client], eps)
        self.assertEqual([(e["operation"], e["entryPointId"], e["confidence"]) for e in result["edges"]],
                         [("GET /api/catalog-items", "ep-list", 0.9), ("DELETE /api/catalog-items/{…}", "ep-del", 0.7)])

    def test_a_trailing_hole_prefers_the_route_of_the_same_length(self):
        client = call("c1", R_SHOP, "Admin", mechanism="http_client", port=5099, path="/api/{…}")
        client["operations"] = [op(verb="GET", path="/api/catalog-items/{…}", resolution="partial")]
        eps = [http_action("ep-list", R_SHOP, "PublicApi", "GET", "api/catalog-items"),
               http_action("ep-one", R_SHOP, "PublicApi", "GET", "api/catalog-items/{catalogItemId}")]
        self.assertEqual([e["entryPointId"] for e in analysis.build_integration([client], eps)["edges"]], ["ep-one"])

    def test_a_configured_base_address_prefix_matches_the_rest_as_a_suffix_never_everything(self):
        client = call("c1", R_SHOP, "Admin", mechanism="http_client", port=5099, path="/")
        client["operations"] = [op(verb="GET", path="/{…}/api/orders", resolution="partial")]
        eps = [http_action("ep-orders", R_SHOP, "PublicApi", "GET", "api/orders"),
               http_action("ep-brands", R_SHOP, "PublicApi", "GET", "api/brands"),
               http_action("ep-other", R_SHOP, "PublicApi", "GET", "v2/{id}")]
        self.assertEqual([e["entryPointId"] for e in analysis.build_integration([client], eps)["edges"]], ["ep-orders"])
        client["operations"] = [op(verb="GET", path="/{…}", resolution="partial")]
        self.assertEqual(analysis.build_integration([client], eps)["edges"], [])

    def test_two_invocations_claiming_one_call_site_are_one_edge(self):
        code = call("c1", R_SHOP, "Win", path="/Catalog.svc", contract="ICatalogService")
        config = call("c2", R_SHOP, "Win", path="/Catalog.svc", contract="ICatalogService", binding="basicHttpBinding")
        for c in (code, config):
            c["operations"] = [op("GetItems", line=78)]
        eps = [wcf_op("ep", R_WCF, "Services", "ICatalogService", "GetItems", "http://localhost/Catalog.svc")]
        edge = analysis.build_integration([config, code], eps)["edges"]
        self.assertEqual([(e["invocationId"], e["invocationIds"]) for e in edge], [("c1", ["c1", "c2"])])

    def test_http_on_a_real_host_is_matched_only_when_annotated_and_only_against_that_repository(self):
        client = call("c1", R_PAY, "Api", mechanism="http_client", host="catalog.corp.example", path="/api/catalog-items")
        client["operations"] = [op(verb="GET", path="/api/catalog-items")]
        eps = [http_action("ep-shop", R_SHOP, "PublicApi", "GET", "api/catalog-items"),
               http_action("ep-wcf", R_WCF, "Gateway", "GET", "api/catalog-items")]
        plain = analysis.build_integration([client], eps)
        self.assertEqual(plain["edges"], [])
        self.assertIn("neither a local address nor annotated", plain["unmatched"][0]["reason"])

        served_by = {"catalog.corp.example": {"repository_id": R_SHOP, "repository_slug": "shop"}}
        annotated = analysis.build_integration([client], eps, served_by=served_by)
        self.assertEqual([(e["entryPointId"], e["matchMethod"]) for e in annotated["edges"]],
                         [("ep-shop", "verb_and_route_template_on_annotated_host")])
        # The register links the annotated host the same way; loopback is unchanged.
        row = analysis.build_register([client], eps, served_by=served_by)["hosts"][0]
        self.assertEqual((row["classification"], row["services"][0]["internalTargets"][0]["repositorySlug"]), ("internal", "shop"))

    def test_grpc_by_service_and_method_and_unresolved_operations_are_reported_not_guessed(self):
        client = call("c1", R_PAY, "Api", mechanism="grpc_client", host="billing.local", contract="Billing")
        client["operations"] = [op("GetInvoice"), op(resolution="unresolved", reason="no method is called on a client of this channel")]
        eps = [{"id": "ep-g", "repository_id": R_SHOP, "repository_slug": "shop", "project_id": "shop-Billing",
                "project_path": "src/Billing/Billing.csproj", "kind": "grpc_service_method", "origin": "application",
                "handler_type": "BillingService", "handler_member": "GetInvoice",
                "detail": {"service": "Billing", "method": "GetInvoice"}}]
        result = analysis.build_integration([client], eps)
        self.assertEqual([(e["entryPointId"], e["matchMethod"], e["sameRepository"]) for e in result["edges"]],
                         [("ep-g", "service_and_method", False)])
        self.assertEqual([u["resolution"] for u in result["unmatched"]], ["unresolved"])
        apps = {a["projectPath"]: a for a in analysis.integration_by_application(result)}
        self.assertEqual([c["operation"] for c in apps["src/Api/Api.csproj"]["calls"]], ["(unresolved operation)", "Billing/GetInvoice"])
        self.assertEqual(apps["src/Billing/Billing.csproj"]["exposes"][0]["callers"][0]["callerRepositorySlug"], "pay")


if __name__ == "__main__":
    unittest.main()
