"""Parser tests for the VFS page text extractor."""

import unittest

from monitor import extract_appointment_details


class TestVfsParser(unittest.TestCase):
    def test_day_month_year_with_time(self):
        text = 'Appointments available\nSelect date: 12 October 2026 09:30\nTehran'
        result = extract_appointment_details(text)
        self.assertEqual(result['text'], '12-10-2026 09:30')
        self.assertEqual(result['datetime_iso'], '2026-10-12T09:30:00')

    def test_numeric_date_without_time(self):
        text = 'Earliest available appointment 13/10/2026'
        result = extract_appointment_details(text)
        self.assertEqual(result['text'], '13-10-2026')
        self.assertEqual(result['datetime_iso'], '2026-10-13T00:00:00')

    def test_month_first_date(self):
        text = 'October 14, 2026 11:45 is available'
        result = extract_appointment_details(text)
        self.assertEqual(result['text'], '14-10-2026 11:45')

    def test_iso_date(self):
        text = 'Slot: 2026-10-15 08:15'
        result = extract_appointment_details(text)
        self.assertEqual(result['text'], '15-10-2026 08:15')

    def test_availability_without_parsable_date(self):
        text = 'Book appointment\nPlease select date to continue'
        result = extract_appointment_details(text)
        self.assertIn('Availability detected', result['text'])

    def test_no_details_found(self):
        text = 'Welcome to the appointment system'
        result = extract_appointment_details(text)
        self.assertIn('Details not found', result['text'])

    def test_empty_page(self):
        result = extract_appointment_details('')
        self.assertIn('empty page', result['text'])

    def test_location_is_reported(self):
        result = extract_appointment_details('Select date: 12 October 2026')
        self.assertTrue(result['location'])


if __name__ == '__main__':
    unittest.main()
