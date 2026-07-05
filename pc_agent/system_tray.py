"""
系统托盘应用 —— 在任务栏显示安全管家图标
"""

import logging
import threading
from pathlib import Path


class SystemTrayApp:
    """Windows 系统托盘"""

    def __init__(self, controller, logger: logging.Logger):
        self.controller = controller
        self.logger = logger
        self.running = False

    def run(self):
        """启动系统托盘"""
        try:
            import pystray
            from PIL import Image, ImageDraw

            # 创建简单图标 (绿色盾牌)
            def create_icon(color=(0, 210, 170)):
                img = Image.new('RGBA', (64, 64), (0, 0, 0, 0))
                draw = ImageDraw.Draw(img)
                # 盾牌形状
                draw.polygon([
                    (32, 4), (58, 16), (58, 36),
                    (40, 56), (32, 60), (24, 56),
                    (6, 36), (6, 16)
                ], fill=color)
                # 勾
                draw.line([(20, 32), (28, 42), (44, 22)], fill='white', width=3)
                return img

            def on_click(icon, item):
                if str(item) == '打开 Dashboard':
                    import webbrowser
                    webbrowser.open('http://127.0.0.1:5000')
                elif str(item) == '立即扫描':
                    self.logger.info("手动触发安全扫描")
                elif str(item) == '退出':
                    icon.stop()
                    self.controller.stop()

            icon = pystray.Icon(
                'ai_guardian',
                create_icon(),
                '🛡️ AI 网络安全管家',
                menu=pystray.Menu(
                    pystray.MenuItem('🛡️ AI 安全管家', None, enabled=False),
                    pystray.Menu.SEPARATOR,
                    pystray.MenuItem('安全等级: ● 安全', None, enabled=False),
                    pystray.MenuItem('威胁: 0', None, enabled=False),
                    pystray.MenuItem('AI: 空闲', None, enabled=False),
                    pystray.Menu.SEPARATOR,
                    pystray.MenuItem('🔍 立即扫描', on_click),
                    pystray.MenuItem('📊 打开 Dashboard', on_click),
                    pystray.Menu.SEPARATOR,
                    pystray.MenuItem('❌ 退出', on_click),
                )
            )

            # 定时更新菜单和图标
            def update_loop():
                import time
                while self.running:
                    try:
                        state = self.controller.get_state()
                        icon.title = f"AI 安全管家 | {state['sec_level'].upper()}"

                        # 根据状态更新图标颜色
                        if state['sec_level'] == 'danger':
                            icon.icon = create_icon((255, 71, 87))
                        elif state['sec_level'] == 'warning':
                            icon.icon = create_icon((255, 193, 7))
                        else:
                            icon.icon = create_icon((0, 210, 170))

                        # 更新菜单文字
                        icon.menu = pystray.Menu(
                            pystray.MenuItem('🛡️ AI 安全管家', None, enabled=False),
                            pystray.Menu.SEPARATOR,
                            pystray.MenuItem(
                                f"安全等级: {'🔴' if state['sec_level']=='danger' else '🟡' if state['sec_level']=='warning' else '🟢'} {state['sec_level'].upper()}",
                                None, enabled=False),
                            pystray.MenuItem(f"威胁: {state['threat_count']}", None, enabled=False),
                            pystray.MenuItem(f"AI: {state['ai_status']}", None, enabled=False),
                            pystray.Menu.SEPARATOR,
                            pystray.MenuItem('🔍 立即扫描', on_click),
                            pystray.MenuItem('📊 打开 Dashboard', on_click),
                            pystray.Menu.SEPARATOR,
                            pystray.MenuItem('❌ 退出', on_click),
                        )
                    except Exception:
                        pass
                    time.sleep(2)

            self.running = True
            update_thread = threading.Thread(target=update_loop, daemon=True)
            update_thread.start()

            self.logger.info("🖥️  系统托盘已启动")
            icon.run()

        except ImportError:
            self.logger.debug("pystray 未安装, 跳过系统托盘")
        except Exception as e:
            self.logger.debug(f"系统托盘启动失败: {e}")

    def stop(self):
        self.running = False
