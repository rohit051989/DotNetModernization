"""One conversion at a time (36-COPILOT-ENHANCED-CONVERSION Part N): the configuration-file check, the verifier's
corrected rules, the opening message, the runbook and the prepare decisions. Without .NET or a database.

Run: python -m unittest tests.test_engine_convert
"""
import subprocess
import tempfile
import unittest
from pathlib import Path

from app import engine  # noqa: F401
from app.conversion import gitops
from app.engine import configfiles, convert, verifier
from app.engine.inputs import render
from app.engine.verifier import packages, rediscovery


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
                         "single line", "Commit after each change", "decision-sheet.md", ".github/upgrades/skills"):
            self.assertIn(expected, m)

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
                                    "## 4. A stuck terminal", "## 5. When the agent reports done", "## 6. Verify"])
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
            (repo / "inputs.md").write_text("i")
            _git(repo, "add", "-A")
            _git(repo, "commit", "-qm", convert.INPUTS_COMMIT)
            self.assertTrue(convert.unrun(repo, base))
            (repo / "a.txt").write_text("changed")
            self.assertFalse(convert.unrun(repo, base))          # uncommitted work
            _git(repo, "commit", "-qam", "agent change")
            self.assertFalse(convert.unrun(repo, base))          # committed work
            self.assertFalse(convert.unrun(repo / "missing", base))


if __name__ == "__main__":
    unittest.main()


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
        with self.assertRaisesRegex(convert.AdvisoryFound, "more than a day ago"):
            convert.check_advisories(self._db(fetched_hours_ago=30), self.FILES, now=self.NOW)
        with self.assertRaisesRegex(convert.AdvisoryFound, "no package lookup knows this version"):
            convert.check_advisories(_Db({}), self.FILES, now=self.NOW)
