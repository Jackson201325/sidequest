import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path[:0] = [str(Path(__file__).resolve().parents[1])]

from sidequest.environments import fetch_environments, review_status


class EnvironmentTests(unittest.TestCase):
    def test_explicit_pipeline_does_not_require_parent_app_access(self):
        commands = []
        def cli(args, **kwargs):
            commands.append(args)
            self.assertEqual(args, ['heroku', 'auth:token'])
            return 'fixture-token'
        with patch.dict('os.environ', {}, clear=True), patch('urllib.request.urlopen', return_value=io.BytesIO(b'[]')) as api:
            result = fetch_environments([42], cli, 'fixture-pipeline')
        self.assertEqual(result['entries']['42']['status'], 'Not provisioned')
        self.assertTrue(api.call_args[0][0].full_url.endswith('/pipelines/fixture-pipeline/review-apps'))
        self.assertEqual(commands, [['heroku', 'auth:token']])

    def test_no_pipeline_means_no_credential_or_api_access(self):
        with patch('urllib.request.urlopen') as api:
            with self.assertRaisesRegex(RuntimeError, 'disabled'):
                fetch_environments([42], lambda *a, **kw: self.fail('credentials requested'))
        api.assert_not_called()

    def test_provisioned_does_not_mean_web_ready(self):
        self.assertEqual(review_status({"status": "created"}), "Provisioned")
        self.assertEqual(review_status({"status": "building"}), "Building")
        self.assertEqual(review_status({"status": "errored"}), "Failed")
        self.assertEqual(review_status({"status": "created"}, {}, [{"type": "web", "state": "crashed"}]), "Web crashed")
        self.assertEqual(review_status({"status": "created"}, {}, [{"type": "worker", "state": "up"}]), "No web dyno")

    def test_reads_only_matching_pr_and_never_saves_token(self):
        payloads = [[{"pr_number": 42, "status": "created", "app": {"id": "test-app"}}],
                    {"name": "review-test", "web_url": "https://review-test.herokuapp.com"},
                    [{"type": "web", "state": "up"}]]
        requests = []

        def respond(request, **kwargs):
            requests.append(request)
            return io.BytesIO(json.dumps(payloads.pop(0)).encode())

        def cli(args, **kwargs):
            self.assertEqual(args, ["heroku", "auth:token"])
            return "test-secret"

        with patch.dict("os.environ", {}, clear=True), patch("urllib.request.urlopen", side_effect=respond):
            result = fetch_environments([42, 99], cli, "test-pipeline")
        self.assertEqual(result["entries"]["42"]["status"], "Web up")
        self.assertEqual(result["entries"]["99"]["status"], "Not provisioned")
        self.assertNotIn("test-secret", json.dumps(result))
        self.assertTrue(all(r.get_method() == "GET" for r in requests))


if __name__ == "__main__":
    unittest.main()
