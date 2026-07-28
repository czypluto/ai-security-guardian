#!/usr/bin/env python3
"""
AI Security Guardian — CLI Agent Interface

Usage:
  python agent_cli.py "scan my network for threats"
  python agent_cli.py --chat          Interactive chat mode
  python agent_cli.py --skill full-audit
  python agent_cli.py --list-tools    List available tools

Dify is the DESIGN platform — you prototype prompts and workflows there.
This CLI is the RUNTIME — the guardian agent that executes.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

# Ensure pc_agent is importable for config loading
sys.path.insert(0, str(Path(__file__).parent / "pc_agent"))

from agent.config import AgentConfig
from agent.core import AgentCore
from agent.tools import create_tool_registry
from agent.knowledge_base import get_knowledge_base


def setup_logging():
    logging.basicConfig(
        level=logging.WARNING,
        format="%(message)s",
        stream=sys.stderr,
    )


def print_banner(agent: AgentCore):
    """Print startup banner."""
    s = agent.summary()
    print()
    print("  \033[1;36m🛡️  AI 网络安全管家\033[0m")
    print("  \033[90m─────────────────────────────────────────\033[0m")
    print(f"  Model:       \033[33m{s['model']}\033[0m")
    print(f"  Tools:       \033[33m{s['builtin_tools']} builtin\033[0m", end="")
    if s['mcp_tools']:
        print(f" + \033[35m{s['mcp_tools']} MCP\033[0m", end="")
    print()
    print(f"  MCP Servers: \033[35m{s['mcp_servers']}\033[0m")
    print(f"  Skills:      \033[36m{s['skills']} loaded\033[0m")
    if s.get('kb_count', 0) > 0:
        print(f"  Knowledge:   \033[35m{s['kb_count']} docs, {s.get('kb_convs', 0)} convs\033[0m")
    print("  \033[90m─────────────────────────────────────────\033[0m")
    print()


def print_tools(agent: AgentCore):
    """Print available tools."""
    print()
    print("  \033[1mAvailable Tools:\033[0m")
    print()
    for tool in agent.tools.list_all():
        desc = tool.description[:80]
        print(f"  \033[36m{tool.name}\033[0m")
        print(f"    {desc}")
        if tool.parameters:
            for pname, pinfo in tool.parameters.items():
                req = " (required)" if pinfo.get("required") else ""
                print(f"    - {pname}: {pinfo.get('type', 'any')}{req}")
        print()


# ================================================================
#  Stream display helpers
# ================================================================

COLORS = {
    "tool_start": "\033[90m",   # gray
    "tool_result": "\033[90m",
    "text": "\033[0m",          # normal
    "error": "\033[31m",       # red
    "reset": "\033[0m",
}


def display_stream(events):
    """Consume streaming events and print formatted output."""
    for event in events:
        etype = event.get("type", "")
        color = COLORS.get(etype, "")

        if etype == "tool_start":
            name = event.get("name", "?")
            args = event.get("arguments", {})
            args_str = ", ".join(f"{k}={v}" for k, v in args.items()) if args else ""
            print(f"  {color}[tool] {name}({args_str})\033[0m")

        elif etype == "tool_result":
            result = event.get("result", "")
            try:
                parsed = __import__("json").loads(result)
                # Truncate for display
                if isinstance(parsed, dict):
                    summary = {k: v for k, v in list(parsed.items())[:5]}
                    display = __import__("json").dumps(summary, ensure_ascii=False, indent=2)
                    if len(parsed) > 5:
                        display += f"\n  ... ({len(parsed)} keys total)"
                    print(f"  {color}→ {display}\033[0m")
                else:
                    print(f"  {color}→ {str(parsed)[:200]}\033[0m")
            except Exception:
                print(f"  {color}→ {str(result)[:200]}\033[0m")

        elif etype == "text":
            sys.stdout.write(f"{color}{event['content']}\033[0m")
            sys.stdout.flush()

        elif etype == "error":
            print(f"\n  {color}[Error] {event['content']}\033[0m")

    print()


# ================================================================
#  Helpers
# ================================================================

def _confirm_and_save(agent: AgentCore) -> bool:
    """询问用户是否保存对话到知识库。返回 True 表示已保存。"""
    if not agent._conversation_messages:
        return False
    # 过滤出有效的 Q&A
    savable = [m for m in agent._conversation_messages
               if m.get("role") in ("user", "assistant")]
    if len(savable) < 2:
        return False

    try:
        answer = input("  \033[33m保存对话到知识库? (Y/n): \033[0m").strip().lower()
    except (EOFError, KeyboardInterrupt):
        answer = 'n'
    if answer not in ('', 'y', 'yes'):
        return False

    conv_id = agent.save_conversation()
    if conv_id:
        print(f"  \033[32m已保存: {conv_id}\033[0m")
        return True
    return False


# ================================================================
#  Modes
# ================================================================

def run_single_query(agent: AgentCore, query: str):
    """Run a single question and exit."""
    display_stream(agent.run_stream(query))


def run_chat_mode(agent: AgentCore):
    """Interactive chat REPL."""
    print_banner(agent)
    print("  Type \033[33m/help\033[0m for commands, \033[33m/quit\033[0m to exit.")
    print("  Type natural language, or \033[33m/run &lt;tool&gt;\033[0m to call a tool directly.")
    print()

    history = []
    while True:
        try:
            user_input = input("  \033[36mYou>\033[0m ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            _confirm_and_save(agent)
            print("  Goodbye!")
            break

        if not user_input:
            continue

        # Slash commands
        if user_input.startswith("/"):
            cmd = user_input[1:].lower().split()
            if cmd[0] in ("q", "quit", "exit"):
                _confirm_and_save(agent)
                print("  Goodbye!")
                break
            elif cmd[0] == "help":
                print()
                print("  \033[1mCommands:\033[0m")
                print("  /help       Show this help")
                print("  /tools      List available tools")
                print("  /model      Show active model")
                print("  /clear      Clear conversation history (auto-saves)")
                print("  /save       Manually save conversation to KB")
                print("  /kb         Show knowledge base stats")
                print("  /quit       Exit")
                print()
            elif cmd[0] == "tools":
                print_tools(agent)
            elif cmd[0] == "model":
                print(f"  Active model: {agent.active_model}")
                print(f"  Tools loaded: {agent.tool_count}")
                print()
            elif cmd[0] in ("clear", "cls"):
                saved = _confirm_and_save(agent)
                agent.clear_conversation()
                history.clear()
                if saved:
                    print("  History cleared (conversation saved to KB).")
                else:
                    print("  History cleared (not saved).")
                print()
            elif cmd[0] == "save":
                conv_id = agent.save_conversation()
                if conv_id:
                    print(f"  Conversation saved: {conv_id}")
                else:
                    print("  Nothing to save.")
                print()
            elif cmd[0] == "kb":
                if agent.kb:
                    stats = agent.kb.get_stats()
                    print()
                    print("  \033[1mKnowledge Base:\033[0m")
                    print(f"  Conversations: {stats['conversations']}")
                    print(f"  Vector docs:   {stats['vector_count']}")
                    print(f"  Embedding:     {stats['embedding_type']}")
                    print(f"  Storage:       {stats['chroma_dir']}")
                    print()
                else:
                    print("  Knowledge base not available.")
                    print("  Install: pip install chromadb sentence-transformers")
                    print()
            elif cmd[0] == "run":
                # Direct tool invocation: /run scan_network
                if len(cmd) < 2:
                    print("  Usage: /run <tool_name> [key=value ...]")
                    print("  e.g.: /run scan_network")
                    print("  e.g.: /run run_command command=ipconfig")
                    print()
                else:
                    tool_name = cmd[1]
                    tool = agent.tools.get(tool_name)
                    if tool is None:
                        print(f"  Unknown tool: {tool_name}")
                        print(f"  Use /tools to list available tools.")
                        print()
                    else:
                        args = {}
                        for arg in cmd[2:]:
                            if "=" in arg:
                                k, v = arg.split("=", 1)
                                try:
                                    args[k] = int(v)
                                except ValueError:
                                    args[k] = v
                        print()
                        print(f"  \033[90m[run] {tool_name}({args})\033[0m")
                        result = tool.execute(args)
                        try:
                            parsed = json.loads(result)
                            print(f"  \033[90m->\033[0m {json.dumps(parsed, ensure_ascii=False, indent=2)}")
                        except Exception:
                            print(f"  \033[90m->\033[0m {result}")
                        print()
            else:
                print(f"  Unknown command: /{cmd[0]}")
            continue

        # Run agent
        history.append({"role": "user", "content": user_input})
        print()
        display_stream(agent.run_stream(user_input))
        print()


# ================================================================
#  Main
# ================================================================

def main():
    parser = argparse.ArgumentParser(
        description="🛡️  AI Security Guardian — CLI Agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python agent_cli.py "scan network"
  python agent_cli.py --chat
  python agent_cli.py --list-tools
  python agent_cli.py --config my_config.yaml --chat
        """,
    )
    parser.add_argument("query", nargs="?", help="Natural language security query")
    parser.add_argument("--chat", "-c", action="store_true", help="Interactive chat mode")
    parser.add_argument("--list-tools", "-l", action="store_true", help="List available tools")
    parser.add_argument("--config", default=None, help="Path to config.yaml")
    parser.add_argument("--model", "-m", default=None, help="Force specific LLM provider")
    args = parser.parse_args()

    setup_logging()

    # Load config
    config_path = args.config or str(Path(__file__).parent / "pc_agent" / "config.yaml")
    config = AgentConfig.from_config_file(config_path)

    # Override with CLI args
    if args.model:
        for p in config.providers:
            p.enabled = (p.name == args.model)
    config.system_prompt = config.system_prompt or ""  # Will use DEFAULT

    # Create agent
    tools = create_tool_registry()

    # Initialize knowledge base
    kb = None
    if config.knowledge_base_enabled:
        try:
            kb = get_knowledge_base(
                persist_dir=config.knowledge_base_dir or None,
            )
            # Override embedding model if different from default
            if config.knowledge_base_embedding_model and kb._embed_type == "sentence-transformers":
                pass  # Model is set at init time; rebuild if needed
            print(f"  \033[90m知识库: {kb.conversation_count} 对话, {kb.count} 向量\033[0m", file=sys.stderr)
        except Exception as e:
            print(f"  \033[90m知识库初始化跳过: {e}\033[0m", file=sys.stderr)

    agent = AgentCore(config, tools, knowledge_base=kb)

    # Dispatch
    if args.list_tools:
        print_tools(agent)
    elif args.chat:
        run_chat_mode(agent)
    elif args.query:
        run_single_query(agent, args.query)
    else:
        # Default: chat mode
        run_chat_mode(agent)


if __name__ == "__main__":
    main()
