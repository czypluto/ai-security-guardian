"""
Web Dashboard —— 在浏览器中查看安全状态
访问 http://127.0.0.1:5000
"""

import logging
import threading
import json
import time
from flask import Flask, render_template_string, jsonify, request

# 内嵌 HTML 模板
DASHBOARD_HTML = r"""
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>🛡️ AI 网络安全管家</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Segoe UI', 'Microsoft YaHei', sans-serif;
            background: #0a0e17;
            color: #e0e6ed;
            min-height: 100vh;
            padding: 20px;
        }
        .container { max-width: 900px; margin: 0 auto; }
        h1 {
            text-align: center;
            font-size: 2em;
            margin-bottom: 20px;
            background: linear-gradient(135deg, #00d4aa, #4a9eff);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }

        .status-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
            margin-bottom: 20px;
        }

        .card {
            background: #141b26;
            border: 1px solid #1e2d3d;
            border-radius: 12px;
            padding: 20px;
            text-align: center;
            transition: all 0.3s;
        }
        .card:hover { border-color: #4a9eff; transform: translateY(-2px); }
        .card .icon { font-size: 2.5em; margin-bottom: 8px; }
        .card .value { font-size: 1.8em; font-weight: bold; margin: 5px 0; }
        .card .label { font-size: 0.85em; color: #8899aa; text-transform: uppercase; }

        .safe { color: #00d4aa; }
        .warning { color: #ffc107; }
        .danger { color: #ff4757; }

        .card.danger-card { border-color: #ff4757; animation: pulse 1.5s infinite; }
        @keyframes pulse {
            0%,100% { box-shadow: 0 0 0 0 rgba(255,71,87,0.4); }
            50% { box-shadow: 0 0 20px 5px rgba(255,71,87,0.2); }
        }

        .threats-section {
            background: #141b26;
            border: 1px solid #1e2d3d;
            border-radius: 12px;
            padding: 20px;
            margin-bottom: 20px;
        }
        .threat-item {
            padding: 8px 12px;
            margin: 5px 0;
            background: #1a1e2a;
            border-radius: 6px;
            border-left: 3px solid #ffc107;
        }

        .progress-bar {
            background: #1e2d3d;
            border-radius: 10px;
            height: 20px;
            overflow: hidden;
            margin: 10px 0;
        }
        .progress-fill {
            height: 100%;
            border-radius: 10px;
            background: linear-gradient(90deg, #00d4aa, #4a9eff);
            transition: width 0.5s;
        }

        .refresh-bar {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 20px;
            color: #8899aa;
            font-size: 0.85em;
        }

        .btn {
            background: #1e3a5f;
            color: #4a9eff;
            border: 1px solid #2a5088;
            padding: 8px 16px;
            border-radius: 6px;
            cursor: pointer;
            font-size: 0.9em;
        }
        .btn:hover { background: #2a5088; }
        .btn.danger { background: #3d1a1a; color: #ff4757; border-color: #5f2a2a; }
        .btn.danger:hover { background: #5f2a2a; }
    </style>
</head>
<body>
    <div class="container">
        <h1>🛡️ AI 网络安全管家</h1>

        <div class="refresh-bar">
            <span id="lastUpdate">更新中...</span>
            <span>
                状态: <span id="connStatus">● 在线</span>
            </span>
        </div>

        <div class="status-grid">
            <div class="card" id="secCard">
                <div class="icon">🛡️</div>
                <div class="value" id="secLevel">SAFE</div>
                <div class="label">安全等级</div>
            </div>
            <div class="card">
                <div class="icon">⚠️</div>
                <div class="value" id="threatCount">0</div>
                <div class="label">活跃威胁</div>
            </div>
            <div class="card">
                <div class="icon">🌐</div>
                <div class="value" id="connections">0</div>
                <div class="label">网络连接</div>
            </div>
            <div class="card" id="charCard">
                <div class="icon" id="charIcon">(｡･ω･｡)</div>
                <div class="value" id="aiStatus">Idle</div>
                <div class="label">🤖 AI 状态</div>
            </div>
            <div class="card">
                <div class="icon">🔥</div>
                <div class="value" id="firewall">ON</div>
                <div class="label">防火墙</div>
            </div>
            <div class="card">
                <div class="icon">🛡️</div>
                <div class="value" id="defender">ON</div>
                <div class="label">防病毒</div>
            </div>
        </div>

        <div class="threats-section" id="threatsSection" style="display:none;">
            <h3>🚨 威胁详情</h3>
            <div id="threats"></div>
        </div>

        <div class="card" style="text-align: left; margin-bottom: 20px;">
            <h3>📊 系统资源</h3>
            <div>CPU: <span id="cpu">0</span>%</div>
            <div class="progress-bar">
                <div class="progress-fill" id="cpuBar" style="width:0%"></div>
            </div>
            <div>内存: <span id="mem">0</span>%</div>
            <div class="progress-bar">
                <div class="progress-fill" id="memBar" style="width:0%"></div>
            </div>
        </div>
    </div>

    <script>
        async function refresh() {
            try {
                const resp = await fetch('/api/state');
                const data = await resp.json();

                // 安全等级
                const secEl = document.getElementById('secLevel');
                const secCard = document.getElementById('secCard');
                secEl.textContent = data.sec_level.toUpperCase();
                secEl.className = 'value ' + data.sec_level;
                secCard.className = 'card ' + (data.sec_level === 'danger' ? 'danger-card' : '');

                // 威胁
                document.getElementById('threatCount').textContent = data.threat_count;
                document.getElementById('connections').textContent = data.active_connections;
                document.getElementById('aiStatus').textContent = data.ai_status;
                document.getElementById('firewall').textContent = data.firewall_on ? '✅ ON' : '❌ OFF';
                document.getElementById('defender').textContent = data.defender_on ? '✅ ON' : '❌ OFF';

                // 角色表情
                const charEmoji = getCharEmoji(data.sec_level, data.ai_status);
                document.getElementById('charIcon').textContent = charEmoji;
                const charCard = document.getElementById('charCard');
                if (data.sec_level === 'danger') {
                    charCard.style.borderColor = '#ff4757';
                } else if (data.sec_level === 'warning') {
                    charCard.style.borderColor = '#ffc107';
                } else {
                    charCard.style.borderColor = '#1e2d3d';
                }

                // CPU / Mem
                const cpu = data.cpu_usage.toFixed(1);
                const mem = data.mem_usage.toFixed(1);
                document.getElementById('cpu').textContent = cpu;
                document.getElementById('cpuBar').style.width = cpu + '%';
                document.getElementById('mem').textContent = mem;
                document.getElementById('memBar').style.width = mem + '%';

                // 威胁列表
                const threatsDiv = document.getElementById('threats');
                const threatsSection = document.getElementById('threatsSection');
                if (data.messages && data.messages.length > 0) {
                    threatsSection.style.display = 'block';
                    threatsDiv.innerHTML = data.messages.map(m =>
                        `<div class="threat-item">${m}</div>`
                    ).join('');
                } else {
                    threatsSection.style.display = 'none';
                }

                document.getElementById('lastUpdate').textContent =
                    '最后更新: ' + new Date().toLocaleTimeString('zh-CN');
            } catch(e) {
                document.getElementById('connStatus').innerHTML = '● <span class="danger">离线</span>';
            }
        }

        // 角色表情映射
        function getCharEmoji(secLevel, aiStatus) {
            if (secLevel === 'danger') return '(>_<)💢';
            if (secLevel === 'warning') return '(;_;)⚡';
            if (aiStatus === 'working') return '(･_･)🛡️';
            if (aiStatus === 'alert') return '(>_<)';
            if (aiStatus === 'offline') return '(-_-)💤';
            return '(｡･ω･｡)✨';
        }
        }

        setInterval(refresh, 3000);
        refresh();
    </script>
</body>
</html>
"""


