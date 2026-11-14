"""Tests for scripts/extract_other.py — run with: python3 -m unittest discover -s scripts/tests"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import extract_other as eo  # noqa: E402

ADAPTER = """
const BASE = '/v1/store';
const m = (merchantId: string) => `${BASE}/merchants/${encodeURIComponent(merchantId)}`;
const s = (merchantId: string, storeId: string) => `${m(merchantId)}/stores/${encodeURIComponent(storeId)}`;
export function create(http: HttpClient) {
  return {
    register: async (code) => toMerchant(await http.post<MerchantDto>(`${BASE}/merchants`, { code })),
    get: async (merchantId) => toMerchant(await http.get<MerchantDto>(m(merchantId))),
    list: async (a, b) => toPage(await http.get<PagedResult<Preview>>(`${s(a, b)}/products/search`, { page: 1 })),
    one: async (a, b, productId) => http.get<P>(`${s(a, b)}/products/${encodeURIComponent(productId)}`),
    cancel: async (a, b, x) => { await http.post<void>(`${s(a, b)}/availability/${encodeURIComponent(x.id)}/cancel`); },
    plain: async () => http.get('/v1/store/ping'),
  };
}
"""


def write(root: Path, relative: str, text: str) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


class WebCallsTest(unittest.TestCase):
    def test_resolves_constants_helpers_and_parameters(self) -> None:
        calls = {(c["method"], c["path"]) for c in eo.web_calls(ADAPTER)}
        self.assertEqual(calls, {
            ("POST", "/v1/store/merchants"),
            ("GET", "/v1/store/merchants/{merchantId}"),
            ("GET", "/v1/store/merchants/{merchantId}/stores/{storeId}/products/search"),
            ("GET", "/v1/store/merchants/{merchantId}/stores/{storeId}/products/{productId}"),
            ("POST", "/v1/store/merchants/{merchantId}/stores/{storeId}/availability/{id}/cancel"),
            ("GET", "/v1/store/ping"),
        })

    def test_shape_ignores_parameter_names(self) -> None:
        self.assertEqual(eo.shape("/a/{id}/b/{x}"), eo.shape("/a/{productId}/b/{y}"))
        self.assertNotEqual(eo.shape("/a/{id}"), eo.shape("/a/{id}/b"))

    def test_calls_are_matched_to_service_endpoints(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "oms-web"
            write(repo, "src/adapters/http/stores/storesService.ts", ADAPTER)
            write(repo, "src/adapters/http/stores/storesService.test.ts", "http.get('/v1/store/only-in-test')")
            write(repo, "src/ports/index.ts", "export interface CartPort {}\nexport interface Helper {}\nexport interface StorePort {}\n")
            services = {"stores-service": {"rest": [
                {"method": "POST", "path": "/v1/store/merchants", "handler": "M#register", "visibility": "public"},
                {"method": "GET", "path": "/v1/store/merchants/{id}", "handler": "M#get", "visibility": "public"},
                {"method": "GET", "path": "/v1/store/merchants/{merchantId}/stores/{storeId}/products/search", "handler": "P#search", "visibility": "public"},
                # same path, other method: must not count as a match for the GET
                {"method": "PUT", "path": "/v1/store/merchants/{merchantId}/stores/{storeId}/products/{productId}", "handler": "P#update", "visibility": "public"},
            ]}}
            facts = eo.extract_web(repo, services)
        self.assertEqual(facts["ports"], ["CartPort", "StorePort"])
        self.assertEqual(len(facts["calls"]), 6)
        self.assertEqual(sorted(facts["calls_without_endpoint"]), [
            "GET /v1/store/merchants/{merchantId}/stores/{storeId}/products/{productId}",
            "GET /v1/store/ping",
            "POST /v1/store/merchants/{merchantId}/stores/{storeId}/availability/{id}/cancel",
        ])
        by_path = {(c["method"], c["path"]): c for c in facts["calls"]}
        self.assertEqual(by_path[("GET", "/v1/store/merchants/{merchantId}")]["handler"], "M#get")
        md = eo.render_web("oms-web", facts, "develop")
        self.assertIn("Endpoint check failed", md)
        self.assertIn("**not found**", md)

    def test_all_matched_says_so(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "oms-web"
            write(repo, "src/adapters/http/a.ts", "const x = () => http.get<X>('/v1/a');")
            facts = eo.extract_web(repo, {"svc": {"rest": [{"method": "GET", "path": "/v1/a", "handler": "A#a", "visibility": "public"}]}})
        self.assertEqual(facts["calls_without_endpoint"], [])
        self.assertIn("all 1 calls match", eo.render_web("oms-web", facts, "develop"))


class CoreTest(unittest.TestCase):
    def test_version_and_public_types_per_package(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "oms-core"
            write(repo, "gradle.properties", "group=com.dotran.oms\n# comment\nversion=1.2.3\n")
            base = "src/main/java/com/dotran/oms/core"
            write(repo, f"{base}/valueobject/Money.java", "public final class Money {}")
            write(repo, f"{base}/annotation/UseCase.java", "public @interface UseCase {}")
            write(repo, f"{base}/domain/id/BaseId.java", "public abstract class BaseId<T> {}")
            write(repo, f"{base}/domain/id/Hidden.java", "class Hidden {}")
            facts = eo.extract_core(repo)
        self.assertEqual(facts["version"], "1.2.3")
        self.assertEqual(facts["packages"], {"annotation": ["UseCase"], "domain.id": ["BaseId"], "valueobject": ["Money"]})


class DevelopmentTest(unittest.TestCase):
    COMPOSE = """services:
  kafka:
    image: confluentinc/cp-kafka:7.3.0
    ports:
      - 9092:9092
      - "9997:9997"
