"""Live CLI routing uses an actual input descriptor and the retained store."""

from contextlib import redirect_stdout, redirect_stderr
from datetime import datetime, timedelta, timezone
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from sociolab.cli import main
from sociolab.events import EventDataset
from sociolab.tracking_store import initialize_tracking_store, inspect_tracking_store
from test_tracking_store import inputs, batch, saved_bytes
from test_temporal_tracking_store import temporal_inputs


def utc_inputs():
    dataset, registration = temporal_inputs()
    data = dataset.to_dict()
    epoch = datetime(2020, 1, 1, tzinfo=timezone.utc)

    def stamp(tick):
        return (epoch + timedelta(seconds=tick)).isoformat().replace('+00:00', 'Z')

    data['clock'] = {'kind': 'utc'}
    for record in data['records']:
        record['occurred_at'] = stamp(record['occurred_at'])
        if record['valid_interval'] is not None:
            record['valid_interval'] = [stamp(x) if x is not None else None for x in record['valid_interval']]
    registration['initial_cursor'] = stamp(5)
    registration['source_time_unit'] = 'microsecond'
    return EventDataset.from_mapping(data), registration


def utc_batch():
    request = batch()
    request['records'][0]['occurred_at'] = '2020-01-01T00:00:01Z'
    return request


class LiveTrackingCliTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.store = self.root / 'live'
        self.initial = initialize_tracking_store(self.store, *utc_inputs())

    def invoke(self, arguments, source=b'', *, expected_exit=None):
        read_fd, write_fd = os.pipe()
        os.write(write_fd, source)
        os.close(write_fd)
        output, error = io.StringIO(), io.StringIO()
        with os.fdopen(read_fd, 'r', encoding='utf-8') as stream:
            with redirect_stdout(output), redirect_stderr(error), patch('sys.stdin', stream):
                if expected_exit is None:
                    self.assertEqual(main(arguments), 0)
                else:
                    with self.assertRaises(SystemExit) as failed:
                        main(arguments)
                    self.assertEqual(failed.exception.code, expected_exit)
        return output.getvalue(), error.getvalue()

    def test_real_fd_eof_accepts_final_batch_without_newline_and_holds_cursor(self):
        source = json.dumps(utc_batch()).encode('utf-8')
        output, error = self.invoke(['tracking', 'live', str(self.store), '--interval-ms', '60000'], source)
        self.assertEqual(error, '')
        receipts = [json.loads(line) for line in output.splitlines()]
        self.assertEqual(len(receipts), 1)
        receipt = receipts[0]
        self.assertEqual(receipt['transition_cause'], 'receipt_batch')
        self.assertEqual(receipt['status'], 'APPLIED')
        self.assertEqual(receipt['knowledge_cutoff'], self.initial['knowledge_cutoff'] + 1)
        self.assertEqual(receipt['cursor'], self.initial['cursor'])
        self.assertEqual(inspect_tracking_store(self.store)['checkpoint_hash'], receipt['checkpoint_hash'])

    def test_manual_advance_rejected_after_prior_batch_without_losing_that_commit(self):
        request = {'schema': 'sociolab.network-tracking-advance.v1', 'cursor': '2020-01-01T00:00:06Z'}
        source = (json.dumps(utc_batch()) + '\n' + json.dumps(request) + '\n').encode('utf-8')
        output, error = self.invoke(['tracking', 'live', str(self.store), '--interval-ms', '60000'], source, expected_exit=2)
        self.assertIn('line 2', error)
        self.assertEqual(len(output.splitlines()), 1)
        head = inspect_tracking_store(self.store)
        self.assertEqual(head['knowledge_cutoff'], self.initial['knowledge_cutoff'] + 1)
        self.assertEqual(head['cursor'], self.initial['cursor'])

    def test_live_rejects_fixed_and_ticks_stores_before_accepting_input(self):
        for name, args in [('fixed', inputs()), ('ticks', temporal_inputs())]:
            with self.subTest(profile=name):
                store = self.root / name
                initialize_tracking_store(store, *args)
                before = saved_bytes(store)
                output, error = self.invoke(['tracking', 'live', str(store)], json.dumps(batch()).encode(), expected_exit=2)
                self.assertEqual(output, '')
                self.assertTrue(error)
                self.assertEqual(saved_bytes(store), before)

    def test_invalid_interval_options_never_modify_store(self):
        before = saved_bytes(self.store)
        for interval in ['0', '-1', '86400001', '1.5', 'true']:
            with self.subTest(interval=interval):
                output, error = self.invoke(['tracking', 'live', str(self.store), '--interval-ms', interval], expected_exit=2)
                self.assertEqual(output, '')
                self.assertTrue(error)
                self.assertEqual(saved_bytes(self.store), before)


if __name__ == '__main__':
    unittest.main()
