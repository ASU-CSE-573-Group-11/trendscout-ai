"""Offline contract, replay, transport, and pagination regression tests."""

import copy
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch

import requests
from jsonschema import ValidationError

from collectors.__main__ import main
from collectors.common import CollectorError, job_fields, plain_text, utc_timestamp, validate_records
from collectors.api_http import HttpClient
from collectors.records import sha256_text
from collectors.sources import (GitHubCollector, GreenhouseCollector, LeverCollector,
                                normalize, target_name)

FIXTURES = Path(__file__).parent / "fixtures/collectors"


def fixture(source):
    return json.loads((FIXTURES / f"{source}.json").read_text())


def response(status=200, data=None, headers=None):
    result = Mock(status_code=status, headers=headers or {})
    result.json.return_value = data
    return result


def raw_commit(sha="a", date="2026-11-09T00:00:00Z", kind="User"):
    return {"sha": sha, "author": {"type": kind, "login": "not-to-be-stored"},
            "commit": {"committer": {"date": date, "email": "private@example.com"},
                       "message": "not-to-be-stored"}}


class NormalizationTests(unittest.TestCase):
    def test_legacy_company_origin_migrates_to_document_origin(self):
        snapshot = fixture("greenhouse")
        snapshot["origin_cluster_id"] = "company:example-ai"
        records = normalize(snapshot)
        self.assertEqual(len({r["origin_cluster_id"] for r in records}), 2)
        self.assertTrue(all(r["metadata"]["source_control_group"] == "company:example-ai" for r in records))
        self.assertEqual(snapshot["origin_cluster_id"], "company:example-ai")

    def test_github_evidence_text_is_source_description(self):
        snapshot = fixture("github")
        self.assertEqual(normalize(snapshot)[0]["text"], snapshot["payload"]["repository"]["description"])

    def test_all_sources_validate_and_preserve_provenance(self):
        for source, count in [("greenhouse", 2), ("lever", 1), ("github", 1)]:
            with self.subTest(source=source):
                records = normalize(fixture(source))
                self.assertEqual(len(records), count)
                for record in records:
                    self.assertEqual(record["company_id"], "example-ai")
                    self.assertEqual(record["origin_cluster_id"], sha256_text(record["source_url"])[:16])
                    self.assertEqual(len(record["content_hash"]), 64)
                    self.assertEqual(record["observed_at"], "2026-11-10T12:00:00Z")

    def test_html_and_explicit_skills(self):
        record = next(r for r in normalize(fixture("greenhouse")) if r["metadata"]["title"].startswith("Machine"))
        self.assertEqual(record["metadata"]["skills"], ["c++", "cuda", "python", "pytorch"])
        self.assertNotIn("<p>", record["text"])
        self.assertEqual(plain_text("<p>one</p><p>two</p><style>hide</style>"), "one two")
        self.assertEqual(job_fields("Engineer", "trust postgres")['skills'], [])

    def test_greenhouse_updated_is_not_publication_date(self):
        record = next(r for r in normalize(fixture("greenhouse")) if r["metadata"]["title"].startswith("Machine"))
        self.assertIsNone(record["published_at"])
        self.assertIsNone(record["event_at"])
        self.assertEqual(record["metadata"]["source_updated_at"], "2026-11-09T16:30:00Z")

    def test_lever_lists_and_footer_are_retained(self):
        record = normalize(fixture("lever"))[0]
        self.assertEqual(record["metadata"]["skills"], ["docker", "kubernetes", "python", "rust", "sql"])
        self.assertIn("Requirements", record["text"])

    def test_observation_time_does_not_change_job_identity(self):
        snapshot = fixture("greenhouse")
        before = normalize(snapshot)
        snapshot["observed_at"] = "2026-11-11T00:00:00Z"
        after = normalize(snapshot)
        self.assertEqual([r["record_id"] for r in before], [r["record_id"] for r in after])
        self.assertNotEqual(before[0]["observed_at"], after[0]["observed_at"])

    def test_content_change_creates_version_preserving_source_identity(self):
        snapshot = fixture("lever")
        before = normalize(snapshot)[0]
        snapshot["payload"][0][0]["descriptionPlain"] += " Use CUDA."
        after = normalize(snapshot)[0]
        self.assertNotEqual(before["record_id"], after["record_id"])
        self.assertEqual(before["metadata"]["source_record_id"], after["metadata"]["source_record_id"])
        self.assertEqual(before["origin_cluster_id"], after["origin_cluster_id"])

    def test_identical_duplicates_collapse(self):
        records = normalize(fixture("lever"))
        self.assertEqual(validate_records(records + records), records)

    def test_conflicting_duplicates_fail(self):
        snapshot = fixture("lever")
        duplicate = copy.deepcopy(snapshot["payload"][0][0])
        duplicate["text"] = "Changed title"
        snapshot["payload"][0].append(duplicate)
        with self.assertRaises(CollectorError):
            normalize(snapshot)

    def test_order_does_not_change_output(self):
        snapshot = fixture("greenhouse")
        before = normalize(snapshot)
        snapshot["payload"]["jobs"].reverse()
        self.assertEqual(before, normalize(snapshot))

    def test_empty_boards_are_valid(self):
        snapshot = fixture("greenhouse")
        snapshot["payload"] = {"jobs": [], "meta": {"total": 0}}
        self.assertEqual(normalize(snapshot), [])
        snapshot = fixture("lever")
        snapshot["payload"] = [[]]
        self.assertEqual(normalize(snapshot), [])

    def test_malformed_response_is_not_empty_success(self):
        for source in ("greenhouse", "lever", "github"):
            snapshot = fixture(source)
            snapshot["payload"] = {"error": "unavailable"}
            with self.subTest(source=source), self.assertRaises(CollectorError):
                normalize(snapshot)

    def test_nonobject_snapshot_fails(self):
        with self.assertRaises(CollectorError):
            normalize([])

    def test_missing_source_id_and_bad_url_fail(self):
        for field, value in [("id", None), ("absolute_url", "javascript:alert(1)")]:
            snapshot = fixture("greenhouse")
            snapshot["payload"]["jobs"][0][field] = value
            with self.subTest(field=field), self.assertRaises(CollectorError):
                normalize(snapshot)

    def test_incorrect_greenhouse_total_fails(self):
        snapshot = fixture("greenhouse")
        snapshot["payload"]["meta"]["total"] = 99
        with self.assertRaises(CollectorError):
            normalize(snapshot)

    def test_naive_timestamp_fails(self):
        with self.assertRaises(CollectorError):
            utc_timestamp("2026-11-10T12:00:00")

    def test_schema_format_checking_is_enabled(self):
        records = normalize(fixture("lever"))
        records[0]["observed_at"] = "not-a-date"
        with self.assertRaises(ValidationError):
            validate_records(records)

    def test_company_id_required_and_custom_cluster_retained(self):
        snapshot = fixture("lever")
        snapshot["origin_cluster_id"] = "company-origin-7"
        self.assertEqual(normalize(snapshot)[0]["origin_cluster_id"], "company-origin-7")
        snapshot["company_id"] = " "
        with self.assertRaises(CollectorError):
            normalize(snapshot)

    def test_github_features_and_unknown_authors(self):
        metadata = normalize(fixture("github"))[0]["metadata"]
        self.assertEqual(metadata["activity_window"]["commit_count"], 3)
        self.assertEqual(metadata["activity_window"]["bot_commit_count"], 1)
        self.assertEqual(metadata["activity_window"]["unknown_author_count"], 1)
        self.assertFalse(metadata["quality_flags"]["bot_heavy"])

    def test_github_private_counter_and_window_validation(self):
        for field, value in [("private", True), ("stargazers_count", -1), ("forks_count", "7")]:
            snapshot = fixture("github")
            snapshot["payload"]["repository"][field] = value
            with self.subTest(field=field), self.assertRaises(CollectorError):
                normalize(snapshot)
        snapshot = fixture("github")
        snapshot["payload"]["commits"][0]["committed_at"] = "2026-10-01T00:00:00Z"
        with self.assertRaises(CollectorError):
            normalize(snapshot)

    def test_github_duplicate_commits_fail(self):
        snapshot = fixture("github")
        snapshot["payload"]["commits"].append(snapshot["payload"]["commits"][0])
        with self.assertRaises(CollectorError):
            normalize(snapshot)

    def test_invalid_target_is_rejected(self):
        for value in ("../private", "https://evil.com", "org/repo?x=y"):
            with self.subTest(value=value), self.assertRaises(CollectorError):
                target_name(value, repository=True)