#  old:
#    image: gone
  kafka-connect:
    build:
      context: ./kafka-connect
    ports:
      - "9084:9084"
  localstack:
    image: localstack/localstack:3.8.1
    ports:
      - '4566-4597:4566-4597'
volumes:
  kafka_data:
"""

    def test_lists_what_the_local_stack_defines(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "development"
            write(repo, "docker/docker-compose.yml", self.COMPOSE)
            write(repo, "docker/kafka/create-topics.sh", "TOPICS=(\n  # replies\n  StockReserved StockReservationRejected\n  ReserveStock  # command\n)\nfoo\n")
            write(repo, "docker/kafka-connect/connectors/postgres-cdc.json", '{"database.dbname": "store", "slot.name": "s1", "publication.name": "p1"}')
            write(repo, "docker/kafka-connect/connectors/broken.json", "{not json")
            write(repo, "docker/infra/local/main.tf", 'resource "aws_sqs_queue" "q" {\n}\nresource "aws_s3_bucket" "b" {\n}\n')
            facts = eo.extract_development(repo)
        self.assertEqual([(s["name"], s["image"], s["ports"]) for s in facts["compose_services"]], [
            ("kafka", "confluentinc/cp-kafka:7.3.0", ["9092", "9997"]),
            ("kafka-connect", None, ["9084"]),
            ("localstack", "localstack/localstack:3.8.1", ["4566-4597"]),
        ])
        self.assertEqual(facts["topics"], ["ReserveStock", "StockReservationRejected", "StockReserved"])
        self.assertEqual(facts["connectors"], [
            {"name": "broken", "database": None, "slot": None, "publication": None},
            {"name": "postgres-cdc", "database": "store", "slot": "s1", "publication": "p1"},
        ])
        self.assertEqual(facts["localstack_resources"], [{"type": "aws_s3_bucket", "name": "b"}, {"type": "aws_sqs_queue", "name": "q"}])
        self.assertIn("Nothing here is checked", eo.render_development("development", facts, "master"))

    def test_missing_folders_give_empty_lists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            facts = eo.extract_development(Path(tmp))
        self.assertEqual((facts["compose_services"], facts["topics"], facts["connectors"], facts["localstack_resources"]), ([], [], [], []))


if __name__ == "__main__":
    unittest.main()
