import unittest

from logic import (
    calculate_recovery_rate,
    calculate_workload,
    get_priority,
    role_can_access,
)


class CollectFlowLogicTests(unittest.TestCase):
    def test_priority_ranking(self):
        self.assertEqual(get_priority(74), "High")
        self.assertEqual(get_priority(46), "Medium")
        self.assertEqual(get_priority(18), "Low")

    def test_recovery_rate(self):
        accounts = [
            {"balance": 85000, "days_past_due": 74},
            {"balance": 62000, "days_past_due": 46},
            {"balance": 41000, "days_past_due": 18},
            {"balance": 96000, "days_past_due": 91},
        ]
        self.assertGreaterEqual(calculate_recovery_rate(accounts), 0)
        self.assertLessEqual(calculate_recovery_rate(accounts), 100)

    def test_workload_distribution(self):
        accounts = [
            {"collector": "Juan Dela Cruz"},
            {"collector": "Juan Dela Cruz"},
            {"collector": "Maria Santos"},
        ]
        result = calculate_workload(accounts)
        self.assertEqual(result["Juan Dela Cruz"], 2)
        self.assertEqual(result["Maria Santos"], 1)

    def test_role_permission_checks(self):
        self.assertTrue(role_can_access("admin", "accounts"))
        self.assertTrue(role_can_access("supervisor", "reports"))
        self.assertTrue(role_can_access("collector", "promises"))
        self.assertTrue(role_can_access("collector", "activities"))
        self.assertTrue(role_can_access("collector", "tasks"))
        self.assertTrue(role_can_access("collector", "payments"))
        self.assertFalse(role_can_access("collector", "users"))
        self.assertFalse(role_can_access("client", "accounts"))
        self.assertFalse(role_can_access("client", "tasks"))
        self.assertTrue(role_can_access("supervisor", "queue"))
        self.assertTrue(role_can_access("admin", "queue"))
        self.assertTrue(role_can_access("management", "reports"))


if __name__ == "__main__":
    unittest.main()
