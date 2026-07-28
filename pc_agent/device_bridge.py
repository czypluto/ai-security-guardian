"""
设备通信桥 —— 与 ESP32 设备通信
支持 Serial (USB) 和 WiFi 两种模式
"""

import json
import time
import logging
import threading
from typing import Optional

import serial
import serial.tools.list_ports


class DeviceBridge:
    """ESP32 设备通信管理"""

    def __init__(self, config: dict, logger: logging.Logger):
        self.config = config
        self.logger = logger
        self.mode = config.get('mode', 'auto')
        self.serial_conn: Optional[serial.Serial] = None
        self.wifi_sock = None
        self.connected = False
        self.lock = threading.Lock()
        self._reconnect_lock = threading.Lock()  # 防止并发重连
        self._reconnect_count = 0
        self._max_reconnects = 10
        self._heartbeat_thread = None
        self._reader_thread = None
        self._running = False

    def connect(self) -> bool:
        """自动选择模式连接设备"""
        if self.mode == 'none':
            self.logger.info("设备连接已禁用")
            return False

        # 尝试 Serial 模式
        if self.mode in ('serial', 'auto'):
            if self._connect_serial():
                self.connected = True
                self.mode = 'serial'
                self.logger.info(f"✅ 通过 Serial 连接设备: {self.serial_conn.port}")
                self._start_background_tasks()
                return True

        # 尝试 WiFi 模式
        if self.mode in ('wifi', 'auto'):
            if self._connect_wifi():
                self.connected = True
                self.mode = 'wifi'
                self.logger.info(f"✅ 通过 WiFi 连接设备: {self.config.get('wifi', {}).get('host')}")
                self._start_background_tasks()
                return True

        self.logger.warning("⚠️  无法连接到设备")
        return False

    def _connect_serial(self) -> bool:
        """连接 Serial 端口"""
        serial_cfg = self.config.get('serial', {})
        port = serial_cfg.get('port', 'auto')
        baudrate = serial_cfg.get('baudrate', 115200)

        # 自动检测 ESP32 端口
        if port == 'auto':
            port = self._find_esp32_port()
            if not port:
                return False

        try:
            self.serial_conn = serial.Serial(
                port=port,
                baudrate=baudrate,
                timeout=1,
                write_timeout=1
            )
            # 等待 ESP32 启动
            time.sleep(1)

            # 清空缓冲区
            self.serial_conn.reset_input_buffer()
            self.serial_conn.reset_output_buffer()

            # 读启动消息
            startup = self._read_line(timeout=3)
            if startup and 'ready' in startup:
                self.logger.debug(f"设备启动消息: {startup}")
                return True

            # 发送 ping 确认
            self._write_line(json.dumps({"cmd": "ping"}))
            response = self._read_line(timeout=2)
            if response and 'pong' in response:
                return True

            return True  # 即使没收到响应也尝试继续

        except serial.SerialException as e:
            self.logger.debug(f"Serial 连接失败: {e}")
            return False

    def _find_esp32_port(self) -> Optional[str]:
        """自动检测 ESP32 的 COM 端口"""
        ports = serial.tools.list_ports.comports()
        for p in ports:
            # ESP32 通常显示为 CP210x, CH340, Silicon Labs
            desc_lower = (p.description + p.manufacturer).lower()
            if any(kw in desc_lower for kw in [
                'cp210', 'ch340', 'ch341', 'silicon',
                'esp32', 'wch', 'qinheng'
            ]):
                self.logger.info(f"🔍 检测到 ESP32: {p.device} ({p.description})")
                return p.device

        # 如果检测不到，列出所有端口让用户手动选择
        if ports:
            self.logger.warning("未检测到 ESP32，可用端口:")
            for p in ports:
                self.logger.warning(f"  {p.device}: {p.description}")
            # 返回第一个可用端口作为备选
            return ports[0].device

        return None

    def _connect_wifi(self) -> bool:
        """连接 WiFi (WebSocket)"""
        wifi_cfg = self.config.get('wifi', {})
        host = wifi_cfg.get('host', '192.168.1.100')
        port = wifi_cfg.get('port', 8080)

        try:
            import socket
            self.wifi_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.wifi_sock.settimeout(5)
            self.wifi_sock.connect((host, port))
            self.wifi_sock.settimeout(1)

            # 发送 ping
            self._wifi_write(json.dumps({"cmd": "ping"}) + '\n')
            time.sleep(0.5)
            response = self._wifi_read()
            if response and 'pong' in response:
                return True
            return True

        except Exception as e:
            self.logger.debug(f"WiFi 连接失败: {e}")
            return False

    # ==================== 后台保活线程 ====================

    def _start_background_tasks(self):
        """启动心跳 + 串口消费后台线程"""
        self._running = True
        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop, name="DeviceHeartbeat", daemon=True)
        self._heartbeat_thread.start()

        if self.mode == 'serial':
            self._reader_thread = threading.Thread(
                target=self._serial_reader_loop, name="SerialReader", daemon=True)
            self._reader_thread.start()

    def _heartbeat_loop(self):
        """每 2 秒发送 ping 保活，防止固件超时"""
        while self._running and self.connected:
            try:
                if self.mode == 'serial':
                    self._write_line(json.dumps({"cmd": "ping"}, ensure_ascii=True))
                elif self.mode == 'wifi':
                    self._wifi_write(json.dumps({"cmd": "ping"}, ensure_ascii=True) + '\n')
            except Exception as e:
                self.logger.debug(f"心跳发送失败: {e}")
                self._handle_disconnect()
            time.sleep(2)

    def _serial_reader_loop(self):
        """持续消费串口响应，避免缓冲区积压导致固件阻塞"""
        while self._running and self.connected:
            try:
                line = self._read_line(timeout=0.5)
                if line:
                    self.logger.debug(f"← 设备: {line[:80]}")
                    # 如果收到 pong，说明连接正常
                    if 'pong' in line:
                        pass
            except Exception:
                pass  # 读取出错不影响主流程

    def disconnect(self):
        """断开连接"""
        self._running = False  # 停止后台线程
        if self.serial_conn and self.serial_conn.is_open:
            self.serial_conn.close()
        if self.wifi_sock:
            try:
                self.wifi_sock.close()
            except Exception:
                pass
        self.connected = False
        self.logger.info("📴 设备已断开")

    def send_update(self, state: dict):
        """发送状态更新到设备"""
        if not self.connected:
            return

        cmd = {
            "cmd": "update",
            **state
        }

        self._send_command(cmd)

    def send_alert(self, message: str):
        """发送告警到设备"""
        cmd = {
            "cmd": "alert",
            "message": message
        }
        self._send_command(cmd)

    def send_command(self, cmd: dict):
        """发送自定义命令"""
        self._send_command(cmd)

    def _send_command(self, cmd: dict):
        """底层命令发送"""
        json_str = json.dumps(cmd, ensure_ascii=False)
        try:
            if self.mode == 'serial':
                self._write_line(json_str)
            elif self.mode == 'wifi':
                self._wifi_write(json_str + '\n')
        except Exception as e:
            self.logger.error(f"发送失败: {e}")
            self._handle_disconnect()

    def _write_line(self, data: str):
        """Serial 写行"""
        if self.serial_conn and self.serial_conn.is_open:
            self.serial_conn.write((data + '\n').encode('utf-8'))
            self.serial_conn.flush()

    def _read_line(self, timeout: float = 1.0) -> Optional[str]:
        """Serial 读行"""
        if self.serial_conn and self.serial_conn.is_open:
            self.serial_conn.timeout = timeout
            try:
                line = self.serial_conn.readline().decode('utf-8', errors='ignore').strip()
                return line if line else None
            except Exception:
                return None
        return None

    def _wifi_write(self, data: str):
        """WiFi Socket 写"""
        if self.wifi_sock:
            self.wifi_sock.send(data.encode('utf-8'))

    def _wifi_read(self, timeout: float = 1.0) -> Optional[str]:
        """WiFi Socket 读"""
        if self.wifi_sock:
            try:
                self.wifi_sock.settimeout(timeout)
                data = self.wifi_sock.recv(4096).decode('utf-8', errors='ignore').strip()
                return data if data else None
            except Exception:
                return None
        return None

    def _handle_disconnect(self):
        """处理断连，尝试恢复"""
        # 防止多个线程同时重连
        if not self._reconnect_lock.acquire(blocking=False):
            return  # 已有其他线程在处理重连
        try:
            self.connected = False
            self._running = False  # 停掉旧的后台线程

            # 关闭旧串口，避免端口占用
            if self.serial_conn and self.serial_conn.is_open:
                try:
                    self.serial_conn.close()
                except Exception:
                    pass
            self.serial_conn = None

            self._reconnect_count += 1
            if self._reconnect_count <= self._max_reconnects:
                self.logger.warning(f"🔄 设备断连, 尝试重连 ({self._reconnect_count}/{self._max_reconnects})...")
                time.sleep(2)  # 给 ESP32 一点时间复位
                if self.mode == 'serial':
                    if self._connect_serial():
                        self.connected = True
                        self._reconnect_count = 0
                        self._start_background_tasks()
                        self.logger.info(f"✅ 重连成功: {self.serial_conn.port}")
                        return
                elif self.mode == 'wifi':
                    if self._connect_wifi():
                        self.connected = True
                        self._reconnect_count = 0
                        self._start_background_tasks()
                        self.logger.info("✅ WiFi 重连成功")
                        return
            else:
                self.logger.error("❌ 设备重连次数耗尽, 请检查硬件连接")
        finally:
            self._reconnect_lock.release()

    @property
    def is_connected(self) -> bool:
        return self.connected


# 便捷函数
def list_serial_ports():
    """列出所有串口"""
    ports = serial.tools.list_ports.comports()
    for p in ports:
        print(f"  {p.device}: {p.description} [{p.manufacturer}]")
        print(f"    VID:{p.vid:04X} PID:{p.pid:04X} S/N:{p.serial_number}")
    return ports
