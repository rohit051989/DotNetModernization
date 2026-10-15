"""One conversion at a time (36-COPILOT-ENHANCED-CONVERSION Part N): the configuration-file check, the verifier's
corrected rules, the opening message, the runbook and the prepare decisions. Without .NET or a database.

Run: python -m unittest tests.test_engine_convert
"""
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

from app import engine  # noqa: F401
from app.conversion import gitops
from app.conversion import approaches, batch, msbuild, planner
from app.engine import configfiles, convert, deployment_assets, inputs, verifier
from app.engine.inputs import selfcontained
from app.engine.inputs import render
from app.engine.verifier import deployment, packages, rediscovery


class ConfigurationFiles(unittest.TestCase):
    def test_json_is_read_as_dotnet_configuration_reads_it(self):
        text = b'\xef\xbb\xbf{\n  // a comment\n  "A": "x // not a comment", /* block */\n  "B": [1, 2,],\n}\n'
        self.assertIsNone(configfiles.json_error(text))
        self.assertIsNone(configfiles.json_error(b"  \n"))

    def test_a_broken_json_file_is_named_with_its_line_and_never_its_text(self):
        text = b'{\n  "Redis": {\n    "Password": "vault:redis-p      "Password": "",sClient"\n  }\n}\n'
        where = configfiles.json_error(text)
        self.assertTrue(where.startswith("invalid JSON at line 3, position"), where)
        self.assertNotIn("vault:redis", where)
        self.assertIn("line 3", configfiles.json_error(b'{\n  "A": 1,\n  "Path": "C:\\Accounts"\n}'))

    def test_a_broken_xml_file_is_named_with_its_line(self):
        self.assertIsNone(configfiles.xml_error(b'<?xml version="1.0"?>\n<configuration><a b="1"/></configuration>'))
        self.assertTrue(configfiles.xml_error(b"<configuration>\n  <a>\n</configuration>").startswith("invalid XML at line 3"))

    def test_every_configuration_file_is_read_except_build_output_and_excluded_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for rel, data in {"src/appsettings.json": b"{ bad", "src/web.config": b"<configuration/>",
                              "src/bin/Debug/x.json": b"{ bad", "src/obj/y.config": b"<bad",
                              ".github/upgrades/state.json": b"{ bad", "src/Program.cs": b"{ bad"}.items():
                (root / rel).parent.mkdir(parents=True, exist_ok=True)
                (root / rel).write_bytes(data)
            found = configfiles.unparseable(root, exclude=(".github/upgrades/",))
            self.assertEqual(list(found), ["src/appsettings.json"])
            self.assertIn(".github/upgrades/state.json", configfiles.unparseable(root))


class ConfigurationCheck(unittest.TestCase):
    def test_a_file_the_conversion_made_unparseable_fails_the_verification(self):
        c = verifier.config_check({}, {"src/appsettings.json": "invalid JSON at line 138, position 40"}, 13)
        self.assertEqual(c["state"], "fail")
        self.assertIn("src/appsettings.json (invalid JSON at line 138, position 40)", c["detail"])
        self.assertEqual(verifier.verdict([c, {"id": "x", "label": "x", "state": "pass", "detail": ""}])[0], "NOT PROVEN")

    def test_a_file_already_broken_at_the_base_commit_is_a_gap(self):
        broken = {"src/Utility/appsettings.json": "invalid JSON at line 3, position 25"}
        self.assertEqual(verifier.config_check(broken, broken, 13)["state"], "gap")
        self.assertEqual(verifier.config_check(broken, {}, 13)["state"], "pass")
        self.assertIn("all 13", verifier.config_check({}, {}, 13)["detail"])

    def test_an_item_inside_an_unparseable_file_is_not_checked_never_resolved(self):
        before = rediscovery.work_items({"items": [
            {"id": "enterprise-vault-secret-reference", "occurrences": [
                {"project": "Api.csproj", "file": "src/Api/appsettings.json", "lines": [{"line": 11}]}]},
            {"id": "custom-file-logger-provider", "occurrences": [
                {"project": "Api.csproj", "file": "src/Api/Logging/FileLoggerProvider.cs", "lines": [{"line": 9}]}]},
            {"id": "aspnetcore-iis-hosting", "occurrences": [{"project": "Api.csproj", "file": None, "lines": []}]},
        ]})
        resolved, not_checked = verifier.split_not_checked(sorted(before), before, {"src/Api/appsettings.json"})
        self.assertEqual(not_checked, [("Api.csproj", "enterprise-vault-secret-reference")])
        self.assertEqual(resolved, [("Api.csproj", "aspnetcore-iis-hosting"), ("Api.csproj", "custom-file-logger-provider")])

    def test_the_rules_say_so(self):
        self.assertTrue(any("does not parse on the branch" in r and r.startswith("NOT PROVEN") for r in verifier.RULES))
        self.assertTrue(any("not checked, never resolved" in r for r in verifier.RULES))


class OpeningMessage(unittest.TestCase):
    def test_it_says_what_done_means(self):
        m = convert.opening_message("Make it ready for OpenShift.", "AccountsApi.sln")
        for expected in ("Make it ready for OpenShift.", "Build the solution (AccountsApi.sln) with 0 errors",
                         "Every test must pass", "Do not weaken, skip or delete any test", "list each change with its reason",
                         "every JSON and XML configuration file", "without blocking the terminal", "listening",
                         "do not change code to work around it", "at most 3 times", "the command you ran",
                         "single line", "decision-sheet.md", ".github/upgrades/skills",
                         "Every result you report must be from the final state of the code",
                         "run all four checks again, and report only the results of that last run"):
            self.assertIn(expected, m)
        self.assertNotIn("Commit after each change", m)      # conversion 2: the agent never did; one commit is fine

    def test_the_target_framework_is_named_as_the_agent_names_it(self):
        self.assertEqual(convert.framework_name("net10.0"), ".NET 10")
        self.assertEqual(convert.framework_name("net8.0"), ".NET 8")


