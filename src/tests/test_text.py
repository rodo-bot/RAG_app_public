import unittest

from ragkb.text import clean_text, detect_entities, fts_query, normalize_identifier, search_variants


class TextTests(unittest.TestCase):
    def test_clean_text_removes_invalid_unicode_surrogates(self):
        cleaned = clean_text("Motor\udc26 drive")
        self.assertEqual(cleaned, "Motor drive")
        cleaned.encode("utf-8")

    def test_normalizes_equipment_identifier(self):
        self.assertEqual(normalize_identifier("LIT 0101"), "LIT0101")
        self.assertEqual(normalize_identifier("10001-SITE-P&ID-03"), "10001SITEPID03")

    def test_appends_compact_search_variant(self):
        value = search_variants("Tank level is measured by LIT 0101")
        self.assertIn("LIT0101", value)

    def test_detects_instrument_tag(self):
        entities = detect_entities("Signal from AIT-0102 is monitored by the PLC.")
        self.assertTrue(any(item.normalized_value == "AIT0102" for item in entities))

    def test_fts_expression_is_quoted(self):
        self.assertEqual(fts_query("pump 1 phase fail"), '("pump" AND "1" AND "phase" AND "fail") OR "PUMP1PHASEFAIL"')

    def test_detects_unhyphenated_model(self):
        entities = detect_entities("Install the new RedLion G10S1000 OIT.")
        self.assertTrue(any(item.normalized_value == "G10S1000" for item in entities))

    def test_does_not_duplicate_tags_as_models(self):
        entities = detect_entities("LIT-0101 and AIT 0102")
        normalized = [item.normalized_value for item in entities]
        self.assertEqual(normalized.count("LIT0101"), 1)
        self.assertEqual(normalized.count("AIT0102"), 1)

    def test_rejects_long_concatenated_table_token(self):
        entities = detect_entities("10024VDC4BMXAMO0410345th")
        self.assertFalse(any(item.entity_type == "model_or_drawing" for item in entities))


if __name__ == "__main__":
    unittest.main()
