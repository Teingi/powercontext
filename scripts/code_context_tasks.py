# Copyright (c) 2026 OceanBase.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Owned cross-module fixtures and fixed acceptance questions for code context."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Task:
    name: str
    query: str
    definitions: tuple[str, ...]
    callers: tuple[str, ...]
    tests: tuple[str, ...]
    check: str = ""


SOURCES = {
    "pricing.py": "def calculate_total(prices):\n    return sum(prices)\n",
    "orders.py": "from pricing import calculate_total\n\ndef checkout(prices):\n    return calculate_total(prices)\n",
    "gateway.py": "from orders import checkout\n\ndef submit_cart(prices):\n    return checkout(prices)\n",
    "backoff.py": "def retry_delay(attempt):\n    return 2 ** attempt\n",
    "workers.py": "from backoff import retry_delay\n\ndef run_job(attempt):\n    return retry_delay(attempt)\n",
    "names.py": "def normalize_label(label):\n    return label.strip()\n",
    "catalog.py": "from names import normalize_label\n\ndef publish(label):\n    return normalize_label(label)\n",
    "test_orders.py": (
        "import unittest\nfrom gateway import submit_cart\nfrom orders import checkout\n\n"
        "class OrdersTest(unittest.TestCase):\n"
        "    def test_checkout(self):\n        self.assertEqual(checkout([2, 3]), 5)\n"
        "    def test_submit_cart(self):\n        self.assertEqual(submit_cart([2, 3]), 5)\n"
    ),
    "test_workers.py": (
        "import unittest\nfrom workers import run_job\n\nclass WorkersTest(unittest.TestCase):\n"
        "    def test_run_job(self):\n        self.assertEqual(run_job(3), 8)\n"
    ),
    "test_catalog.py": (
        "import unittest\nfrom catalog import publish\n\nclass CatalogTest(unittest.TestCase):\n"
        "    def test_publish(self):\n        self.assertEqual(publish(' hello '), 'hello')\n"
    ),
    **{f"extras/module_{i}.py": f"def unrelated_{i}(value):\n    return value + {i}\n" for i in range(24)},
}

TASKS = (
    Task(
        "locate_total",
        "Locate calculate_total, its direct production caller, and tests covering the checkout path.",
        ("pricing.py",),
        ("orders.py:checkout",),
        ("test_orders.py",),
    ),
    Task(
        "locate_delay",
        "Locate retry_delay, its direct production caller, and the test of that caller.",
        ("backoff.py",),
        ("workers.py:run_job",),
        ("test_workers.py",),
    ),
    Task(
        "locate_label",
        "Locate normalize_label, its direct production caller, and the test of that caller.",
        ("names.py",),
        ("catalog.py:publish",),
        ("test_catalog.py",),
    ),
    Task(
        "cart_path",
        "Explain the submit_cart to calculate_total call path. List all three definition files, both production callers, and test files.",
        ("gateway.py", "orders.py", "pricing.py"),
        ("gateway.py:submit_cart", "orders.py:checkout"),
        ("test_orders.py",),
    ),
    Task(
        "job_path",
        "Explain how run_job obtains retry_delay. List both definition files, the production caller, and test files.",
        ("workers.py", "backoff.py"),
        ("workers.py:run_job",),
        ("test_workers.py",),
    ),
    Task(
        "publish_path",
        "Explain how publish uses normalize_label. List both definition files, the production caller, and test files.",
        ("catalog.py", "names.py"),
        ("catalog.py:publish",),
        ("test_catalog.py",),
    ),
    Task(
        "total_tests",
        "Before changing calculate_total, identify its definition, all transitive production callers, and relevant existing test files. Do not change files.",
        ("pricing.py",),
        ("orders.py:checkout", "gateway.py:submit_cart"),
        ("test_orders.py",),
    ),
    Task(
        "delay_tests",
        "Before changing retry_delay, identify its definition, production callers, and relevant existing test files. Do not change files.",
        ("backoff.py",),
        ("workers.py:run_job",),
        ("test_workers.py",),
    ),
    Task(
        "negative_total",
        "Modify calculate_total so any negative price raises ValueError through checkout and submit_cart; preserve nonnegative totals. Report the changed definition file, its direct production caller, and test files. Run checks.",
        ("pricing.py",),
        ("orders.py:checkout",),
        ("test_orders.py",),
        "from gateway import submit_cart\ntry:\n submit_cart([2,-1])\nexcept ValueError:\n pass\nelse:\n raise AssertionError('negative prices accepted')\nassert submit_cart([2,3]) == 5",
    ),
    Task(
        "cap_delay",
        "Modify retry_delay so it caps delays at 60, including through run_job, preserving delays below 60. Report the changed definition file, its direct production caller, and test files. Run checks.",
        ("backoff.py",),
        ("workers.py:run_job",),
        ("test_workers.py",),
        "from workers import run_job\nassert run_job(8) == 60\nassert run_job(3) == 8",
    ),
    Task(
        "lower_label",
        "Modify normalize_label to strip outer whitespace and lowercase text through publish. Report the changed definition file, its direct production caller, and test files. Run checks.",
        ("names.py",),
        ("catalog.py:publish",),
        ("test_catalog.py",),
        "from catalog import publish\nassert publish(' HELLO ') == 'hello'",
    ),
    Task(
        "continue_discount",
        "Continue the handoff: add optional discount=0 to submit_cart, checkout, and calculate_total. Pass it through both callers and return max(0, sum(prices)-discount), preserving old positional calls. Report all three definition files, both production callers, and test files. Run checks and preserve the historical constraints.",
        ("pricing.py", "orders.py", "gateway.py"),
        ("gateway.py:submit_cart", "orders.py:checkout"),
        ("test_orders.py",),
        "from gateway import submit_cart\nfrom orders import checkout\nfrom pricing import calculate_total\nassert submit_cart([2,3], discount=2)==3\nassert checkout([2,3], discount=7)==0\nassert calculate_total([2,3], discount=1)==4\nassert submit_cart([2,3])==5",
    ),
)
