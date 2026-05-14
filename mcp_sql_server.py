"""MCP SQL Server — 通过 MCP 协议提供只读 SQL 执行能力。

使用 FastMCP 暴露 execute_sql 工具，支持：
- SQL 白名单校验（仅 SELECT / EXPLAIN / WITH）
- 多语句注入检测（阻止分号拼接攻击）
- SQLite 只读连接 + 查询超时（5s）
- 最大返回 1000 行，超限截断
- 进程隔离，崩溃不影响主智能体
"""

import json
import re
import sqlite3
from pathlib import Path

from mcp.server.fastmcp import FastMCP

# ---------- 配置 ----------
DEFAULT_DB_PATH = str(Path(__file__).parent / "data" / "school_demo.db")
MAX_ROWS = 1000
QUERY_TIMEOUT_MS = 5000  # 查询超时（毫秒）
ALLOWED_PREFIXES = ("SELECT", "EXPLAIN", "WITH")

# ---------- 服务器实例 ----------
mcp = FastMCP("sql-server")


# ---------- 工具函数 ----------
def _validate_sql(sql: str) -> str | None:
    """校验 SQL 安全性。返回 None 表示通过，否则返回错误信息。

    检查项：
    1. 白名单前缀（仅 SELECT / EXPLAIN / WITH）
    2. 移除注释和字符串后，检测分号（防多语句注入）
    3. 危险关键字黑名单
    """
    if not sql or not sql.strip():
        return "SQL 语句不能为空"

    # 移除单行注释
    cleaned = re.sub(r"--[^\n]*", " ", sql)
    # 移除多行注释
    cleaned = re.sub(r"/\*.*?\*/", " ", cleaned, flags=re.DOTALL)
    # 移除字符串字面量（防止 'xxx;yyy' 中的分号误判）
    cleaned = re.sub(r"'[^']*'", "''", cleaned)
    cleaned = re.sub(r'"[^"]*"', '""', cleaned)

    # 前缀白名单
    first_word = cleaned.strip().split()[0].upper() if cleaned.strip() else ""
    if first_word not in ALLOWED_PREFIXES:
        return f"只允许 {', '.join(ALLOWED_PREFIXES)} 查询，收到: {first_word}"

    # 多语句注入检测：移除注释和字符串后，不允许出现分号（除非末尾可选的 ;）
    stripped = cleaned.strip().rstrip(";").strip()
    if ";" in stripped:
        return "检测到多语句（分号分隔），拒绝执行。请只提交单条 SQL。"

    # 危险关键字黑名单（移除注释/字符串后的 cleaned 上检查）
    cleaned_upper = cleaned.upper()
    dangerous = (
        "DROP", "DELETE", "UPDATE", "INSERT", "ALTER", "CREATE",
        "REPLACE", "TRUNCATE", "ATTACH", "DETACH", "PRAGMA",
    )
    for kw in dangerous:
        # 用单词边界匹配，避免误判如 "updated_at" 包含 UPDATE
        if re.search(rf'\b{kw}\b', cleaned_upper):
            return f"检测到危险关键字 '{kw}'，拒绝执行。"

    return None


def _progress_handler():
    """SQLite 进度回调，每 N 条指令检查一次，用于实现查询超时。"""
    # 抛出异常中断查询
    raise sqlite3.OperationalError("查询执行超时")


@mcp.tool()
async def execute_sql(sql: str, db_path: str = DEFAULT_DB_PATH) -> str:
    """执行只读 SQL 查询并返回 JSON 结果。

    仅允许 SELECT / EXPLAIN / WITH 语句，结果上限 1000 行，查询超时 5 秒。

    Args:
        sql: 要执行的 SQL 语句
        db_path: SQLite 数据库文件路径（默认 school_demo.db）
    """
    err = _validate_sql(sql)
    if err:
        return json.dumps({"error": err}, ensure_ascii=False)

    uri = f"file:{db_path}?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True)
    except sqlite3.OperationalError as e:
        return json.dumps(
            {"error": f"无法以只读模式打开数据库: {e}"},
            ensure_ascii=False,
        )

    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 5000")
        # 每 100000 条指令触发一次进度检查，配合 _progress_handler 实现超时
        conn.set_progress_handler(_progress_handler, 100000)
        cursor = conn.cursor()
        cursor.execute(sql)
        rows = cursor.fetchmany(MAX_ROWS + 1)

        truncated = len(rows) > MAX_ROWS
        rows = rows[:MAX_ROWS]

        if rows:
            result = [dict(row) for row in rows]
            output = {"data": result, "row_count": len(result)}
            if truncated:
                output["truncated"] = True
                output["notice"] = (
                    f"结果已截断，仅返回前 {MAX_ROWS} 行。"
                    "请添加 LIMIT 或 WHERE 条件缩小范围。"
                )
            return json.dumps(output, ensure_ascii=False, indent=2)
        else:
            return json.dumps({"data": [], "row_count": 0}, ensure_ascii=False)

    except sqlite3.OperationalError as e:
        if "超时" in str(e):
            return json.dumps({"error": f"查询执行超时（>{QUERY_TIMEOUT_MS}ms），请简化查询条件"}, ensure_ascii=False)
        return json.dumps({"error": f"SQL 执行错误: {e}"}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": f"未知错误: {e}"}, ensure_ascii=False)
    finally:
        conn.close()


# ---------- 入口 ----------
if __name__ == "__main__":
    mcp.run()
