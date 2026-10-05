import threading
import unittest
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import server


class CollectFlowServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.CollectFlowHandler)
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.httpd.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join(timeout=2)

    def test_password_hash_is_salted_and_verified(self):
        first_hash = server.hash_password("Strong-password-123")
        second_hash = server.hash_password("Strong-password-123")
        self.assertNotEqual(first_hash, second_hash)
        self.assertTrue(server.verify_password("Strong-password-123", first_hash))
        self.assertFalse(server.verify_password("wrong-password", first_hash))

    def test_account_read_rejects_anonymous_request(self):
        with self.assertRaises(HTTPError) as error:
            urlopen(f"{self.base_url}/api/accounts", timeout=3)
        self.assertEqual(error.exception.code, 401)
        error.exception.read()
        error.exception.close()

    def test_account_write_rejects_anonymous_request(self):
        request = Request(
            f"{self.base_url}/api/accounts",
            data=b"{}",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.assertRaises(HTTPError) as error:
            urlopen(request, timeout=3)
        self.assertEqual(error.exception.code, 401)
        error.exception.read()
        error.exception.close()

    def test_workflow_and_admin_routes_reject_anonymous_requests(self):
        for endpoint in ("/api/tasks", "/api/payments", "/api/activities", "/api/audit"):
            with self.subTest(endpoint=endpoint):
                with self.assertRaises(HTTPError) as error:
                    urlopen(f"{self.base_url}{endpoint}", timeout=3)
                self.assertEqual(error.exception.code, 401)
                error.exception.read()
                error.exception.close()


if __name__ == "__main__":
    unittest.main()