class PaginationTests(unittest.TestCase):
    def test_greenhouse_requests_content(self):
        client = Mock()
        client.get.return_value = fixture("greenhouse")["payload"]
        snapshot = GreenhouseCollector().collect(client, fixture("greenhouse"))
        self.assertEqual(len(normalize(snapshot)), 2)
        self.assertEqual(client.get.call_args.kwargs["params"], {"content": "true"})

    def test_lever_multiple_pages_and_region(self):
        job = fixture("lever")["payload"][0][0]
        other = {**job, "id": "job-202"}
        client = Mock()
        client.get.side_effect = [[job], [other], []]
        snapshot = LeverCollector(page_size=1, region="eu").collect(client, fixture("lever"))
        self.assertEqual(len(normalize(snapshot)), 2)
        self.assertEqual([call.kwargs["params"]["skip"] for call in client.get.call_args_list], [0, 1, 2])
        self.assertIn("api.eu.lever.co", client.get.call_args.args[0])

    def test_lever_repeated_page_fails(self):
        client = Mock()
        client.get.return_value = fixture("lever")["payload"][0]
        with self.assertRaises(CollectorError):
            LeverCollector(page_size=1).collect(client, fixture("lever"))

    def test_lever_page_cap_fails(self):
        client = Mock()
        client.get.return_value = fixture("lever")["payload"][0]
        with self.assertRaises(CollectorError):
            LeverCollector(page_size=1, max_pages=1).collect(client, fixture("lever"))

    def github_client(self, pages):
        client = Mock()
        client.get.side_effect = [fixture("github")["payload"]["repository"],
                                  [{"name": "main"}], {"commit": {"sha": "pinned-tip"}}, *pages]
        return client

    def test_github_pagination_pins_tip_and_removes_personal_data(self):
        client = self.github_client([[raw_commit("a")], [raw_commit("b", kind="Bot")], []])
        snapshot = GitHubCollector(page_size=1).collect(client, fixture("github"))
        self.assertEqual(normalize(snapshot)[0]["metadata"]["activity_window"]["commit_count"], 2)
        self.assertNotIn("private@example.com", json.dumps(snapshot))
        self.assertNotIn("not-to-be-stored", json.dumps(snapshot))
        self.assertEqual(client.get.call_args.kwargs["params"]["sha"], "pinned-tip")
        self.assertEqual(snapshot["coverage"]["commit_pages"], 3)

    def test_github_empty_repository(self):
        client = Mock()
        client.get.side_effect = [fixture("github")["payload"]["repository"], []]
        snapshot = GitHubCollector().collect(client, fixture("github"))
        self.assertEqual(normalize(snapshot)[0]["metadata"]["activity_window"]["commit_count"], 0)
        self.assertEqual(client.get.call_count, 2)

    def test_github_private_repo_rejected_before_commits(self):
        client = Mock()
        client.get.return_value = {"private": True}
        with self.assertRaises(CollectorError):
            GitHubCollector().collect(client, fixture("github"))
        self.assertEqual(client.get.call_count, 1)

    def test_github_page_limit_and_repeated_commits_fail(self):
        with self.assertRaises(CollectorError):
            GitHubCollector(page_size=1, max_pages=1).collect(self.github_client([[raw_commit()]]), fixture("github"))
        with self.assertRaises(CollectorError):
            GitHubCollector(page_size=1).collect(self.github_client([[raw_commit()], [raw_commit()]]), fixture("github"))

    def test_github_half_open_window_and_fractional_seconds(self):
        batch = [raw_commit("start", "2026-11-03T12:00:00Z"),
                 raw_commit("inside", "2026-11-03T12:00:00.001Z"),
                 raw_commit("end", "2026-11-10T12:00:00Z"),
                 raw_commit("outside", "2026-11-10T12:00:00.001Z")]
        snapshot = GitHubCollector().collect(self.github_client([batch]), fixture("github"))
        self.assertEqual({c["sha"] for c in snapshot["payload"]["commits"]}, {"inside", "end"})


