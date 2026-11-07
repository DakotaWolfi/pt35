"""Offline launcher regression tests. No Tk window, GPIO, RF or I2C required."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))

import pt35_launcher as launcher


class LaunchTests(unittest.TestCase):
    def test_all_launcher_entries_stay_in_git_checkout(self):
        tag = launcher.target_command('tag')
        reader = launcher.target_command('reader')
        spectrum = launcher.target_command('spectrum')
        self.assertEqual(Path(tag[-1]), ROOT / 'nfc/pt35_i2c_tag_gui.py')
        self.assertEqual(Path(reader[-1]), ROOT / 'nfc/pt35_nfc_gui.py')
        self.assertEqual(Path(spectrum[1]), ROOT / 'tools/pt35_tools.py')
        with self.assertRaises(ValueError):
            launcher.target_command('unrecognized')

    def test_lra_test_commands_are_bounded_and_noncontinuous(self):
        self.assertEqual(launcher.lra_command('status'), ['/usr/local/bin/lra_ctl', 'status'])
        self.assertEqual(launcher.lra_command('play', 10),
                         ['/usr/local/bin/lra_ctl', 'play', '10'])
        self.assertEqual(launcher.lra_command('stop'), ['/usr/local/bin/lra_ctl', 'stop'])
        for action, effect in (('rtp', 80), ('play', 123), ('play', -1),
                               ('test', None), ('play', '10')):
            with self.assertRaises(ValueError):
                launcher.lra_command(action, effect)

    def test_recent_archive_reads_without_touching_hardware(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for uid, ts in (('E004030000000001', '2026-11-06'), ('E004030000000002', '2026-11-07')):
                folder = root / uid
                folder.mkdir()
                (folder / 'record.json').write_text(json.dumps({'uid': uid, 'protocol': 'ISO15693',
                                                                 'last_seen_utc': ts}))
            records = launcher.latest_tag_records(root)
            self.assertEqual(records[0]['uid'], 'E004030000000002')
            self.assertEqual(len(launcher.latest_tag_records(root, limit=1)), 1)

    def test_led_commands_cannot_modify_persistent_color_or_gpio(self):
        self.assertNotIn('color 255 255 255', launcher.LED_COMMANDS)
        self.assertNotIn('off', launcher.LED_COMMANDS)
        self.assertNotIn('rainbow', launcher.LED_COMMANDS)
        for command in ('color 1 1 1', 'nfc abcd release', 'restart', 'off'):
            with self.assertRaises(ValueError):
                launcher.led_command(command)

    def test_led_socket_short_reply(self):
        conn = Mock()
        conn.__enter__ = Mock(return_value=conn)
        conn.__exit__ = Mock(return_value=False)
        conn.recv.return_value = b'OK\n'
        with patch.object(launcher.socket, 'socket', return_value=conn):
            self.assertEqual(launcher.led_command('nfc-test'), 'OK')
        conn.sendall.assert_called_once_with(b'nfc-test\n')

    def test_daemon_error_is_reported(self):
        conn = Mock()
        conn.__enter__ = Mock(return_value=conn)
        conn.__exit__ = Mock(return_value=False)
        conn.recv.return_value = b'ERR NFC scan active\n'
        with patch.object(launcher.socket, 'socket', return_value=conn):
            with self.assertRaisesRegex(RuntimeError, 'scan active'):
                launcher.led_command('nfc-test')


if __name__ == '__main__':
    unittest.main()