class Runbook(unittest.TestCase):
    RECORD = {"repository": "accountsapi-net10", "engagement": "test-client-a", "branch": "conversion/1",
              "worktree": r"D:\runs\test-client-a\accountsapi-net10\conversions\1\wt", "solution": "AccountsApi.sln",
              "baseline": "e89bc6a147e456b730d664178d416f50bd532f31", "platform": {"commit": "0123456789abcdef", "dirty": False},
              "goal": "Make it ready for OpenShift.", "targetFramework": "net10.0"}

    def test_one_page_from_the_template(self):
        text = convert.render_runbook(self.RECORD)
        self.assertNotIn("${", text)
        self.assertLess(len(text.splitlines()), 100)
        headings = [line for line in text.splitlines() if line.startswith("## ")]
        self.assertEqual(headings, ["## 1. Open the worktree", "## 2. Send the opening message", "## 3. Standard replies",
                                    "## 4. A stuck terminal", "## 5. When the agent stops",
                                    "## 6. When the agent reports done", "## 7. Verify"])
        self.assertIn("If the agent stops without its done report (the four results from the opening message), send "
                      "`Continue.`", text)
        self.assertIn("One commit at the end is fine.", text)
        self.assertIn(convert.opening_message("Make it ready for OpenShift.", "AccountsApi.sln"), text)
        self.assertIn("python -m app.engine.convert verify --engagement test-client-a --repository accountsapi-net10 "
                      "--branch conversion/1", text)
        self.assertIn("Ctrl+C", text)
        self.assertIn("Commit all remaining changes on the current branch.", text)


class GlobalInstructions(unittest.TestCase):
    def test_configuration_files_are_edited_once_and_checked(self):
        text = (render.TEMPLATES / "copilot-instructions.md").read_text(encoding="utf-8")
        self.assertIn("in a single edit", text)
        self.assertIn("re-read it and confirm it parses", text)
        self.assertNotIn("skip attribute", text)


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *args],
                          capture_output=True, text=True, check=True).stdout.strip()


