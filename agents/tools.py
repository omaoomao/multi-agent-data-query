from pathlib import Path
import subprocess
from typing import Optional, Dict, Any

from langchain_core.tools import tool

WORKDIR = Path(__file__).parent.parent


def safe_path(p: str) -> Path:
    path = (WORKDIR / p).resolve()
    try:
        path.relative_to(WORKDIR)
    except Exception:
        raise ValueError(f"Path escapes workspace: {p}")
    return path


@tool
def run_bash(command: str) -> str:
    """Execute a shell command and return the output."""
    dangerous = ["rm -rf /", "sudo", "shutdown", "reboot", "> /dev/"]
    if any(d in command for d in dangerous):
        return "Error: Dangerous command blocked"
    try:
        result = subprocess.run(command, shell=True, cwd=WORKDIR, capture_output=True, text=True, timeout=60)
        output = (result.stdout or "") + (result.stderr or "")
        return output.strip()[:50000] if output else "(no output)"
    except subprocess.TimeoutExpired:
        return "Error: Command timed out (60s)"
    except Exception as e:
        return f"Error: {e}"


@tool
def run_read_file(path: str, limit: Optional[int] = None) -> str:
    """Read the contents of a file. Optionally limit the number of lines returned."""
    try:
        fp = safe_path(path)
        text = fp.read_text(encoding="utf-8")
        if limit is None:
            return text[:50000]
        lines = text.splitlines()
        if limit < len(lines):
            return "\n".join(lines[:limit]) + f"\n... ({len(lines)-limit} more lines)"
        return text
    except Exception as e:
        return f"Error: {e}"


@tool
def run_write_file(path: str, content: str) -> str:
    """Write content to a file, creating directories if needed."""
    try:
        fp = safe_path(path)
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content, encoding="utf-8")
        return f"Wrote {len(content)} bytes to {path}"
    except Exception as e:
        return f"Error: {e}"


@tool
def run_edit_file(path: str, old_text: str, new_text: str) -> str:
    """Replace exact text in a file with new text."""
    try:
        fp = safe_path(path)
        content = fp.read_text(encoding="utf-8")
        if old_text not in content:
            return f"Error: Text not found in {path}"
        new_content = content.replace(old_text, new_text, 1)
        fp.write_text(new_content, encoding="utf-8")
        return f"Edited {path}"
    except Exception as e:
        return f"Error: {e}"


@tool
def run_web_search(query: str, max_results: int = 5) -> str:
    """Search the web for information using Tavily."""
    import os
    try:
        from langchain_tavily import TavilySearch
        api_key = os.getenv("TAVILY_API_KEY", "")
        if not api_key or api_key.startswith("${"):
            return "Error: TAVILY_API_KEY is not configured or invalid."
        search_tool = TavilySearch(max_results=max_results)
        invoke_result = search_tool.invoke(query)

        # 格式化搜索结果
        if isinstance(invoke_result, list):
            formatted = []
            for i, r in enumerate(invoke_result, 1):
                if isinstance(r, dict):
                    title = r.get("title", "无标题")
                    content = r.get("content", "")
                    url = r.get("url", "")
                    content_preview = content[:600] if len(content) > 600 else content
                    formatted.append(f"[来源{i}] {title}\n{content_preview}\n链接: {url}")
            return "\n\n".join(formatted) if formatted else "未找到相关搜索结果"
        elif isinstance(invoke_result, dict):
            results = invoke_result.get("results", [])
            formatted = []
            for i, r in enumerate(results, 1):
                if isinstance(r, dict):
                    title = r.get("title", "无标题")
                    content = r.get("content", "")
                    url = r.get("url", "")
                    content_preview = content[:600] if len(content) > 600 else content
                    formatted.append(f"[来源{i}] {title}\n{content_preview}\n链接: {url}")
            return "\n\n".join(formatted) if formatted else "未找到相关搜索结果"
        else:
            return str(invoke_result)
    except ImportError:
        return "Error: langchain-tavily is not installed. Run `pip install langchain-tavily`."
    except Exception as e:
        return f"Error: Web search failed: {e}"


# 工具列表（用于 llm.bind_tools）
TOOLS = [run_bash, run_read_file, run_write_file, run_edit_file, run_web_search]

# 工具调度字典（用于按名称调用）
TOOL_DISPATCH = {
    "run_bash": run_bash,
    "run_read_file": run_read_file,
    "run_write_file": run_write_file,
    "run_edit_file": run_edit_file,
    "run_web_search": run_web_search,
}


def execute_tool(name: str, args: Dict[str, Any]) -> str:
    """按名称执行工具（向后兼容）"""
    if name in TOOL_DISPATCH:
        return TOOL_DISPATCH[name].invoke(args)
    return f"Unknown tool: {name}"
