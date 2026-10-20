"""Privacy, saved-test evidence and worker contracts for the CI diagnostics."""
import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from devpocket import envguard, testlens
from devpocket.checks import invoke, pipeline
from devpocket.cli import main
from devpocket.engine import execute, gated_exit
from devpocket.inputs import read_text
from devpocket.reports import sarif


class TempTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()

    def write(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def run_cli(self, *args):
        output = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(io.StringIO()):
            code = main([*args, "--root", str(self.root), "--json"])
        return code, json.loads(output.getvalue())


class InputTests(TempTest):
    def test_bounds_utf8_bom_and_root_containment(self):
        self.write("a", "\ufeffhello")
        self.assertEqual(read_text(self.root, "a", 8), "hello")
        for path, limit in (("a", 4), ("../a", 8), ("/a", 8), ("a\\b", 8), ("C:/a", 8), (".", 8)):
            with self.subTest(path=path), self.assertRaises(ValueError):
                read_text(self.root, path, limit)

    def test_invalid_bytes_do_not_appear_in_errors(self):
        (self.root / "a").write_bytes(b"private-payload\xff")
        with self.assertRaisesRegex(ValueError, "UTF-8") as error:
            read_text(self.root, "a", 100)
        self.assertNotIn("private-payload", str(error.exception))

    @unittest.skipUnless(os.name == "posix", "symlink/FIFO support")
    def test_symlink_files_directories_and_special_files_refused(self):
        self.write("real/a", "value")
        (self.root / "file").symlink_to(self.root / "real/a")
        (self.root / "directory").symlink_to(self.root / "real", target_is_directory=True)
        os.mkfifo(self.root / "pipe")
        for path in ("file", "directory/a", "pipe"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                read_text(self.root, path, 100)

    def test_observed_file_mutation_is_refused(self):
        self.write("a", "stable")
        real_fstat = os.fstat
        calls = 0

        def changed(fd):
            nonlocal calls
            calls += 1
            if calls == 2:
                self.write("a", "changed")
            return real_fstat(fd)

        with mock.patch("devpocket.inputs.os.fstat", side_effect=changed):
            with self.assertRaisesRegex(ValueError, "changed"):
                read_text(self.root, "a", 100)

    def test_path_and_handle_ctime_may_differ_but_handle_changes_are_refused(self):
        self.write("a", "unchanged")
        original = os.fstat
        fields = ("st_mode", "st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
        calls = 0

        def metadata(fd):
            nonlocal calls
            calls += 1
            value = original(fd)
            attributes = {key: getattr(value, key) for key in fields}
            attributes["st_ctime_ns"] += 123
            return SimpleNamespace(**attributes)

        with mock.patch("devpocket.inputs.os.fstat", side_effect=metadata):
            self.assertEqual(read_text(self.root, "a", 100), "unchanged")

        def changed(fd):
            result = metadata(fd)
            result.st_ctime_ns += calls
            return result

        with mock.patch("devpocket.inputs.os.fstat", side_effect=changed):
            with self.assertRaisesRegex(ValueError, "changed"):
                read_text(self.root, "a", 100)


class EnvGuardTests(TempTest):
    def inspect(self, template, target, **params):
        self.write(".env.example", template)
        self.write(".env", target)
        return execute("envguard", params, self.root)

    def test_names_missing_empty_extra_and_duplicates_have_locations(self):
        result = self.inspect("URL=\nKEY=\nEMPTY=\n", "URL=https://example.invalid\nEMPTY='' # empty\nEXTRA=private-value\nURL=again\n")
        self.assertEqual(result["status"], "completed")
        self.assertEqual((result["data"]["missing"], result["data"]["empty"], result["data"]["extra"]), (1, 1, 1))
        by_rule = {row["rule"]: row for row in result["findings"]}
        self.assertEqual(by_rule["env-missing"]["path"], ".env.example")
        self.assertEqual(by_rule["env-missing"]["line"], 2)
        self.assertEqual(by_rule["env-duplicate"]["line"], 4)
        self.assertEqual(gated_exit(result), 1)
        self.assertNotIn("private-value", json.dumps(result))

    def test_multiline_values_do_not_become_names_or_leak(self):
        target = "export TEXT=\"private-first-line\nFAKE_NAME=private-second-line\nclosing\" # comment\nSINGLE='private\nANOTHER_FAKE=private'\n"
        result = self.inspect("TEXT=\nSINGLE=\n", target)
        self.assertEqual(result["findings"], [])
        self.assertEqual(result["data"]["target_names"], 2)
        self.assertNotIn("private", json.dumps(result))
        self.assertNotIn("FAKE", json.dumps(result))

    def test_values_are_never_evaluated_or_returned(self):
        result = self.inspect("A=\nB=\n", "A=$(touch should-not-exist)\nB=${ARBITRARY_SECRET}\n")
        self.assertEqual(result["findings"], [])
        self.assertFalse((self.root / "should-not-exist").exists())
        self.assertNotIn("ARBITRARY_SECRET", json.dumps(result))

    def test_unquoted_hash_and_quoted_hash_empty_rules(self):
        result = self.inspect("A=\nB=\nC=\n", "A= # comment\nB='#not-empty'\nC=\"\"\n")
        self.assertEqual(result["data"]["empty"], 2)

    def test_malformed_and_unclosed_quotes_withhold_input(self):
        for target in ("private-bad-line", "A='private-unclosed", "A='good'private-tail"):
            with self.subTest(target=target):
                result = self.inspect("A=\n", target)
                self.assertIn("env-syntax", {row["rule"] for row in result["findings"]})
                self.assertNotIn("private", json.dumps(result))

    def test_optional_names_and_extra_policy(self):
        result = self.inspect("REQUIRED=\nOPTIONAL=\n", "REQUIRED=present\nEXTRA=present\n", ignore=["OPTIONAL"], allow_extra=True)
        self.assertEqual(result["findings"], [])
        self.assertEqual(result["data"]["extra"], 1)

    def test_missing_file_bad_ignore_and_empty_reference_do_not_pass(self):
        self.assertEqual(execute("envguard", {}, self.root)["status"], "error")
        result = self.inspect("A=\n", "A=1\n", ignore=["not valid"])
        self.assertEqual(result["status"], "error")
        self.assertEqual(gated_exit(self.inspect("# none\n", "A=1\n")), 1)

    def test_name_and_byte_limits(self):
        with mock.patch.object(envguard, "MAX_KEYS", 1):
            self.assertEqual(self.inspect("A=1\nB=2\n", "A=1\n")["status"], "error")
        with mock.patch.object(envguard, "MAX_BYTES", 2):
            self.assertEqual(self.inspect("A=1\n", "A=1\n")["status"], "error")

    def test_cli_worker_and_sarif_preserve_privacy(self):
        self.inspect("MISSING=\n", "OTHER=never-expose-this\n")
        code, report = self.run_cli("envguard")
        self.assertEqual(code, 1)
        worker = invoke("envguard", {}, self.root)
        self.assertEqual(worker["data"], report["data"])
        output = json.dumps(sarif(worker))
        self.assertNotIn("never-expose-this", output)
        self.assertIn(".env.example", output)


class TestLensTests(TempTest):
    def inspect(self, xml, **params):
        self.write("junit.xml", xml)
        return execute("testlens", {"paths": ["junit.xml"], **params}, self.root)

    def test_counts_nested_suites_namespaces_and_body_privacy(self):
        result = self.inspect('''<testsuites xmlns="urn:junit" tests="4" failures="1" errors="1" skipped="1"><testsuite tests="4"><testsuite><testcase name="ok"/><testcase name="failed"><failure message="private-message">private-stack</failure><system-out>private-output</system-out></testcase></testsuite><testcase name="broken"><error>private-error</error></testcase><testcase name="skip"><skipped/></testcase></testsuite></testsuites>''')
        self.assertEqual(result["status"], "failed")
        self.assertEqual({k: result["data"][k] for k in ("tests", "passed", "failures", "errors", "skipped")}, {"tests": 4, "passed": 1, "failures": 1, "errors": 1, "skipped": 1})
        self.assertEqual(len(result["findings"]), 2)
        self.assertNotIn("private", json.dumps(result))

    def test_failures_remain_failed_when_baselined_or_gate_disabled(self):
        result = self.inspect('<testsuite><testcase name="bad"><failure/></testcase></testsuite>')
        for row in result["findings"]:
            row["existing"] = True
        self.assertEqual(gated_exit(result, "none"), 1)

    def test_empty_and_skipped_only_evidence_have_explicit_count_gates(self):
        self.assertEqual(self.inspect("<testsuite/>")["status"], "failed")
        self.assertEqual(self.inspect("<testsuite/>", min_tests=0)["status"], "completed")
        xml = '<testsuite><testcase name="skip"><skipped/></testcase></testsuite>'
        self.assertEqual(self.inspect(xml)["status"], "completed")
        self.assertEqual(self.inspect(xml, max_skipped=0)["status"], "failed")

    def test_mixed_outcomes_are_descriptive_not_a_flakiness_claim(self):
        xml = '<testsuite><testcase classname="group" name="same"/><testcase classname="group" name="same"><failure/></testcase></testsuite>'
        result = self.inspect(xml)
        self.assertEqual(result["data"]["mixed_outcomes"], 1)
        self.assertEqual(result["data"]["repeated_identities"], 1)
        self.assertIn("does not establish flakiness", result["findings"][1]["help"])

    def test_declared_counts_and_conflicting_markers_cannot_pass(self):
        invalid = ['<testsuite tests="99"><testcase name="a"/></testsuite>', '<testsuites failures="1"><testsuite><testcase name="a"/></testsuite></testsuites>', '<testsuite errors="-1"/>', '<testsuite><testcase name="a"><failure/><skipped/></testcase></testsuite>']
        for xml in invalid:
            with self.subTest(xml=xml):
                self.assertEqual(self.inspect(xml)["status"], "error")

    def test_xml_entities_dtd_bad_encoding_and_parser_errors_are_private(self):
        invalid = ['<!DOCTYPE testsuite [<!ENTITY x "private">]><testsuite/>', '<!DOCTYPE testsuite SYSTEM "file:///private"><testsuite/>', '<?xml version="1.0" encoding="utf-16"?><testsuite/>', '<testsuite><private-bad></testsuite>']
        for xml in invalid:
            with self.subTest(xml=xml):
                result = self.inspect(xml)
                self.assertEqual(result["status"], "error")
                self.assertNotIn("private", json.dumps(result))

    def test_invalid_structure_and_missing_names_rejected(self):
        for xml in ('<project/>', '<testsuite><wrapper><testcase name="x"/></wrapper></testsuite>', '<testsuite><testcase/></testsuite>', '<testsuite><failure/></testsuite>'):
            with self.subTest(xml=xml):
                self.assertEqual(self.inspect(xml)["status"], "error")

    def test_truncated_display_does_not_merge_distinct_test_names(self):
        first, second = "x" * 180 + "one", "x" * 180 + "two"
        report = self.inspect(f'<testsuite><testcase name="{first}"><failure/></testcase><testcase name="{second}"><failure/></testcase></testsuite>')
        self.assertEqual(report["data"]["identities"], 2)
        self.assertEqual(len({f["fingerprint"] for f in report["findings"]}), 2)

    def test_path_aliases_rejected_and_multiple_inputs_aggregated(self):
        self.write("a.xml", '<testsuite><testcase name="one"/></testsuite>')
        self.write("b.xml", '<testsuite><testcase name="two"/></testsuite>')
        result = execute("testlens", {"paths": ["a.xml", "./a.xml"]}, self.root)
        self.assertEqual(result["status"], "error")
        report = execute("testlens", {"paths": ["a.xml", "b.xml"]}, self.root)
        self.assertEqual(report["data"]["tests"], 2)

    def test_resource_limits_and_large_depth(self):
        xml = '<testsuite><testcase name="x"/><testcase name="y"/></testsuite>'
        with mock.patch.object(testlens, "MAX_CASES", 1):
            self.assertEqual(self.inspect(xml)["status"], "error")
        with mock.patch.object(testlens, "MAX_TOTAL_BYTES", 10):
            self.assertEqual(self.inspect(xml)["status"], "error")
        self.assertEqual(self.inspect("<testsuite>" + "<x>" * 65 + "</x>" * 65 + "</testsuite>")["status"], "error")

    def test_cli_worker_sarif_and_dependent_gate(self):
        self.inspect('<testsuite><testcase name="broken"><failure/></testcase></testsuite>')
        code, report = self.run_cli("testlens", "junit.xml")
        self.assertEqual(code, 1)
        self.assertEqual(invoke("testlens", {"paths": ["junit.xml"]}, self.root)["data"], report["data"])
        config = {"version": 1, "checks": {"tests": {"tool": "testlens", "input": {"paths": ["junit.xml"]}}, "later": {"tool": "envtwin", "needs": ["tests"]}}}
        results = pipeline(config, self.root, fail_on="none")
        self.assertEqual([row["status"] for row in results["checks"]], ["failed", "skipped"])
        location = sarif(report)["runs"][0]["results"][0]["locations"][0]["physicalLocation"]
        self.assertEqual(location["artifactLocation"]["uri"], "junit.xml")

    def test_google_test_notrun_is_skipped_and_unknown_status_is_refused(self):
        report = self.inspect('<testsuite><testcase name="disabled" status="notrun" result="suppressed"/></testsuite>', max_skipped=0)
        self.assertEqual(report["data"]["skipped"], 1)
        self.assertEqual(report["status"], "failed")
        self.assertEqual(self.inspect('<testsuite><testcase name="unknown" status="failed"/></testsuite>')["status"], "error")

    def test_cached_pass_invalidates_when_report_changes_to_failure(self):
        self.write("junit.xml", '<testsuite><testcase name="one"/></testsuite>')
        config = {"version": 1, "checks": {"test-results": {"tool": "testlens", "input": {"paths": ["junit.xml"]}, "cache": {"inputs": ["junit.xml"]}}}}
        first = pipeline(config, self.root)["checks"][0]["report"]
        second = pipeline(config, self.root)["checks"][0]["report"]
        self.assertEqual([first["cache"]["status"], second["cache"]["status"]], ["miss", "hit"])
        self.write("junit.xml", '<testsuite><testcase name="one"><failure/></testcase></testsuite>')
        failed = pipeline(config, self.root, fail_on="none")
        self.assertEqual(failed["exit_code"], 1)
        self.assertNotEqual(failed["checks"][0]["report"]["cache"]["status"], "hit")

    def test_actual_stdio_mcp_exposes_both_tools_without_values_or_bodies(self):
        import subprocess
        import sys
        self.write(".env.example", "NAME=\n")
        self.write(".env", "NAME=hidden-env-value\n")
        self.write("junit.xml", '<testsuite><testcase name="ok"><system-out>hidden-test-output</system-out></testcase></testsuite>')
        messages = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {"name": "ci-test", "version": "1"}}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "envguard", "arguments": {}}},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "testlens", "arguments": {"paths": ["junit.xml"]}}},
        ]
        result = subprocess.run([sys.executable, "-m", "devpocket", "serve", "--root", str(self.root)], input="".join(json.dumps(m) + "\n" for m in messages), text=True, capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        replies = {row["id"]: row for row in map(json.loads, result.stdout.splitlines())}
        self.assertFalse(replies[2]["result"]["isError"])
        self.assertFalse(replies[3]["result"]["isError"])
        self.assertEqual(replies[3]["result"]["structuredContent"]["data"]["passed"], 1)
        self.assertNotIn("hidden-", result.stdout)


if __name__ == "__main__":
    unittest.main()