class Unrun(unittest.TestCase):
    def test_only_a_worktree_nothing_happened_in_is_refreshed_in_place(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            _git(repo, "init", "-q")
            (repo / "a.txt").write_text("a")
            _git(repo, "add", "-A")
            _git(repo, "commit", "-qm", "base")
            base = _git(repo, "rev-parse", "HEAD")
            self.assertTrue(convert.unrun(repo, base))
            for name in ("package.csproj", "inputs.md"):          # a package commit, then the inputs: the platform's
                (repo / name).write_text(name)
                subprocess.run(["git", "-C", str(repo), *gitops.PLATFORM_IDENTITY, "add", "-A"], check=True)
                subprocess.run(["git", "-C", str(repo), *gitops.PLATFORM_IDENTITY, "commit", "-qm", name], check=True)
                self.assertTrue(convert.unrun(repo, base))
            (repo / "a.txt").write_text("changed")
            self.assertFalse(convert.unrun(repo, base))          # uncommitted work
            _git(repo, "commit", "-qam", "agent change")
            self.assertFalse(convert.unrun(repo, base))          # committed work
            self.assertFalse(convert.unrun(repo / "missing", base))



def _upgrade(project, value, item="package-upgrade-safe"):
    return {"id": item, "occurrences": [{"project": project, "file": project, "value": value, "lines": [{"line": 7}]}]}


class PackagesAgainstTheInputs(unittest.TestCase):
    TARGETS = [{"project": "Infra.csproj", "package": "System.Runtime.Caching", "current": "10.0.10", "asked": "10.0.12"},
               {"project": "Infra.csproj", "package": "Microsoft.Extensions.Http.Resilience", "current": "10.9.0", "asked": "10.10.0"},
               {"project": "Api.csproj", "package": "PdfPig", "current": "0.1.13", "asked": "0.1.16"}]

    def test_nuget_versions_are_ordered(self):
        k = packages.version_key
        self.assertLess(k("10.0.9"), k("10.0.12"))
        self.assertLess(k("10.0.0-rc.2.25502.107"), k("10.0.0"))
        self.assertLess(k("1.0.0-alpha"), k("1.0.0-beta"))
        self.assertEqual(k("10.0"), k("10.0.0"))

    def test_at_the_asked_version_a_newer_release_since_is_information_never_remaining(self):
        model = {"items": [
            _upgrade("Infra.csproj", "System.Runtime.Caching 10.0.12 -> 10.0.13"),               # asked: met
            _upgrade("Infra.csproj", "Microsoft.Extensions.Http.Resilience 10.11.0 -> 10.12.0"),  # above asked: met
            _upgrade("Api.csproj", "PdfPig 0.1.14 -> 0.1.17"),                                     # below asked: remains
            _upgrade("Api.csproj", "Asp.Versioning.Mvc.ApiExplorer 8.1.0 -> 10.2.1"),             # never asked: remains
            {"id": "package-vulnerable", "occurrences": [
                {"project": "Infra.csproj", "file": "Infra.csproj", "value": "System.Runtime.Caching 10.0.12: high", "lines": []}]},
        ]}
        judged, since = packages.judge(model, self.TARGETS)
        left = [(i["id"], o["value"]) for i in judged["items"] for o in i["occurrences"]]
        self.assertEqual(left, [("package-upgrade-safe", "PdfPig 0.1.14 -> 0.1.17"),
                                ("package-upgrade-safe", "Asp.Versioning.Mvc.ApiExplorer 8.1.0 -> 10.2.1"),
                                ("package-vulnerable", "System.Runtime.Caching 10.0.12: high")])
        self.assertEqual([(s["package"], s["version"], s["asked"], s["newest"]) for s in since],
                         [("System.Runtime.Caching", "10.0.12", "10.0.12", "10.0.13"),
                          ("Microsoft.Extensions.Http.Resilience", "10.11.0", "10.10.0", "10.12.0")])
        items = rediscovery.work_items(judged)
        self.assertNotIn(("Infra.csproj", "package-upgrade-safe"), items)
        self.assertIn(("Infra.csproj", "package-vulnerable"), items)       # a vulnerability is today's finding

    def test_the_versions_asked_for_are_read_back_from_a_package_instructions_places(self):
        # The place line as render._instruction writes it: "- `file:line` (project): `value`".
        place = "- `src/Infra/Infra.csproj:20` (src/Infra/Infra.csproj): `System.Runtime.Caching 10.0.10 -> 10.0.12`"
        targets = render.package_targets({".github/upgrades/skills/applying-package-upgrade-safe-bump.md": "x\n" + place + "\n",
                                          ".github/upgrades/skills/applying-other.md": place})
        self.assertEqual([(t["project"], t["package"], t["current"], t["asked"]) for t in targets],
                         [("src/Infra/Infra.csproj", "System.Runtime.Caching", "10.0.10", "10.0.12")])

    def test_the_inputs_commit_is_the_platforms_first_commit_after_the_baseline(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            _git(repo, "init", "-q")
            (repo / "a.txt").write_text("a")
            _git(repo, "add", "-A")
            _git(repo, "commit", "-qm", "base")
            base = _git(repo, "rev-parse", "HEAD")
            skills = repo / ".github" / "upgrades" / "skills"
            skills.mkdir(parents=True)
            (skills / "applying-package-upgrade-safe-bump.md").write_text(
                "- `p.csproj:3` (p.csproj): `Moq 4.20.72 -> 4.21.0`\n", newline="\n")
            subprocess.run(["git", "-C", str(repo), *gitops.PLATFORM_IDENTITY, "add", "-A"], check=True)
            subprocess.run(["git", "-C", str(repo), *gitops.PLATFORM_IDENTITY, "commit", "-qm", "inputs"], check=True)
            inputs = _git(repo, "rev-parse", "HEAD")
            (repo / "a.txt").write_text("agent")
            _git(repo, "commit", "-qam", "agent change")
            self.assertEqual(packages.inputs_commit(repo, base, "HEAD"), inputs)
            self.assertEqual([(t["package"], t["asked"]) for t in packages.asked_for(repo, inputs)], [("Moq", "4.21.0")])


class SuccessorsAndFixes(unittest.TestCase):
    PLACES = "\n".join([
        "- `src/Api/Api.csproj:20` (src/Api/Api.csproj): `Microsoft.AspNetCore.Mvc.Versioning.ApiExplorer 5.1.0: package "
        "deprecated (Other); replacement Asp.Versioning.Mvc.ApiExplorer 10.2.1`",
        "- `src/Api/Api.csproj:24` (src/Api/Api.csproj): `Microsoft.Extensions.PlatformAbstractions 1.1.0: package "
        "deprecated (Legacy, Other); no suggested replacement`",
        "- `src/Infra/Infra.csproj:21` (src/Infra/Infra.csproj): `System.Security.Cryptography.Xml 10.0.9: high; fixed in 10.0.13`",
        "- `src/Infra/Infra.csproj:22` (src/Infra/Infra.csproj): `Acme.Crypto 1.0.0: critical; no release without a known advisory yet`",
    ])

    def test_a_successor_and_a_fix_are_requested_versions_too(self):
        targets = render.package_targets({".github/upgrades/skills/applying-package-x.md": self.PLACES})
        self.assertEqual([(t["project"], t["package"], t["current"], t["asked"]) for t in targets], [
            ("src/Api/Api.csproj", "Asp.Versioning.Mvc.ApiExplorer", None, "10.2.1"),
            ("src/Infra/Infra.csproj", "System.Security.Cryptography.Xml", "10.0.9", "10.0.13")])

    def test_the_verifier_judges_a_successor_like_any_other_upgrade(self):
        targets = render.package_targets({".github/upgrades/skills/applying-package-x.md": self.PLACES})
        judged, since = packages.judge({"items": [_upgrade("src/Api/Api.csproj", "Asp.Versioning.Mvc.ApiExplorer 8.1.0 -> 10.2.1")]},
                                       targets)
        self.assertEqual(len(judged["items"]), 1)          # 8.1.0 is below the 10.2.1 asked for: remaining
        judged, since = packages.judge({"items": [_upgrade("src/Api/Api.csproj", "Asp.Versioning.Mvc.ApiExplorer 10.2.1 -> 10.3.0")]},
                                       targets)
        self.assertEqual((judged["items"], [s["asked"] for s in since]), ([], ["10.2.1"]))


class _Rows:
    def __init__(self, rows):
        self.rows = rows

    def all(self):
        return self.rows


class _Db:
    """package_lookup_cache rows by package id: [(metadata, fetched_at)]."""
    def __init__(self, cache):
        self.cache = cache

    def execute(self, _sql, params):
        return _Rows(self.cache.get(params["p"], []))


class Advisories(unittest.TestCase):
    NOW = convert.datetime.datetime(2026, 10, 14, 12, 0, tzinfo=convert.datetime.timezone.utc)
    FILES = {".github/upgrades/skills/applying-package-x.md": SuccessorsAndFixes.PLACES}

    def _db(self, xml_advisory=False, fetched_hours_ago=1):
        fetched = self.NOW - convert.datetime.timedelta(hours=fetched_hours_ago)
        vuln = [{"severity": 2, "advisoryUrl": "https://github.com/advisories/GHSA-x"}] if xml_advisory else []
        return _Db({"asp.versioning.mvc.apiexplorer": [({"10.2.1": {"vulnerabilities": []}}, fetched)],
                    "system.security.cryptography.xml": [({"10.0.13": {"vulnerabilities": vuln}}, fetched)]})

    def test_every_version_asked_for_is_confirmed_free_of_known_advisories(self):
        checked = convert.check_advisories(self._db(), self.FILES, now=self.NOW)
        self.assertEqual([(c["package"], c["asked"], c["advisories"]) for c in checked],
                         [("Asp.Versioning.Mvc.ApiExplorer", "10.2.1", []), ("System.Security.Cryptography.Xml", "10.0.13", [])])

    def test_a_version_with_an_advisory_or_stale_lookups_is_refused(self):
        with self.assertRaisesRegex(convert.AdvisoryFound, "System.Security.Cryptography.Xml 10.0.13 .*GHSA-x"):
            convert.check_advisories(self._db(xml_advisory=True), self.FILES, now=self.NOW)
        # Part N: old lookups are refreshed, never refused: the caller runs discovery, which answers them again.
        with self.assertRaisesRegex(convert.LookupsStale, "more than a day ago"):
            convert.check_advisories(self._db(fetched_hours_ago=30), self.FILES, now=self.NOW)
        # Within the discovery run that answered them, their age is not checked again.
        self.assertEqual(len(convert.check_advisories(self._db(fetched_hours_ago=30), self.FILES, now=self.NOW,
                                                      check_age=False)), 2)
        with self.assertRaisesRegex(convert.AdvisoryFound, "no package lookup knows this version"):
            convert.check_advisories(_Db({}), self.FILES, now=self.NOW)


class FromConversionOne(unittest.TestCase):
    """What conversion 1 of AccountsApi.Net10 found (36-COPILOT-ENHANCED-CONVERSION Part N)."""

    def test_the_opening_message_says_open_the_named_files_and_never_hide_a_warning(self):
        m = convert.opening_message("Goal.", "A.sln")
        self.assertIn("Open those files by their paths; do not search for them", m)
        self.assertIn("never create a file the instructions say already exists", m)
        self.assertIn("Never suppress a warning or an error to make a check pass: no -nowarn", m)
        g = (render.TEMPLATES / "copilot-instructions.md").read_text(encoding="utf-8")
        self.assertIn("Open them by those paths; do not", g)
        self.assertIn("NU1901 to\n  NU1904", g)

    def test_the_runbook_says_close_the_terminal_when_ctrl_c_does_not_clear_it(self):
        self.assertIn("If Ctrl+C does not clear `>>`, close the Copilot terminal: it\nreopens and retries the command.",
                      convert.render_runbook(Runbook.RECORD))

    def test_every_instruction_names_the_existing_files_it_concerns(self):
        files = ["Build/validate-config.bat", "Build/Jenkins/Jenkinsfile", "deploy/docker/Dockerfile",
                 ".github/workflows/ci.yml", ".github/upgrades/skills/x.md", "src/Api/Api.csproj", "src/Api/Program.cs",
                 "src/Api/appsettings.json", "Directory.Packages.props", "README.md"]
        model = {"files": files}
        build = {"id": "windows-build-pipeline", "occurrences": [{"project": "src/Api/Api.csproj", "file": None}], "impact": []}
        named = render.concerned_files(model, build)
        self.assertEqual(named, [".github/workflows/ci.yml", "Build/Jenkins/Jenkinsfile", "Build/validate-config.bat",
                                 "Directory.Packages.props", "deploy/docker/Dockerfile", "src/Api/Api.csproj"])
        package = {"id": "package-upgrade-safe", "occurrences": [{"project": "src/Api/Api.csproj", "file": "src/Api/Api.csproj"}],
                   "impact": []}
        self.assertEqual(render.concerned_files(model, package), ["Directory.Packages.props", "src/Api/Api.csproj"])
        config = {"id": "hardcoded-windows-path", "occurrences": [{"project": "src/Api/Api.csproj", "file": "src/Api/appsettings.json"}],
                  "impact": [{"file": "src/Api/Program.cs"}, {"file": None, "proposed": "src/Api/New.cs"}]}
        self.assertIn("src/Api/Program.cs", render.concerned_files(model, config))
        self.assertIn("src/Api/appsettings.json", render.concerned_files(model, config))
        self.assertEqual(render.concerned_files({}, config), [])

    def test_a_settings_file_named_like_a_java_integration_test_is_not_a_test_file(self):
        projects = ["tests/Api.UnitTests/Api.UnitTests.csproj"]
        self.assertFalse(verifier.is_test_file("src/Api/appsettings.SIT.json", projects))
        self.assertFalse(verifier.is_test_file("tests/Api.UnitTests/appsettings.json", projects))      # configuration
        self.assertFalse(verifier.is_test_file("tests/Api.UnitTests/Api.UnitTests.csproj", projects))  # configuration
        self.assertTrue(verifier.is_test_file("src/Api/ServiceTests.cs", projects))

    def test_tests_kept_counts_and_lists_dotnet_test_files_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            base, tip = Path(tmp) / "base", Path(tmp) / "tip"
            for root, settings, test in ((base, "a", "x"), (tip, "b", "y")):
                for rel, text in {"src/Api/appsettings.SIT.json": settings, "tests/Api.UnitTests/ApiTests.cs": test,
                                  "tests/Api.UnitTests/Same.cs": "same"}.items():
                    (root / rel).parent.mkdir(parents=True, exist_ok=True)
                    (root / rel).write_text(text + "\n")
            tc = verifier.tests_changed(base, tip, ["tests/Api.UnitTests/Api.UnitTests.csproj"])
        self.assertEqual((tc["legacyTests"], [c["path"] for c in tc["changed"]]), (2, ["tests/Api.UnitTests/ApiTests.cs"]))
        self.assertEqual(tc["configuration"], [{"path": "src/Api/appsettings.SIT.json", "change": "changed"}])
        md = verifier.markdown({"label": "x", "verdict": "PROVEN", "repository": "r", "base": "b" * 8, "ref": "r",
                                "tip": "t" * 8, "verifiedAt": "now", "verifier": {"version": "v", "plugin": "p"},
                                "reasons": [], "checks": [], "rules": [], "forAPerson": [],
                                "rediscovery": {"before": 0, "resolved": [], "remaining": [], "introduced": [], "offTarget": []},
                                "impact": {"predictedFiles": 0, "predictedCreates": 0, "changedFiles": 0, "unpredicted": [],
                                           "predictedUntouched": []},
                                "diff": {"filesTouched": 0, "linesAdded": 0, "linesDeleted": 0, "commits": 0}, "excludedPaths": [],
                                "testFiles": {k: tc[k] for k in ("changed", "added", "removed")}})
        self.assertIn("| changed | `tests/Api.UnitTests/ApiTests.cs` | +1 -1 |", md)


class CarriedByDeployment(unittest.TestCase):
    def test_a_cronjob_naming_the_console_application_and_an_inject_annotation_for_the_secret(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            files = {
                "deploy/openshift/cronjob-encryptionutility.yaml":
                    "apiVersion: batch/v1\nkind: CronJob\nmetadata:\n  name: accounts-encryptionutility\n",
                "deploy/openshift/notes.yaml": "kind: ConfigMap\nname: accounts-keygenerator\n",
                "deploy/openshift/vault-agent-annotations.yaml":
                    'vault.hashicorp.com/agent-inject-secret-token-signing-key: "${VAULT_SECRETS_PATH}"\n',
                "src/Api/appsettings.json": '{\n  "Token": {\n    "SigningKey": "vault:token-signing-key",\n'
                                            '    "ClientSecret": "vault:client-secret"\n  }\n}\n',
            }
            for rel, text in files.items():
                (root / rel).parent.mkdir(parents=True, exist_ok=True)
                (root / rel).write_text(text)
            model = {"items": [
                {"id": "console-batch-job", "occurrences": [
                    {"project": "src/Accounts.EncryptionUtility/Accounts.EncryptionUtility.csproj", "file": None, "lines": []},
                    {"project": "src/Accounts.KeyGenerator/Accounts.KeyGenerator.csproj", "file": None, "lines": []}]},
                {"id": "enterprise-vault-secret-reference", "occurrences": [
                    {"project": "src/Api/Api.csproj", "file": "src/Api/appsettings.json",
                     "lines": [{"line": 3, "value": "Token:SigningKey"}, {"line": 4, "value": "Token:ClientSecret"}]}]},
            ]}
            left, carried = deployment.carried(model, root)
        self.assertEqual([(c["item"], c["file"]) for c in carried], [
            ("console-batch-job", "deploy/openshift/cronjob-encryptionutility.yaml"),
            ("enterprise-vault-secret-reference", "deploy/openshift/vault-agent-annotations.yaml")])
        self.assertEqual([(i["id"], [o["project"] for o in i["occurrences"]]) for i in left["items"]], [
            ("console-batch-job", ["src/Accounts.KeyGenerator/Accounts.KeyGenerator.csproj"]),
            ("enterprise-vault-secret-reference", ["src/Api/Api.csproj"])])
        self.assertEqual(left["items"][1]["occurrences"][0]["lines"], [{"line": 4, "value": "Token:ClientSecret"}])


class PackagesBeforeTheAgent(unittest.TestCase):
    def test_a_framework_provided_reference_is_removed_with_its_line(self):
        text = ('<Project>\r\n  <ItemGroup>\r\n    <PackageReference Include="System.Text.Json" Version="10.0.9" />\r\n'
                '    <PackageReference Include="Moq" Version="4.20.72">\r\n      <PrivateAssets>all</PrivateAssets>\r\n'
                '    </PackageReference>\r\n  </ItemGroup>\r\n</Project>')
        once, removed = msbuild.remove_package_reference(text, "System.Text.Json")
        self.assertTrue(removed)
        self.assertNotIn("System.Text.Json", once)
        self.assertIn('    <PackageReference Include="Moq"', once)
        twice, _ = msbuild.remove_package_reference(once, "moq")
        self.assertEqual(twice, "<Project>\r\n  <ItemGroup>\r\n  </ItemGroup>\r\n</Project>")
        self.assertEqual(msbuild.remove_package_reference(twice, "Moq"), (twice, False))

    def test_the_removal_approach_checks_applies_and_says_why(self):
        approach = approaches.APPROACHES["remove-package-reference"]
        target = {"package_id": "System.Text.Json", "version": "10.0.9", "project": "src/U/U.csproj",
                  "provided_by": "Microsoft.NETCore.App net10.0"}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "src/U").mkdir(parents=True)
            (root / "src/U/U.csproj").write_text('<Project>\n  <ItemGroup>\n    <PackageReference Include="System.Text.Json" '
                                                 'Version="10.0.9" />\n  </ItemGroup>\n</Project>\n')
            self.assertEqual(approach.pre_check(root, target).outcome, "apply")
            approach.apply(root, target)
            self.assertEqual(approach.post_check(root, target), [])
            self.assertEqual(approach.pre_check(root, target).outcome, "not_applicable")
        self.assertEqual(approach.allowed_paths(target), {"src/U/U.csproj"})
        self.assertEqual(selfcontained.check_commit_message(approach.message(target), None), [])

    def test_the_agent_is_not_asked_for_what_the_platform_applied(self):
        model = {"items": [
            {"id": "package-upgrade-safe", "occurrences": [
                {"project": "src/I/I.csproj", "value": "System.Runtime.Caching 10.0.10 -> 10.0.13"},
                {"project": "src/A/A.csproj", "value": "PdfPig 0.1.13 -> 0.1.16"}]},
            {"id": "package-vulnerable", "occurrences": [
                {"project": "src/I/I.csproj", "value": "System.Security.Cryptography.Xml 10.0.9: high; fixed in 10.0.13"}]},
            {"id": "package-provided-by-framework", "occurrences": [
                {"project": "src/U/U.csproj", "value": "System.Text.Json 10.0.9: provided by Microsoft.NETCore.App net10.0"}]},
            {"id": "package-replacement-required", "occurrences": [
                {"project": "src/A/A.csproj", "value": "Old 5.1.0: package deprecated (Other); replacement New 10.2.1"}]},
        ], "packages": [{"package": "System.Runtime.Caching", "projects": ["src/I/I.csproj"]},
                        {"package": "PdfPig", "projects": ["src/A/A.csproj"]}]}
        applied = [{"item": "package-upgrade-safe", "project": "src/I/I.csproj", "package": "System.Runtime.Caching", "to": "10.0.13"},
                   {"item": "package-upgrade-safe", "project": "src/I/I.csproj", "package": "System.Security.Cryptography.Xml",
                    "to": "10.0.13"},
                   {"item": "package-provided-by-framework", "project": "src/U/U.csproj", "package": "System.Text.Json", "to": None}]
        left = inputs.without_applied(model, applied)
        self.assertEqual([(i["id"], [o["value"] for o in i["occurrences"]]) for i in left["items"]], [
            ("package-upgrade-safe", ["PdfPig 0.1.13 -> 0.1.16"]),
            ("package-replacement-required", ["Old 5.1.0: package deprecated (Other); replacement New 10.2.1"])])
        self.assertEqual([p["package"] for p in left["packages"]], ["PdfPig"])

    def test_the_verifier_reads_the_package_commits_and_finds_the_inputs_commit_after_them(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            _git(repo, "init", "-q")
            (repo / "a.txt").write_text("a")
            _git(repo, "add", "-A")
            _git(repo, "commit", "-qm", "base")
            base = _git(repo, "rev-parse", "HEAD")

            def platform(message, rel, text):
                (repo / rel).parent.mkdir(parents=True, exist_ok=True)
                (repo / rel).write_text(text, newline="\n")
                subprocess.run(["git", "-C", str(repo), *gitops.PLATFORM_IDENTITY, "add", "-A"], check=True)
                subprocess.run(["git", "-C", str(repo), *gitops.PLATFORM_IDENTITY, "commit", "-qm", message], check=True)
                return _git(repo, "rev-parse", "HEAD")

            bump = approaches.APPROACHES["package-upgrade-safe"].message(
                {"package_id": "Moq", "from": "4.20.72", "to": "4.21.0", "project": "t/T.csproj",
                 "declaration": {"file": "t/T.csproj", "kind": "package_reference", "name": "Moq"}})
            platform(bump, "t/T.csproj", "moq")
            inputs_sha = platform(convert.INPUTS_COMMIT, ".github/upgrades/skills/applying-package-upgrade-safe-bump.md",
                                  "- `p.csproj:3` (p.csproj): `PdfPig 0.1.13 -> 0.1.16`\n")
            self.assertEqual(packages.inputs_commit(repo, base, "HEAD"), inputs_sha)
            self.assertEqual([(t["project"], t["package"], t["asked"]) for t in packages.applied_by_platform(repo, base, "HEAD")],
                             [("t/T.csproj", "Moq", "4.21.0")])



TEMPLATE = """apiVersion: apps/v1
kind: Deployment
spec:
  template:
    spec:
      initContainers:
        - name: vault-init
          image: ${VAULT_INIT_IMAGE}
---
kind: ConfigMap
data:
  secret-mapping.json: |
    {"token-signing-key": "secret/accounts-api/auth/token-signing-key"}
"""


class FromConversionTwo(unittest.TestCase):
    """What conversion 2 of AccountsApi.Net10 found (36-COPILOT-ENHANCED-CONVERSION Part N)."""

    def test_an_existing_vault_delivery_is_recognised_and_names_what_it_delivers(self):
        found = deployment_assets.vault_delivery({"deploy/openshift/deployment-template.yaml": TEMPLATE,
                                                  "src/Api/appsettings.json": '{"A": "vault:x"}',
                                                  "deploy/other.yaml": "kind: Service\n"})
        self.assertEqual([(f.file, f.kind) for f in found], [("deploy/openshift/deployment-template.yaml", "vault-init-container")])
        self.assertTrue(found[0].delivers("token-signing-key"))
        self.assertFalse(found[0].delivers("signing-key"))
        agent = deployment_assets.vault_delivery({"d.yaml": "vault.hashicorp.com/agent-inject: 'true'\n"})
        self.assertEqual([f.kind for f in agent], ["vault-agent-injector"])

    def test_a_vault_reference_the_existing_mechanism_delivers_is_carried(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for rel, text in {"deploy/openshift/deployment-template.yaml": TEMPLATE,
                              "src/Api/appsettings.json": '{\n  "SigningKey": "vault:token-signing-key"\n}\n'}.items():
                (root / rel).parent.mkdir(parents=True, exist_ok=True)
                (root / rel).write_text(text)
            model = {"items": [{"id": "enterprise-vault-secret-reference", "occurrences": [
                {"project": "src/Api/Api.csproj", "file": "src/Api/appsettings.json", "lines": [{"line": 2, "value": "SigningKey"}]}]}]}
            left, carried = deployment.carried(model, root)
        self.assertEqual(left["items"], [])
        self.assertEqual(carried[0]["file"], "deploy/openshift/deployment-template.yaml")

    def test_an_instruction_names_the_tests_of_the_code_it_touches_and_the_mechanism_it_keeps(self):
        model = {"engagement": {"target_framework": "net10.0"}, "repository": {"commit": "e89bc6a"},
                 "files": ["deploy/openshift/deployment-template.yaml", "src/Api/Logging/FileLoggerProvider.cs", "src/Api/Api.csproj"],
                 "vault_delivery": [{"file": "deploy/openshift/deployment-template.yaml", "kind": "vault-init-container",
                                     "description": "an init container that writes the vault secrets before the application starts"}],
                 "test_mappings": [{"source_file": "src/Api/Logging/FileLoggerProvider.cs",
                                    "production_type": "Api.Logging.FileLoggerProvider", "test_file": "tests/Api.Tests/HostTests.cs",
                                    "test_class": "Api.Tests.HostComponentTests",
                                    "test_methods": ["FileLogger_UnwritablePath_DoesNotThrow", "FileLogger_WritesDailyFileUnderConfiguredPath"]}]}
        logger = {"id": "custom-file-logger-provider", "name": "Custom logging provider", "guidance": "g", "decided": False,
                  "ordering": [],
                  "resolution": {"id": "unregister-file-logger-provider", "name": "Unregister", "guidance": "Unregister it."},
                  "occurrences": [{"project": "src/Api/Api.csproj", "file": "src/Api/Logging/FileLoggerProvider.cs",
                                   "value": None, "certainty": "confirmed", "lines": [{"line": 9}]}], "impact": []}
        text = render._instruction(model, logger, {"custom-file-logger-provider"}, {"custom-file-logger-provider": logger})
        self.assertIn("## Tests that use this code", text)
        self.assertIn("- `tests/Api.Tests/HostTests.cs`, `HostComponentTests`: `FileLogger_UnwritablePath_DoesNotThrow`, "
                      "`FileLogger_WritesDailyFileUnderConfiguredPath` (uses `FileLoggerProvider`)", text)
        vault = {"id": "enterprise-vault-secret-reference", "name": "Vault reference", "guidance": "g", "decided": False,
                 "ordering": [],
                 "resolution": {"id": "keep-existing-vault-delivery", "name": "Keep", "guidance": "Keep it."},
                 "occurrences": [{"project": "src/Api/Api.csproj", "file": "src/Api/appsettings.json", "value": "SigningKey",
                                  "certainty": "confirmed", "lines": [{"line": 2}]}], "impact": []}
        text = render._instruction(model, vault, {"enterprise-vault-secret-reference"}, {"enterprise-vault-secret-reference": vault})
        self.assertIn("## The existing vault delivery", text)
        self.assertIn("- `deploy/openshift/deployment-template.yaml`: an init container", text)
        self.assertIn("never replace, remove or rewrite a mechanism they hold", text)

    def test_the_catalog_keeps_the_logger_class_and_its_tests_by_default(self):
        import yaml
        items = yaml.safe_load((Path(render.__file__).resolve().parents[2] / "seed" / "data" / "catalog_items.yaml")
                               .read_text(encoding="utf-8"))["items"]
        by_id = {i["id"]: i for i in items}
        defaults = lambda i: [r["id"] for r in by_id[i]["resolutions"] if r.get("is_default")]   # noqa: E731
        self.assertEqual(defaults("custom-file-logger-provider"), ["unregister-file-logger-provider"])
        self.assertIn("keep-existing-vault-delivery", [r["id"] for r in by_id["enterprise-vault-secret-reference"]["resolutions"]])
        guidance = yaml.safe_load((Path(render.__file__).resolve().parents[2] / "seed" / "data" / "engine_guidance.yaml")
                                  .read_text(encoding="utf-8"))
        linux = guidance["items"]["windows-build-pipeline"]["resolutions"]["linux-build-pipeline"]
        self.assertIn("Never delete,\n   rename or empty one", linux)
        self.assertIn("`*.sh text eol=lf`", linux)
        self.assertIn("git add --chmod=+x", linux)

    def test_a_retarget_and_a_fixed_delta_are_left_out_of_the_inputs(self):
        model = {"items": [{"id": "target-framework-retarget", "occurrences": [{"project": "a.csproj", "value": "net8.0 -> net10.0"}]}],
                 "packages": [], "deltas": [{"id": "d1", "sites": {"src/Program.cs": ["x"], "src/Other.cs": ["y"]}}]}
        left = inputs.without_applied(model, [
            {"item": "target-framework-retarget", "project": "*", "package": "", "to": "net10.0"},
            {"item": "framework-delta", "project": "src/Program.cs", "package": "d1", "to": None}])
        self.assertEqual(left["items"], [])
        self.assertEqual(left["deltas"], [{"id": "d1", "sites": {"src/Other.cs": ["y"]}}])


class FastPackageStep(unittest.TestCase):
    def test_a_batch_commit_lists_every_change_in_the_form_the_verifier_reads_back(self):
        class U:
            def __init__(self, approach_id, target):
                self.approach_id, self.target = approach_id, target
        lines = batch.change_line(U("package-upgrade-safe", {"bumps": [
            {"package_id": "Moq", "from": "4.20.72", "to": "4.21.0", "project": "tests/A/A.csproj"},
            {"package_id": "Moq", "from": "4.20.72", "to": "4.21.0", "project": "tests/B/B.csproj"}]}))
        lines += batch.change_line(U("remove-package-reference", {"package_id": "System.Text.Json", "version": "10.0.9",
                                                                  "project": "src/U/U.csproj", "provided_by": "Microsoft.NETCore.App net10.0"}))
        self.assertEqual(lines, ["- Moq 4.20.72 -> 4.21.0 (tests/A/A.csproj)", "- Moq 4.20.72 -> 4.21.0 (tests/B/B.csproj)",
                                 "- Remove System.Text.Json 10.0.9 (src/U/U.csproj): provided by Microsoft.NETCore.App net10.0"])
        read = [packages.BUMP_LINE.match(x) for x in lines]
        self.assertEqual([(m["package"], m["asked"], m["where"]) for m in read if m],
                         [("Moq", "4.21.0", "tests/A/A.csproj"), ("Moq", "4.21.0", "tests/B/B.csproj")])
        message = "Package changes that need no code (2)\n\n" + "\n".join(lines) + f"\nBuilt and tested together.\n{batch.MESSAGE_END}"
        self.assertEqual(selfcontained.check_commit_message(message, None), [])

    def test_a_data_row_test_is_rerun_by_its_method(self):
        from app.conversion import dotnet
        self.assertEqual(dotnet.method_name('InvalidField_FailsValidationForThatField ("BranchCode","12")'),
                         "InvalidField_FailsValidationForThatField")


class VerifierFromConversionTwo(unittest.TestCase):
    def test_an_approved_removal_is_recorded_and_an_unapproved_one_is_not(self):
        approvals = [{"test": "FileLogger_UnwritablePath_DoesNotThrow", "reason": "provider removed by decision",
                      "approvedBy": "R. Khanna", "at": "2026-10-15T10:00:00+00:00"}]
        approved, rest = verifier.approved_removals(
            ["FileLogger_UnwritablePath_DoesNotThrow", "FileLogger_WritesDailyFileUnderConfiguredPath"], approvals)
        self.assertEqual([a["test"] for a in approved], ["FileLogger_UnwritablePath_DoesNotThrow"])
        self.assertEqual(rest, ["FileLogger_WritesDailyFileUnderConfiguredPath"])

    def test_approvals_are_kept_per_branch_with_reason_and_person(self):
        with tempfile.TemporaryDirectory() as tmp:
            old = planner.RUNS
            planner.RUNS = Path(tmp)
            try:
                (Path(tmp) / "e" / "r").mkdir(parents=True)
                convert.approve_removal("e", "r", "conversion/2", ["T1", "T2"], "removed with the provider", "R. Khanna")
                convert.approve_removal("e", "r", "conversion/2", ["T2"], "again", "R. Khanna")
                got = convert.approvals_for("e", "r", "conversion/2")
                self.assertEqual([(a["test"], a["reason"]) for a in got], [("T1", "removed with the provider"), ("T2", "again")])
                self.assertEqual(convert.approvals_for("e", "r", "conversion/3"), [])
                with self.assertRaises(ValueError):
                    convert.approve_removal("e", "r", "conversion/2", ["T3"], " ", "R. Khanna")
            finally:
                planner.RUNS = old

    def test_changed_files_are_attributed_to_the_instructions_that_name_them(self):
        named = {"applying-linux-build-pipeline.md": ["Build/package.bat", "Build/validate-config.bat", ".github/workflows/ci.yml"],
                 "applying-vault-agent-files.md": ["deploy/openshift/deployment-template.yaml"],
                 "applying-console-json-only.md": ["src/Api/appsettings.json"]}
        a = verifier.attribution(named, [".github/workflows/ci.yml", "Build/package.sh", "src/Api/appsettings.json"])
        self.assertEqual([(x["instruction"], x["state"]) for x in a["instructions"]], [
            ("applying-console-json-only.md", "changed"), ("applying-linux-build-pipeline.md", "partly"),
            ("applying-vault-agent-files.md", "untouched")])
        self.assertEqual(a["unnamed"], ["Build/package.sh"])

    def test_the_files_section_is_read_back_from_an_instruction(self):
        text = ("# x\n\n## Files\n\nThese files exist in this repository and concern this change.\n\n"
                "- `Build/package.bat`\n- `deploy/docker/Dockerfile`\n\nThe deployment and build files listed ...\n")
        m = verifier.FILES_SECTION.search(text)
        self.assertEqual(re.findall(r"^- `([^`]+)`", m.group(1), re.MULTILINE), ["Build/package.bat", "deploy/docker/Dockerfile"])

    def test_a_shell_script_needs_lf_the_executable_bit_and_an_eol_rule(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            _git(repo, "init", "-q")
            _git(repo, "config", "core.autocrlf", "false")
            (repo / "a.txt").write_text("a")
            _git(repo, "add", "-A")
            _git(repo, "commit", "-qm", "base")
            (repo / ".gitattributes").write_bytes(b"*.sh text eol=lf\n")
            (repo / "good.sh").write_bytes(b"#!/bin/sh\necho ok\n")
            (repo / "bad.sh").write_bytes(b"#!/bin/sh\r\necho no\r\n")
            _git(repo, "add", ".gitattributes", "good.sh")
            _git(repo, "add", "--chmod=+x", "good.sh")
            (repo / ".gitattributes").write_bytes(b"*.sh text eol=lf\n")
            subprocess.run(["git", "-C", str(repo), "-c", "core.autocrlf=false", "-c", "core.safecrlf=false", "add",
                            "--renormalize", "bad.sh"], capture_output=True)
            _git(repo, "update-index", "--add", "--cacheinfo", "100644,"
                 + subprocess.run(["git", "-C", str(repo), "hash-object", "-w", "--no-filters", "bad.sh"],
                                  capture_output=True, text=True).stdout.strip() + ",bad.sh")
            _git(repo, "commit", "-qm", "scripts")
            got = verifier.shell_scripts(repo, repo, "HEAD", [{"path": "good.sh", "change": "A"}, {"path": "bad.sh", "change": "A"},
                                                             {"path": "a.txt", "change": "M"}])
        self.assertEqual([(s["path"], s["lf"], s["executable"], s["attribute"]) for s in got],
                         [("good.sh", True, True, True), ("bad.sh", False, False, True)])


if __name__ == "__main__":
    unittest.main()
