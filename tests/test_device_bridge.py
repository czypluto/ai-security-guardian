"""
测试 DeviceBridge: JSON 协议序列化, 断连处理, 自动检测
"""

import json
import pytest
from unittest.mock import MagicMock, patch, PropertyMock, mock_open
import serial

from device_bridge import DeviceBridge, list_serial_ports


class TestJSONProtocol:
    """JSON 协议格式测试"""

    def setup_method(self):
        self.device = DeviceBridge({'mode': 'none'}, MagicMock())

    def test_update_message_format(self):
        """状态更新消息格式"""
        state = {
            'ai_status': 'working',
            'sec_level': 'safe',
            'threat_count': 0,
            'active_connections': 42,
        }
        self.device.connected = True
        self.device.mode = 'serial'
        self.device.serial_conn = MagicMock()
        self.device.serial_conn.is_open = True

        self.device.send_update(state)

        # 验证发送的是合法 JSON
        call_args = self.device.serial_conn.write.call_args[0][0]
        sent_data = call_args.decode('utf-8').strip()
        parsed = json.loads(sent_data)
        assert parsed['cmd'] == 'update'
        assert parsed['ai_status'] == 'working'
        assert parsed['sec_level'] == 'safe'

    def test_alert_message_format(self):
        """告警消息格式"""
        self.device.connected = True
        self.device.mode = 'serial'
        self.device.serial_conn = MagicMock()
        self.device.serial_conn.is_open = True

        self.device.send_alert('检测到攻击!')

        call_args = self.device.serial_conn.write.call_args[0][0]
        sent_data = call_args.decode('utf-8').strip()
        parsed = json.loads(sent_data)
        assert parsed['cmd'] == 'alert'
        assert parsed['message'] == '检测到攻击!'

    def test_custom_command(self):
        """自定义命令"""
        self.device.connected = True
        self.device.mode = 'serial'
        self.device.serial_conn = MagicMock()
        self.device.serial_conn.is_open = True

        self.device.send_command({'cmd': 'say', 'text': '你好!'})

        call_args = self.device.serial_conn.write.call_args[0][0]
        parsed = json.loads(call_args.decode('utf-8').strip())
        assert parsed['cmd'] == 'say'
        assert parsed['text'] == '你好!'

    def test_unicode_preserved(self):
        """中文/颜文字在 JSON 中正确保留"""
        self.device.connected = True
        self.device.mode = 'serial'
        self.device.serial_conn = MagicMock()
        self.device.serial_conn.is_open = True

        text_with_emoji = '主人! (｡･ω･｡) ✨'
        self.device.send_command({'cmd': 'say', 'text': text_with_emoji})

        call_args = self.device.serial_conn.write.call_args[0][0]
        parsed = json.loads(call_args.decode('utf-8').strip())
        assert parsed['text'] == text_with_emoji


class TestDisconnectedBehavior:
    """未连接状态行为"""

    def setup_method(self):
        self.device = DeviceBridge({'mode': 'none'}, MagicMock())

    def test_send_update_when_disconnected_no_error(self):
        """未连接时发送不崩溃"""
        self.device.send_update({'test': 'data'})  # 不应抛出

    def test_send_alert_when_disconnected_no_error(self):
        """未连接时告警不崩溃"""
        self.device.send_alert('test')  # 不应抛出

    def test_disconnect_cleans_up(self):
        """断开连接清理资源"""
        self.device.connected = True
        self.device.mode = 'serial'
        self.device.serial_conn = MagicMock()
        self.device.serial_conn.is_open = True

        self.device.disconnect()

        assert self.device.connected is False
        assert self.device._running is False


class TestReconnect:
    """重连逻辑"""

    def setup_method(self):
        self.device = DeviceBridge({'mode': 'serial', 'serial': {'port': 'COM99', 'baudrate': 115200}}, MagicMock())

    def test_max_reconnects_exhausted(self):
        """重连次数耗尽后停止"""
        self.device._reconnect_count = 11
        self.device._max_reconnects = 10

        self.device._handle_disconnect()
        # 应该只记录错误而不是无限重连
        assert self.device.connected is False

    def test_reconnect_resets_counter_on_success(self):
        """重连成功后重置计数器"""
        self.device._reconnect_count = 2
        self.device._max_reconnects = 10
        self.device.connected = False

        # Mock 串口对象
        mock_serial = MagicMock()
        mock_serial.port = 'COM99'

        def fake_connect():
            self.device.serial_conn = mock_serial
            return True

        with patch.object(self.device, '_connect_serial', side_effect=fake_connect):
            self.device._handle_disconnect()
            assert self.device._reconnect_count == 0
            assert self.device.connected is True
