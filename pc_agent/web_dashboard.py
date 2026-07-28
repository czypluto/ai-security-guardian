"""
Web Dashboard — 极简莫兰迪风格
浏览器访问 http://127.0.0.1:5000
响应式设计 / 低饱和配色 / 圆角柔和 / hover微效
"""

import logging
from flask import Flask, render_template_string, jsonify, request

DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AI 网络安全管家</title>
<style>
  :root {
    --bg:        #f5f1ed;
    --card:      #ffffff;
    --text:      #4a4a4a;
    --muted:     #9a8f8a;
    --border:    #e8e0db;
    --safe:      #7a9a7e;
    --warn:      #c9a96e;
    --danger:    #c47e7e;
    --accent:    #8b9dab;
    --shadow:    0 1px 3px rgba(0,0,0,.06), 0 1px 2px rgba(0,0,0,.04);
    --radius:    12px;
  }
  * { margin:0; padding:0; box-sizing:border-box; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC',
                 'Microsoft YaHei', sans-serif;
    background: var(--bg);
    color: var(--text);
    line-height: 1.6;
    min-height: 100vh;
  }

  /* 导航 */
  nav {
    background: var(--card);
    border-bottom: 1px solid var(--border);
    padding: 0 24px;
    height: 56px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    position: sticky; top: 0; z-index: 10;
    box-shadow: var(--shadow);
  }
  nav .brand { font-size: 18px; font-weight: 600; color: var(--text); letter-spacing: .5px; }
  nav .brand span { color: var(--accent); }
  nav .nav-right { display: flex; align-items: center; gap: 16px; font-size: 13px; color: var(--muted); }
  .status-dot { width: 7px; height: 7px; border-radius: 50%; display: inline-block; margin-right: 4px; }
  .status-dot.online { background: var(--safe); }
  .status-dot.offline { background: var(--danger); }

  /* 主体 */
  main {
    max-width: 960px;
    margin: 0 auto;
    padding: 32px 24px 80px;
  }

  /* 状态卡片网格 */
  .grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
    gap: 16px;
    margin-bottom: 28px;
  }
  .card {
    background: var(--card);
    border-radius: var(--radius);
    padding: 24px 20px;
    text-align: center;
    box-shadow: var(--shadow);
    border: 1px solid transparent;
    transition: border-color .25s, box-shadow .25s;
  }
  .card:hover { border-color: var(--border); box-shadow: 0 2px 8px rgba(0,0,0,.08); }
  .card .emoji { font-size: 32px; margin-bottom: 8px; line-height: 1; }
  .card .val { font-size: 28px; font-weight: 600; margin: 4px 0; }
  .card .lbl { font-size: 12px; color: var(--muted); text-transform: uppercase; letter-spacing: 1px; }
  .card.safe .val { color: var(--safe); }
  .card.warn .val { color: var(--warn); }
  .card.danger .val { color: var(--danger); }
  .card.danger { border-color: var(--danger); }

  /* 系统资源 */
  .section {
    background: var(--card);
    border-radius: var(--radius);
    padding: 24px;
    margin-bottom: 20px;
    box-shadow: var(--shadow);
  }
  .section h3 { font-size: 14px; font-weight: 600; margin-bottom: 16px; color: var(--text); }
  .meter { margin-bottom: 14px; }
  .meter .row { display: flex; justify-content: space-between; font-size: 13px; margin-bottom: 4px; color: var(--muted); }
  .meter .bar {
    height: 8px;
    border-radius: 4px;
    background: var(--border);
    overflow: hidden;
    transition: background .4s;
  }
  .meter .bar .fill {
    height: 100%;
    border-radius: 4px;
    transition: width .6s ease;
  }
  .fill.cpu { background: var(--accent); }
  .fill.mem { background: var(--safe); }
  .fill.cpu.high { background: var(--danger); }
  .fill.mem.high { background: var(--danger); }

  /* 消息 */
  .msg { padding: 10px 14px; border-radius: 8px; font-size: 13px; margin-bottom: 6px; }
  .msg.warn { background: #fdf3e0; color: #8b6d3b; border-left: 3px solid var(--warn); }
  .msg.danger { background: #fce8e8; color: #8b4a4a; border-left: 3px solid var(--danger); }

  /* 页脚 */
  footer {
    text-align: center;
    font-size: 12px;
    color: var(--muted);
    padding: 24px;
    border-top: 1px solid var(--border);
    position: fixed; bottom: 0; left: 0; right: 0;
    background: var(--bg);
  }

  /* 刷新条 */
  .refresh-row { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; font-size: 13px; color: var(--muted); }

  @media (max-width: 640px) {
    .grid { grid-template-columns: repeat(2, 1fr); gap: 10px; }
    .card { padding: 16px 12px; }
    .card .val { font-size: 22px; }
    main { padding: 20px 14px 80px; }
  }
</style>
</head>
<body>

<nav>
  <div class="brand">🛡️ AI <span>安全管家</span></div>
  <div class="nav-right">
    <span><span class="status-dot online" id="dot"></span><span id="connLabel">在线</span></span>
    <span id="clock">--:--:--</span>
  </div>
</nav>

<main>
  <div class="refresh-row">
    <span id="lastUpdate">加载中...</span>
  </div>

  <!-- 安全卡片 -->
  <div class="grid">
    <div class="card" id="secCard">
      <div class="emoji" id="secEmoji">🛡️</div>
      <div class="val" id="secLevel">---</div>
      <div class="lbl">安全等级</div>
    </div>
    <div class="card">
      <div class="emoji">⚠️</div>
      <div class="val" id="threatCount">0</div>
      <div class="lbl">威胁数</div>
    </div>
    <div class="card">
      <div class="emoji">🌐</div>
      <div class="val" id="connCount">0</div>
      <div class="lbl">活跃连接</div>
    </div>
    <div class="card">
      <div class="emoji">🔒</div>
      <div class="val" id="fwVal">ON</div>
      <div class="lbl">防火墙</div>
    </div>
    <div class="card">
      <div class="emoji">🛡️</div>
      <div class="val" id="avVal">ON</div>
      <div class="lbl">防病毒</div>
    </div>
  </div>

  <!-- 系统资源 -->
  <div class="section">
    <h3>系统资源</h3>
    <div class="meter">
      <div class="row"><span>CPU</span><span id="cpuPct">0%</span></div>
      <div class="bar"><div class="fill cpu" id="cpuBar" style="width:0%"></div></div>
    </div>
    <div class="meter">
      <div class="row"><span>内存</span><span id="memPct">0%</span></div>
      <div class="bar"><div class="fill mem" id="memBar" style="width:0%"></div></div>
    </div>
  </div>

  <!-- 消息 -->
  <div class="section" id="msgSection" style="display:none">
    <h3>最近事件</h3>
    <div id="msgList"></div>
  </div>
</main>

<footer>AI Security Guardian · v3.1</footer>

<script>
const $ = (s) => document.querySelector(s);
const API = '/api/state';

function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)); }