class HttpTests(unittest.TestCase):
    def client(self, replies, **kwargs):
        session = Mock()
        session.get.side_effect = replies
        return HttpClient(session=session, sleep=Mock(), **kwargs)

    def test_retry_after_then_success(self):
        client = self.client([response(429, headers={"Retry-After": "3"}), response(data=[])])
        self.assertEqual(client.get("https://api.lever.co/v0/postings/example"), [])
        client.sleep.assert_called_once_with(3)

    def test_long_rate_limit_exits_without_retrying_early(self):
        client = self.client([response(403, headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "2000"})], clock=lambda: 1000)
        with self.assertRaises(CollectorError):
            client.get("https://api.github.com/repos/example/sdk")
        client.sleep.assert_not_called()

    def test_retry_after_http_date(self):
        client = self.client([response(429, headers={"Retry-After": "Thu, 01 Jan 1970 00:00:05 GMT"}), response(data={})], clock=lambda: 0)
        client.get("https://api.lever.co/v0/postings/example")
        client.sleep.assert_called_once_with(5)

    def test_secondary_rate_limit_waits_one_minute(self):
        client = self.client([response(403), response(data={})])
        client.get("https://api.github.com/repos/example/sdk")
        client.sleep.assert_called_once_with(60)

    def test_network_and_server_retries(self):
        client = self.client([requests.Timeout(), response(503), response(data={"ok": True})])
        self.assertEqual(client.get("https://api.github.com/repos/example/sdk"), {"ok": True})
        self.assertEqual(client.session.get.call_count, 3)

    def test_exhausted_retries_fail(self):
        client = self.client([response(503)] * 3)
        with self.assertRaises(CollectorError):
            client.get("https://api.github.com/repos/example/sdk")
        self.assertEqual(client.session.get.call_count, 3)

    def test_nonretryable_http_and_redirect_fail(self):
        for status in (401, 404, 302):
            client = self.client([response(status)])
            with self.subTest(status=status), self.assertRaises(CollectorError):
                client.get("https://api.github.com/repos/example/sdk")
            self.assertEqual(client.session.get.call_count, 1)

    def test_invalid_json_fails(self):
        bad = response()
        bad.json.side_effect = ValueError("invalid")
        with self.assertRaises(CollectorError):
            self.client([bad]).get("https://api.github.com/repos/example/sdk")

    def test_token_only_sent_to_github(self):
        client = self.client([response(), response()], token="test-token")
        client.get("https://api.lever.co/v0/postings/example")
        self.assertNotIn("Authorization", client.session.get.call_args.kwargs["headers"])
        client.get("https://api.github.com/repos/example/sdk")
        self.assertEqual(client.session.get.call_args.kwargs["headers"]["Authorization"], "Bearer test-token")
        self.assertFalse(client.session.get.call_args.kwargs["allow_redirects"])

    def test_untrusted_api_host_rejected(self):
        for url in ("https://evil.com", "http://api.github.com", "https://api.github.com:444", "https://user@api.github.com"):
            client = self.client([])
            with self.subTest(url=url), self.assertRaises(CollectorError):
                client.get(url)
            client.session.get.assert_not_called()


