# Dify Design Platform — How to Use

Dify (http://localhost) is the **design-time** tool for prototyping the guardian agent.

## Workflow

### 1. Prototype System Prompt
- Open Dify → Create Agent App
- Paste `system_prompt.md` as the system prompt
- Select different LLM models (local Qwen vs DeepSeek vs Zhipu)
- Test with various security questions
- Iterate on the prompt until agent behavior is correct

### 2. Test Tools in Dify
- The guardian's MCP tools can be imported into Dify as Custom Tools
- Import the OpenAPI schema to test tool chaining
- Design workflow logic visually

### 3. Export to Guardian
Once satisfied with the design:
- Copy the refined system prompt to the guardian's `agent/config.py`
- Skills designed as Dify workflows → implement as Python skills in `skills/`
- Test in the guardian CLI: `python agent_cli.py --chat`

### 4. Production Runtime
The guardian runs independently:
```bash
python agent_cli.py --chat          # Interactive mode
python agent_cli.py "scan network"  # Single query
```
