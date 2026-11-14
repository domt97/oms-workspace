"""Tests for scripts/extract_facts.py — run with: python3 -m unittest discover -s scripts/tests"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import extract_facts  # noqa: E402

PKG = "src/main/java/com/dotran/oms/demo"


def write(root: Path, relative: str, text: str) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def published(root: Path, relative: str, text: str) -> list[str]:
    java = write(root, relative, text)
    code, _ = extract_facts.strip_comments(text)
    return [p["event"] for p in extract_facts.extract_published(java, root, code)]


class PublishedEventsTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_literal_passed_to_the_outbox_builder(self) -> None:
        events = published(self.root, f"svc/{PKG}/application/event/OutboxEventHelper.java", """
            class OutboxEventHelper {
                OutboxEvent created() { return OutboxEvent.builder().eventType("ProductCreated").build(); }
                OutboxEvent updated() { return OutboxEvent.builder().eventType( "ProductUpdated" ).build(); }
            }""")
        self.assertEqual(events, ["ProductCreated", "ProductUpdated"])

    def test_builder_literal_needs_an_outbox_file(self) -> None:
        events = published(self.root, f"svc/{PKG}/infrastructure/rest/SomeMapper.java", """
            class SomeMapper { Dto map() { return Dto.builder().eventType("OrderPlaced").build(); } }""")
        self.assertEqual(events, [])

    def test_type_constants_of_outgoing_messages(self) -> None:
        events = published(self.root, f"svc/{PKG}/application/event/StockReply.java", """
            public sealed interface StockReply {
                String eventType();
                record Reserved(UUID eventId, String eventType) implements StockReply {
                    public static final String TYPE = "StockReserved";
                }
                record Rejected(UUID eventId, String eventType) implements StockReply {
                    public static final String TYPE = "StockReservationRejected";
                }
            }""")
        self.assertEqual(events, ["StockReservationRejected", "StockReserved"])

    def test_event_type_field_default_of_an_outgoing_payload(self) -> None:
        events = published(self.root, f"svc/{PKG}/domain/event/ProductCreatedEvent.java", """
            public class ProductCreatedEvent { private String eventType = "ProductCreated"; }""")
        self.assertEqual(events, ["ProductCreated"])

    def test_consumer_constant_is_not_a_published_event(self) -> None:
        events = published(self.root, f"svc/{PKG}/infrastructure/message/ReserveStockConsumer.java", """
            class ReserveStockConsumer { static final String TYPE = "ReserveStock"; }""")
        self.assertEqual(events, [])

    def test_incoming_dto_default_is_not_a_published_event(self) -> None:
        events = published(self.root, f"svc/{PKG}/infrastructure/message/dto/ProductCreatedEvent.java", """
            public class ProductCreatedEvent { private String eventType = "ProductCreated"; }""")
        self.assertEqual(events, [])

    def test_other_constants_in_the_event_package_are_ignored(self) -> None:
        events = published(self.root, f"svc/{PKG}/application/event/OutboxMessage.java", """
            public record OutboxMessage(String eventType) {
                public static final String AGGREGATE_TYPE = "StockReservation";
                static final String TYPE_HEADER = "type";
            }""")
        self.assertEqual(events, [])

    def test_type_constant_outside_the_event_packages_is_ignored(self) -> None:
        events = published(self.root, f"svc/{PKG}/application/service/ImportProductService.java", """
            class ImportProductService { static final String TYPE = "xlsx"; private String eventType = "Import"; }""")
        self.assertEqual(events, [])

    def test_the_package_rule_looks_at_the_path_inside_the_repo_only(self) -> None:
        root = self.root / "application/event/checkout"   # a checkout that happens to live under such a folder
        events = published(root, f"svc/{PKG}/infrastructure/message/ReserveStockConsumer.java", """
            class ReserveStockConsumer { static final String TYPE = "ReserveStock"; }""")
        self.assertEqual(events, [])

    def test_commented_out_declarations_are_ignored(self) -> None:
        events = published(self.root, f"svc/{PKG}/application/event/StockReply.java", """
            interface StockReply {
                // public static final String TYPE = "OldEvent";
                /* String TYPE = "OlderEvent"; */
                String TYPE = "StockReserved";
            }""")
        self.assertEqual(events, ["StockReserved"])


class ExtractServiceTest(unittest.TestCase):
    def test_published_events_are_merged_per_event_with_their_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repos = Path(tmp)
            svc = repos / "demo-service"
            write(repos, f"demo-service/{PKG}/DemoApplication.java", "@SpringBootApplication class DemoApplication {}")
            write(repos, f"demo-service/{PKG}/application/event/OutboxEventHelper.java",
                  'class OutboxEventHelper { OutboxEvent e() { return OutboxEvent.builder().eventType("ProductCreated").build(); } }')
            write(repos, f"demo-service/{PKG}/domain/event/ProductCreatedEvent.java",
                  'class ProductCreatedEvent { private String eventType = "ProductCreated"; }')
            write(repos, f"demo-service/{PKG}/application/event/StockReply.java",
                  'interface StockReply { String TYPE = "StockReserved"; }')
            write(repos, f"demo-service/{PKG}/infrastructure/message/ReserveStockConsumer.java",
                  'class ReserveStockConsumer { static final String TYPE = "ReserveStock"; }')

            self.assertTrue(extract_facts.is_service(svc))
            facts = extract_facts.extract_service(svc, repos)

            self.assertEqual([p["event"] for p in facts["published_events"]], ["ProductCreated", "StockReserved"])
            created = facts["published_events"][0]["files"]
            self.assertEqual(created, sorted(created))
            self.assertEqual(len(created), 2)
            rendered = extract_facts.render_md("demo-service", facts)
            self.assertIn("- `StockReserved` — demo-service/", rendered)
            self.assertNotIn("ReserveStock`", rendered)


class ContractCheckTest(unittest.TestCase):
    """The extractor only knows some spellings; the contract schemas say what each service should publish."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.repos = self.root / "repos"
        self.contracts = self.root / "contracts"
        write(self.repos, f"demo-service/{PKG}/DemoApplication.java", "@SpringBootApplication class DemoApplication {}")
        write(self.repos, f"demo-service/{PKG}/application/event/StockReply.java",
              'interface StockReply { String TYPE = "StockReserved"; }')
        write(self.contracts, "StockReserved.schema.json",
              '{"description": "Reply (ADR 0006). Published by demo-service through its outbox."}')
        write(self.contracts, "ReserveStock.schema.json",
              '{"description": "Command. Sent by order-service through its outbox. Consumed by demo-service."}')
        write(self.contracts, "Broken.schema.json", "not json")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def facts(self) -> dict:
        by_contract = extract_facts.contract_events(self.contracts)
        return extract_facts.extract_service(self.repos / "demo-service", self.repos, by_contract.get("demo-service"))

    def test_only_published_by_lines_are_read_from_the_contracts(self) -> None:
        self.assertEqual(extract_facts.contract_events(self.contracts), {"demo-service": ["StockReserved"]})
        self.assertEqual(extract_facts.contract_events(self.root / "missing"), {})

    def test_all_contract_events_found(self) -> None:
        facts = self.facts()
        self.assertEqual(facts["contract_events_missing"], [])
        rendered = extract_facts.render_md("demo-service", facts)
        self.assertIn("Contract check: all 1 events", rendered)
        self.assertNotIn("Contract check failed", rendered)

    def test_an_event_the_extractor_does_not_find_is_reported(self) -> None:
        write(self.contracts, "StockReleased.schema.json", '{"description": "Published by demo-service via outbox."}')
        facts = self.facts()
        self.assertEqual(facts["contract_events_missing"], ["StockReleased"])
        rendered = extract_facts.render_md("demo-service", facts)
        self.assertIn("**Contract check failed.**", rendered)
        self.assertIn("`StockReleased`", rendered)

    def test_an_event_in_code_without_a_schema_is_reported(self) -> None:
        write(self.repos, f"demo-service/{PKG}/application/event/Stray.java", 'interface Stray { String TYPE = "NotAnEvent"; }')
        schemas = extract_facts.contract_names(self.contracts)
        self.assertEqual(schemas, {"StockReserved", "ReserveStock", "Broken"})
        facts = extract_facts.extract_service(self.repos / "demo-service", self.repos, ["StockReserved"], schemas)
        self.assertEqual(facts["published_without_contract"], ["NotAnEvent"])
        rendered = extract_facts.render_md("demo-service", facts)
        self.assertIn("**No contract schema.** `NotAnEvent`", rendered)
        self.assertIn("Contract check: all 1 events", rendered)

    def test_without_a_contracts_folder_nothing_is_reported(self) -> None:
        self.assertIsNone(extract_facts.contract_names(self.root / "missing"))
        facts = extract_facts.extract_service(self.repos / "demo-service", self.repos, None, None)
        self.assertEqual(facts["published_without_contract"], [])

    def test_a_service_without_contracts_gets_no_contract_line(self) -> None:
        facts = extract_facts.extract_service(self.repos / "demo-service", self.repos)
        self.assertEqual((facts["contract_events"], facts["contract_events_missing"]), ([], []))
        self.assertNotIn("Contract check", extract_facts.render_md("demo-service", facts))


if __name__ == "__main__":
    unittest.main()