class IntegrationTests(unittest.TestCase):
    def test_all_sources_import_into_teammates_graph(self):
        from graph.import_contract import records_to_graph
        records = [r for source in ("greenhouse", "lever", "github") for r in normalize(fixture(source))]
        graph = records_to_graph(records)
        nodes = [node for node in graph["nodes"] if node["label"] == "SourceRecord"]
        self.assertEqual(len(nodes), 4)
        self.assertEqual(len([node for node in graph["nodes"] if node["label"] == "Startup"]), 1)
        originals = {r["record_id"]: r for r in records}
        for node in nodes:
            actual = node["properties"]
            original = originals[actual["record_id"]]
            self.assertEqual(actual["passage"], original["text"])
            self.assertEqual(actual["origin_cluster_id"], original["origin_cluster_id"])
            self.assertEqual(actual["collector_version"], original["collector_version"])

    def test_retrieval_keeps_separate_jobs_and_evidence(self):
        from retrieval.handoff import graph_evidence, load_records_jsonl, search_snapshot
        records = normalize(fixture("greenhouse"))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "records.jsonl"
            path.write_text("\n".join(json.dumps(record) for record in records))
            loaded = load_records_jsonl(path)
        hits = search_snapshot(loaded, "Python", k=5)
        self.assertEqual(len(hits), 2)
        for hit in hits:
            evidence = graph_evidence(hit["record"])
            self.assertEqual(evidence["company_id"], "example-ai")
            self.assertEqual(evidence["source_url"], hit["record"]["source_url"])
            self.assertIn("Python", evidence["text"])


