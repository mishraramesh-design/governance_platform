import json
import unittest
from io import BytesIO

from pydantic import ValidationError
from workspace_core import BrowserAction, Plan, extract_document, deterministic_plan, validate_plan, origin, json_object


class WorkspaceCoreTests(unittest.TestCase):
    def test_origin_canonicalization_and_unsafe_urls(self):
        self.assertEqual(origin('https://Example.com/path'), 'https://example.com:443')
        self.assertEqual(origin('http://example.com:5021/'), 'http://example.com:5021')
        for url in ('file:///etc/passwd', 'javascript:alert(1)', 'https://user:pass@example.com/', 'https://example.com\\@internal/', 'http://example.com\n/'):
            with self.assertRaises(ValueError): origin(url)

    def test_documents_have_hashes_and_line_provenance(self):
        sources, metadata = extract_document('srs.txt', b'REQ-1 User shall see Dashboard after login.\nREQ-2 User shall log out.', 'DOC1')
        self.assertEqual(sources[0]['id'], 'DOC1-L1')
        self.assertEqual(sources[1]['location'], 'line 2')
        self.assertEqual(len(metadata['sha256']), 64)
        self.assertFalse(metadata['raw_retained'])

    def test_excel_formulas_omitted_and_sheet_rows_preserved(self):
        from openpyxl import Workbook
        book = Workbook(); sheet = book.active; sheet.title = 'Registration'
        sheet.append(['ID', 'Steps', 'Expected'])
        sheet.append(['TC-9', 'Open registration', 'Registration form is shown'])
        sheet.append(['TC-10', '=HYPERLINK("https://evil.example", "run")', 'Do not execute formulas'])
        output = BytesIO(); book.save(output)
        sources, metadata = extract_document('cases.xlsx', output.getvalue(), 'DOC2')
        self.assertEqual(sources[0]['location'], 'Registration!2')
        self.assertEqual(sources[0]['id'], 'DOC2-S1-R2')
        self.assertIn('Expected: Registration form is shown', sources[0]['text'])
        self.assertIn('[formula omitted]', sources[1]['text'])
        self.assertNotIn('evil.example', json.dumps(sources))
        self.assertEqual(metadata['source_count'], 2)

    def test_no_code_execution_action_or_model_pass_action(self):
        for op in ('evaluate', 'shell', 'python', 'pass', 'finish', 'execute'):
            with self.assertRaises(ValidationError): BrowserAction(op=op)
        with self.assertRaises(ValidationError): BrowserAction(op='click', script='alert(1)')

    def test_browser_values_preserve_whitespace_for_credentials(self):
        self.assertEqual(BrowserAction(op='fill', value='  exact password  ').value, '  exact password  ')

    def test_unknown_trace_links_and_duplicate_test_ids_are_rejected(self):
        sources = [{'id': 'DOC1-L1', 'text': 'The dashboard shall be visible.'}]
        plan = deterministic_plan(sources)
        validate_plan(plan, sources)
        plan['cases'][0]['source_ids'] = ['invented']
        with self.assertRaises(ValueError): validate_plan(plan, sources)
        plan = deterministic_plan(sources)
        plan['cases'].append(dict(plan['cases'][0]))
        with self.assertRaises(ValidationError): Plan.model_validate(plan)

    def test_zero_model_draft_never_invents_execution_or_assertions(self):
        plan = deterministic_plan([{'id': 'R1', 'text': 'User shall be able to sign in.'}])
        self.assertNotIn('oracle', plan['cases'][0])
        self.assertNotIn('verdict', plan['cases'][0])
        self.assertIn('Owner must specify', plan['cases'][0]['expected'])

    def test_only_json_objects_and_bounded_uploads_are_accepted(self):
        self.assertEqual(json_object('```json\n{"cases": []}\n```'), {'cases': []})
        with self.assertRaises(ValueError): json_object('["not a plan"]')
        with self.assertRaises(ValueError): extract_document('huge.txt', b'x' * 2_000_001, 'D1')
        with self.assertRaises(ValueError): extract_document('test.exe', b'no', 'D1')


if __name__ == '__main__': unittest.main()