async function refresh() {
  try {
    const r = await fetch(API);
    const d = await r.json();

    // 安全等级
    const lv = d.sec_level || 'safe';
    const sc = $('#secCard');
    sc.className = 'card ' + (lv === 'danger' ? 'danger' : lv === 'warning' ? 'warn' : 'safe');
    $('#secLevel').textContent = lv.toUpperCase();

    const emojis = { safe:'😊', warning:'😟', danger:'🚨' };
    $('#secEmoji').textContent = emojis[lv] || '🛡️';

    // 计数
    $('#threatCount').textContent = d.threat_count || 0;
    $('#connCount').textContent = d.active_connections || 0;
    $('#fwVal').textContent = d.firewall_on ? 'ON' : 'OFF';
    $('#fwVal').style.color = d.firewall_on ? 'var(--safe)' : 'var(--danger)';
    $('#avVal').textContent = d.defender_on ? 'ON' : 'OFF';
    $('#avVal').style.color = d.defender_on ? 'var(--safe)' : 'var(--danger)';

    // CPU / 内存
    const cpu = clamp(d.cpu_usage || 0, 0, 100);
    const mem = clamp(d.mem_usage || 0, 0, 100);
    $('#cpuPct').textContent = cpu.toFixed(0) + '%';
    $('#memPct').textContent = mem.toFixed(0) + '%';
    $('#cpuBar').style.width = cpu + '%';
    $('#memBar').style.width = mem + '%';
    $('#cpuBar').className = 'fill cpu' + (cpu > 80 ? ' high' : '');
    $('#memBar').className = 'fill mem' + (mem > 80 ? ' high' : '');

    // 消息
    const msgs = d.messages || [];
    const ms = $('#msgSection');
    if (msgs.length) {
      ms.style.display = 'block';
      $('#msgList').innerHTML = msgs.map(m =>
        `<div class="msg ${lv === 'danger' ? 'danger' : 'warn'}">${m}</div>`
      ).join('');
    } else { ms.style.display = 'none'; }

    // 在线
    $('#dot').className = 'status-dot online';
    $('#connLabel').textContent = '在线';
    $('#lastUpdate').textContent = '更新: ' + new Date().toLocaleTimeString('zh-CN');
  } catch(e) {
    $('#dot').className = 'status-dot offline';
    $('#connLabel').textContent = '离线';
  }
}

refresh(); setInterval(refresh, 3000);
setInterval(() => { $('#clock').textContent = new Date().toLocaleTimeString('zh-CN'); }, 1000);
</script>
</body>
</html>"""


class WebDashboard:
    """Flask Web 仪表盘"""

    def __init__(self, config: dict, controller, logger: logging.Logger):
        self.config = config
        self.controller = controller
        self.logger = logger
        self.app = Flask(__name__)
        self.host = config.get('host', '127.0.0.1')
        self.port = config.get('port', 5000)
        self._setup_routes()

    def _setup_routes(self):
        app = self.app

        @app.route('/')
        def index():
            return render_template_string(DASHBOARD_HTML)

        @app.route('/api/state')
        def api_state():
            return jsonify(self.controller.get_state())

        @app.route('/api/logs')
        def api_logs():
            lines = request.args.get('lines', 50, type=int)
            return jsonify(self.controller.get_logs(lines))

        @app.route('/api/chat', methods=['POST'])
        def api_chat():
            data = request.json or {}
            message = data.get('message', '').strip()
            if not message:
                return jsonify({'reply': '跟我说点什么吧~', 'success': False})
            try:
                char_mgr = self.controller.character
                if char_mgr.is_llm_available:
                    reply = char_mgr.smart_chat(message)
                    if reply:
                        self.controller.device.send_command({
                            "cmd": "say",
                            "text": reply[:40],
                        })
                        return jsonify({'reply': reply, 'success': True, 'llm': True})
                reply = char_mgr._pick_from('greeting')
                return jsonify({'reply': reply, 'success': True, 'llm': False})
            except Exception as e:
                return jsonify({'reply': f'出错了: {e}', 'success': False})

        @app.route('/api/llm/status')
        def api_llm_status():
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

    def run(self):
        try:
            self.logger.info(f"🌐 Web Dashboard: http://{self.host}:{self.port}")
            self.app.run(host=self.host, port=self.port, debug=False, use_reloader=False)
        except Exception as e:
            self.logger.error(f"Dashboard 启动失败: {e}")

    def stop(self):
        pass
