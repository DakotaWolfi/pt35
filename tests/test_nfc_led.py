"""LED socket, serpentine mapping and lease tests with no GPIO access."""
import socket
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'nfc'), str(ROOT / 'services')]

import pt35_led_daemon as led
from nfc_led import NFCLeds

TOKEN = '0123456789abcdef'


def send(path, command):
    with socket.socket(socket.AF_UNIX) as client:
        client.settimeout(1)
        client.connect(str(path))
        client.sendall((command + '\n').encode())
        return client.recv(256).decode().strip()


class StateTests(unittest.TestCase):
    def setUp(self):
        self.now = 10
        self.state = led.LEDState(clock=lambda: self.now, battery=lambda: (50, 3.7), haptic=lambda _: None)
        self.addCleanup(self.state.close)

    def test_progress_mapping_and_release_restore_previous_mode(self):
        self.state.command('color 1 2 3')
        self.assertEqual(self.state.command(f'nfc {TOKEN} sweep 12 read 7 16'), 'OK')
        frame = self.state.frame()
        self.assertEqual({i for i, color in enumerate(frame) if color != (0, 0, 0)},
                         {0, 1, 2})
        self.assertEqual(self.state.command(f'nfc {TOKEN} sweep 12 read 16 16'), 'OK')
        self.assertEqual(self.state.frame(), ((0, 12, 3),) * 8 + led.BLACK[8:])
        self.state.command(f'nfc {TOKEN} release')
        self.assertEqual(self.state.frame(), ((1, 2, 3),) * 16)

    def test_top_progress_and_bottom_technology_mapping(self):
        self.assertEqual(self.state.command(f'nfc {TOKEN} sweep 12 read 3 8 ISO15693 15'), 'OK')
        frame = self.state.frame()
        self.assertEqual([i for i in range(8) if frame[i] != led.BLACK[i]], [0, 1, 2])
        self.assertEqual([i for i in led.BOTTOM_LEFT_TO_RIGHT if frame[i] != led.BLACK[i]],
                         list(led.BOTTOM_LEFT_TO_RIGHT))
        self.assertEqual(self.state.command(f'nfc {TOKEN} sweep 12 scan 0 0 NFC-A -1'), 'OK')
        frame = self.state.frame()
        self.assertEqual([i for i in led.BOTTOM_LEFT_TO_RIGHT if frame[i] != led.BLACK[i]], [15])
        self.assertGreater(frame[15][1], frame[15][0])
        self.assertEqual(self.state.command(f'nfc {TOKEN} sweep 12 read 2 8 NFC-B 4'), 'OK')
        frame = self.state.frame()
        self.assertEqual([i for i in led.BOTTOM_LEFT_TO_RIGHT if frame[i] != led.BLACK[i]], [15, 14, 13])
        self.assertGreater(frame[15][0], frame[15][2])
        self.assertEqual(self.state.command(f'nfc {TOKEN} sweep 12 scan 0 0 ISO15693 16'),
                         'ERR invalid NFC signal')

    def test_rssi_zero_is_no_bar_not_a_fake_minimum(self):
        self.state.command(f'nfc {TOKEN} minimal 12 scan 0 0 NFC-F 0')
        self.assertEqual([i for i in led.BOTTOM_LEFT_TO_RIGHT if self.state.frame()[i] != led.BLACK[i]], [])

    def test_lost_process_lease_expires_and_other_clients_cannot_override_it(self):
        self.state.command('rainbow')
        self.state.command(f'nfc {TOKEN} minimal 12 read 3 0')
        self.assertEqual(self.state.frame()[0], (0, 0, 4))
        self.assertEqual(self.state.command('nfc 0000000000000000 release'), 'ERR NFC lease busy')
        self.now += led.LEASE_SECONDS
        frame = self.state.frame()
        self.assertIsNone(self.state.lease)
        self.assertGreater(sum(color != (0, 0, 0) for color in frame), 1)

    def test_index_test_is_dim_and_legacy_off_has_priority(self):
        self.assertEqual(self.state.command('nfc-test'), 'OK')
        for index in range(16):
            self.now = 10 + (index + .1) * led.INDEX_SECONDS
            self.assertEqual([i for i, c in enumerate(self.state.frame()) if c != (0, 0, 0)], [index])
        self.state.command('off')
        self.assertEqual(self.state.command(f'nfc {TOKEN} pulse 32 scan 0 0'), 'OK')
        self.assertEqual(self.state.frame(), led.BLACK)
        self.assertEqual(self.state.command(f'nfc {TOKEN} pulse 255 scan 0 0'), 'ERR invalid NFC frame')

    def test_battery_and_flash_restore_base_mode(self):
        self.state.command('color 1 2 3')
        self.state.command('battery')
        self.state.battery_job.result(timeout=1)
        self.assertEqual(sum(pixel != led.BLACK[0] for pixel in self.state.frame()), 8)
        self.now += 3
        self.assertEqual(self.state.frame()[0], (1, 2, 3))
        self.state.command('flash 10 0 0')
        self.assertEqual(self.state.frame()[0], (10, 0, 0))
        self.now += .5
        self.assertEqual(self.state.frame()[0], (1, 2, 3))