class WebDashboard:
    """Flask Web 仪表盘"""

    def __init__(self, config: dict, controller, logger: logging.Logger):
        self.config = config
        self.controller = controller
        self.logger = logger
        self.app = Flask(__name__)
        self.host = config.get('host', '127.0.0.1')
        self.port = config.get('port', 5000)

        # 注册路由
        self._setup_routes()

    def _setup_routes(self):
        app = self.app

        @app.route('/')
        def index():
            return render_template_string(DASHBOARD_HTML)

        @app.route('/api/state')
        def api_state():
            state = self.controller.get_state()
            return jsonify(state)

        @app.route('/api/logs')
        def api_logs():
            lines = request.args.get('lines', 50, type=int)
            logs = self.controller.get_logs(lines)
            return jsonify(logs)

        @app.route('/api/chat', methods=['POST'])
        def api_chat():
            """与 AI 角色对话 (LLM驱动)"""
            data = request.json or {}
            message = data.get('message', '').strip()
            if not message:
                return jsonify({'reply': '跟我说点什么吧~', 'success': False})

            try:
                char_mgr = self.controller.character
                if char_mgr.is_llm_available:
                    reply = char_mgr.smart_chat(message)
                    if reply:
                        # 同时发送到设备屏幕
                        self.controller.device.send_command({
                            "cmd": "say",
                            "text": reply[:40],
                        })
                        return jsonify({'reply': reply, 'success': True, 'llm': True})
                    else:
                        return jsonify({
                            'reply': '唔... LLM 好像不在状态，请稍后再试~',
                            'success': False, 'llm': False,
                        })
                else:
                    # 本地台词库回复
                    reply = char_mgr._pick_from('greeting')
                    return jsonify({'reply': reply, 'success': True, 'llm': False})
            except Exception as e:
                return jsonify({'reply': f'出错了: {e}', 'success': False})

        @app.route('/api/llm/status')
        def api_llm_status():
            """LLM 状态"""
            try:
                return jsonify({
                    'available': self.controller.character.is_llm_available,
                    'providers': self.controller.llm.available_count,
                    'stats': {
                        'total_calls': self.controller.llm.stats.total_calls,
                        'total_tokens': self.controller.llm.stats.total_tokens,
                    },
                })
            except Exception:
                return jsonify({'available': False, 'providers': 0})

        @app.route('/api/commands', methods=['POST'])
        def api_commands():
            cmd = request.json
            if cmd.get('action') == 'scan_now':
                return jsonify({'status': 'ok', 'message': '扫描已触发'})
            elif cmd.get('action') == 'test_llm':
                if self.controller.llm.available_count > 0:
                    results = self.controller.llm.test_connection()
                    return jsonify({'status': 'ok', 'results': results})
                return jsonify({'status': 'error', 'message': '无可用 LLM'})
            return jsonify({'status': 'error', 'message': '未知命令'})

    def run(self):
        """启动 Web 服务器"""
        try:
            self.logger.info(f"🌐 Web Dashboard: http://{self.host}:{self.port}")
            self.app.run(host=self.host, port=self.port, debug=False, use_reloader=False)
        except Exception as e:
            self.logger.error(f"Dashboard 启动失败: {e}")

    def stop(self):
        """停止 Web 服务器"""
        # Flask 没有优雅停止方式，依赖线程结束
        pass