class CliTests(unittest.TestCase):
    def test_live_cli_wiring_with_mocked_public_responses(self):
        replies = {
            "greenhouse": [fixture("greenhouse")["payload"]],
            "lever": [fixture("lever")["payload"][0]],
            "github": [fixture("github")["payload"]["repository"], []],
        }
        with tempfile.TemporaryDirectory() as directory:
            for source, payloads in replies.items():
                with patch("collectors.__main__.HttpClient") as http, redirect_stdout(io.StringIO()):
                    http.return_value.get.side_effect = payloads
                    self.assertEqual(main(["--source", source, "--target", fixture(source)["target"],
                                           "--company-id", "example-ai", "--company-name", "Synthetic Example",
                                           "--output-dir", directory]), 0)
            for run in Path(directory).iterdir():
                self.assertEqual(json.loads((run / "manifest.json").read_text())["mode"], "live")
                self.assertTrue((run / "records.jsonl").exists())

    def test_malformed_live_response_writes_failure_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch("collectors.__main__.HttpClient") as http, redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                http.return_value.get.side_effect = [fixture("github")["payload"]["repository"], [{"name": "main"}], {}]
                self.assertEqual(main(["--source", "github", "--target", "example/sdk",
                                       "--company-id", "example-ai", "--company-name", "Synthetic Example",
                                       "--output-dir", directory]), 1)
            run = next(Path(directory).iterdir())
            self.assertEqual(json.loads((run / "manifest.json").read_text())["status"], "failed")
            self.assertFalse((run / "records.jsonl").exists())

    def test_all_fixture_replays_without_network_and_exact_replay(self):
        with tempfile.TemporaryDirectory() as directory, patch("collectors.api_http.requests.Session.get", side_effect=AssertionError("network forbidden")):
            for source in ("greenhouse", "lever", "github"):
                with redirect_stdout(io.StringIO()):
                    self.assertEqual(main(["--replay", str(FIXTURES / f"{source}.json"), "--output-dir", directory]), 0)
            runs = list(Path(directory).iterdir())
            self.assertEqual(len(runs), 3)
            for run in runs:
                manifest = json.loads((run / "manifest.json").read_text())
                self.assertEqual(manifest["status"], "success")
                self.assertTrue(manifest["coverage"]["fixture"])
                self.assertEqual([json.loads(line) for line in (run / "records.jsonl").read_text().splitlines()],
                                 normalize(json.loads((run / "snapshot.json").read_text())))

    def test_failure_manifest_is_not_empty_success(self):
        with tempfile.TemporaryDirectory() as directory:
            bad = Path(directory) / "bad.json"
            bad.write_text('{"snapshot_version": 9}')
            output = Path(directory) / "out"
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                self.assertEqual(main(["--replay", str(bad), "--output-dir", str(output)]), 1)
            run = next(output.iterdir())
            self.assertEqual(json.loads((run / "manifest.json").read_text())["status"], "failed")
            self.assertFalse((run / "records.jsonl").exists())

    def test_replay_cannot_relabel_company(self):
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            main(["--replay", str(FIXTURES / "lever.json"), "--company-id", "other"])


if __name__ == "__main__":
    unittest.main()