class SocketTests(unittest.TestCase):
    def wait(self, condition):
        end = time.monotonic() + 2
        while time.monotonic() < end:
            if condition():
                return
            time.sleep(.02)
        self.fail('LED state change timed out')

    def test_socket_command_can_arrive_in_separate_chunks(self):
        request = Mock()
        request.recv.side_effect = [b'nfc 0123456789', b'abcdef pulse 12 read ', b'5 8\n']
        state = Mock()
        state.command.return_value = 'OK'
        led.LEDRequest(request, None, SimpleNamespace(state=state))
        state.command.assert_called_once_with(f'nfc {TOKEN} pulse 12 read 5 8')
        request.sendall.assert_called_once_with(b'OK\n')

    def test_live_socket_and_client_release_have_single_render_owner(self):
        try:
            with socket.socket(socket.AF_UNIX):
                pass
        except PermissionError:
            self.skipTest('Unix sockets are blocked in this environment')
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'led.sock'
            stopped = threading.Event()
            state = led.LEDState(battery=lambda: (70, 3.9), haptic=lambda _: None)
            frames = []
            renderer = threading.Thread(target=led.serve, args=(
                path, state, lambda frame: frames.append((threading.get_ident(), frame)), stopped))
            client = NFCLeds(path)
            renderer.start()
            try:
                self.wait(path.exists)
                self.assertEqual(send(path, 'color 1 2 3'), 'OK')
                self.assertIn('mode=solid', send(path, 'status'))
                client.start('minimal', 12)
                self.wait(lambda: state.lease is not None)
                client.reading(4, 8)
                self.wait(lambda: state.lease and state.lease.completed == 4)
                client.stop()
                self.wait(lambda: state.lease is None)
                self.wait(lambda: frames and frames[-1][1][0] == (1, 2, 3))
            finally:
                client.close()
                client.thread.join(2)
                stopped.set()
                renderer.join(2)
                state.close()
            self.assertFalse(path.exists())
            self.assertEqual({owner for owner, _ in frames}, {renderer.ident})
            self.assertEqual(frames[-1][1], led.BLACK)

    def test_fake_socket_exchanges_with_the_daemon_handler(self):
        state = led.LEDState(battery=lambda: (70, 3.9), haptic=lambda _: None)
        messages = []

        def socket_factory(*_):
            connection = Mock()
            connection.__enter__ = Mock(return_value=connection)
            connection.__exit__ = Mock(return_value=False)

            def transact(data):
                request = Mock()
                request.recv.return_value = data
                led.LEDRequest(request, None, SimpleNamespace(state=state))
                connection.recv.return_value = request.sendall.call_args.args[0]
                messages.append(data.decode())
            connection.sendall.side_effect = transact
            return connection

        with patch('nfc_led.socket', SimpleNamespace(socket=socket_factory, AF_UNIX=socket.AF_UNIX)):
            client = NFCLeds('/fake/pt35-led.sock')
            try:
                client.start('pulse', 12)
                self.wait(lambda: state.lease is not None)
                client.reading(5, 8)
                self.wait(lambda: state.lease and state.lease.completed == 5)
                client.result('partial')
                self.wait(lambda: state.lease and state.lease.stage == 'partial')
                client.stop()
                self.wait(lambda: state.lease is None)
            finally:
                client.close()
                client.thread.join(2)
                state.close()
        self.assertIn('pulse 12 read 5 8 none -1', ''.join(messages))
        self.assertTrue(messages[-1].endswith('release\n'))

    def test_missing_socket_does_not_raise_in_caller(self):
        with tempfile.TemporaryDirectory() as directory:
            client = NFCLeds(Path(directory) / 'missing')
            try:
                client.start('sweep', 12)
                self.wait(lambda: client.status == 'NFC LED service unavailable')
            finally:
                client.close()
                client.thread.join(2)
