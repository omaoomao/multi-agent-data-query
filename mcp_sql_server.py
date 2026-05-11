"""MCP SQL Server — 通过 MCP 协议提供只读 SQL 执行能力。

使用 FastMCP 暴露 execute_sql 工具，支持：
- SQL 白名单校验（仅 SELECT / EXPLAIN / WITH）
- SQLite 只读连接
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
ALLOWED_PREFIXES = ("SELECT", "EXPLAIN", "WITH")

# ---------- 服务器实例 ----------
mcp = FastMCP("sql-server")


# ---------- 工具函数 ----------
def _validate_sql(sql: str) -> str | None:
    """校验 SQL 是否在白名单内。返回 None 表示通过，否则返回错误信息。"""
    if not sql or not sql.strip():
        return "SQL 语句不能为空"
    cleaned = re.sub(r"--[^\n]*", " ", sql)
    cleaned = re.sub(r"/\*.*?\*/", " ", cleaned, flags=re.DOTALL)
    first_word = cleaned.strip().split()[0].upper() if cleaned.strip() else ""
    if first_word not in ALLOWED_PREFIXES:
        return f"只允许 {', '.join(ALLOWED_PREFIXES)} 查询，收到: {first_word}"
    return None


@mcp.tool()
async def execute_sql(sql: str, db_path: str = DEFAULT_DB_PATH) -> str:
    """执行只读 SQL 查询并返回 JSON 结果。

    仅允许 SELECT / EXPLAIN / WITH 语句，结果上限 1000 行。

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

    except sqlite3.Error as e:
        return json.dumps({"error": f"SQL 执行错误: {e}"}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": f"未知错误: {e}"}, ensure_ascii=False)
    finally:
        conn.close()


# ---------- 入口 ----------
if __name__ == "__main__":
    mcp.run()
