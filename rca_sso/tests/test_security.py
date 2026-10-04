"""Проверка подписи и одноразовых токенов.

Запуск внутри bench:
    bench --site <site> run-tests --app rca_sso
"""

import unittest

import frappe

from rca_sso import security


class TestToken(unittest.TestCase):
    def setUp(self):
        frappe.conf["rca_sso_secret"] = "test-secret-for-unit-tests"

    def tearDown(self):
        frappe.conf.pop("rca_sso_secret", None)

    def test_signature_is_stable_and_secret_dependent(self):
        first = security.sign("a=1&b=2")
        self.assertEqual(first, security.sign("a=1&b=2"))
        self.assertTrue(security.verify("a=1&b=2", first))
        self.assertFalse(security.verify("a=1&b=3", first))
        self.assertFalse(security.verify("a=1&b=2", None))

    def test_token_round_trip(self):
        token = security.make_token({"n": "abc", "u": "user@example.com"})
        payload = security.read_token(token)
        self.assertEqual(payload["n"], "abc")
        self.assertEqual(payload["u"], "user@example.com")

    def test_tampered_token_is_rejected(self):
        token = security.make_token({"u": "user@example.com"})
        body, signature = token.rsplit(".", 1)
        self.assertIsNone(security.read_token(body + ".deadbeef"))
        self.assertIsNone(security.read_token("мусор"))
        self.assertIsNone(security.read_token(""))
