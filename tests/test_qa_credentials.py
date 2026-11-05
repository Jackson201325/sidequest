import importlib.util
import os
from pathlib import Path
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('portable_qa_credentials', ROOT / 'bin/sidequest-qa-shot.py')
qa = importlib.util.module_from_spec(spec)
spec.loader.exec_module(qa)


class CredentialTests(unittest.TestCase):
    def test_redirected_login_never_receives_credentials(self):
        class Browser:
            def __init__(self): self.calls = []
            def js(self, expression):
                self.calls.append(expression)
                return 'https://unrelated.example/login' if expression == 'window.location.href' else True
        browser = Browser()
        with self.assertRaises(qa.Fail):
            qa.sign_in_if_asked(browser, 'https://review-test.herokuapp.com', ('qa@example.invalid', 'fixture'), {'review-test.herokuapp.com'})
        self.assertEqual(len(browser.calls), 2)

    def test_local_login_requires_users_own_environment_credentials(self):
        class Browser:
            def js(self, expression): return 'http://localhost/login' if expression == 'window.location.href' else True
        with self.assertRaisesRegex(qa.Fail, 'SIDEQUEST_QA_EMAIL'):
            qa.sign_in_if_asked(Browser(), 'http://localhost/login', qa.DEFAULT_ACCOUNT)

    def test_review_login_has_no_platform_specific_fallback(self):
        from sidequest.review_apps import login, ReviewAppError
        with patch.dict(os.environ, {}, clear=True), patch('subprocess.run') as process:
            with self.assertRaises(ReviewAppError): login()
        process.assert_not_called()


if __name__ == '__main__':
    unittest.main()
