"""
SQL查询子智能体

负责将自然语言转换为SQL并执行查询，支持自动纠错循环（最多3次重试）。
Reflection 模式：执行失败时将错误信息反馈给 LLM 重新生成。
"""

import json
import sqlite3
import re
from typing import Dict, Any

from langchain_core.language_models import BaseLLM

import logging
logger = logging.getLogger(__name__)
from prompts import get_few_shot_prompt, get_sql_correction_prompt


class SQLQueryAgent:
    """SQL查询子智能体，支持自动纠错循环（ReAct/Reflection 模式）"""

    def __init__(self, llm: BaseLLM, db_path: str, num_examples: int = 3,
                 mcp_enabled: bool = True):
        self.llm = llm
        self.db_path = db_path
        self.num_examples = num_examples
        self._mcp_client = None

        if mcp_enabled:
            try:
                from agents.mcp_client import SyncMCPSQLClient
                self._mcp_client = SyncMCPSQLClient(db_path)
                self._mcp_client.connect()
                logger.info("[NL2SQL] MCP SQL 客户端已连接")
            except Exception as e:
                logger.warning(f"[NL2SQL] MCP 连接失败，降级为直连 SQLite: {e}")
                self._mcp_client = None

    @staticmethod
    def _preview(text: str, max_len: int = 220) -> str:
        """日志预览：避免把超长文本一次性打满终端。"""
        if not text:
            return ""
        one_line = text.replace("\n", " ").strip()
        if len(one_line) <= max_len:
            return one_line
        return one_line[:max_len] + " ..."

    @staticmethod
    def _query_timeout_handler():
        """SQLite 进度回调，用于中断超时查询。"""
        raise sqlite3.OperationalError("查询执行超时")

    @staticmethod
    def _llm_to_str(result) -> str:
        """安全地从 LLM 返回值中提取文本，清理思考标签"""
        from agents._utils import llm_to_str
        return llm_to_str(result)

    # ------------------------------------------------------------------
    # Schema 构建：一次性返回所有表的完整详情
    # ------------------------------------------------------------------

    def _get_table_names(self) -> list[str]:
        """读取所有用户表名。"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
        tables = [row[0] for row in cursor.fetchall()]
        conn.close()
        return tables

    def _get_table_details(self, table_name: str) -> dict[str, Any]:
        """获取单表的字段、约束和少量样例行。"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute(f"PRAGMA table_info({table_name})")
        columns = cursor.fetchall()

        cursor.execute(f"PRAGMA foreign_key_list({table_name})")
        foreign_keys = cursor.fetchall()

        cursor.execute(f"PRAGMA index_list({table_name})")
        indexes = cursor.fetchall()
        unique_indexes = []
        for index in indexes:
            if len(index) >= 3 and index[2]:
                index_name = index[1]
                cursor.execute(f"PRAGMA index_info({index_name})")
                indexed_columns = [row[2] for row in cursor.fetchall()]
                if indexed_columns:
                    unique_indexes.append(indexed_columns)

        sample_rows = []
        try:
            cursor.execute(f'SELECT * FROM "{table_name}" LIMIT 3')
            sample_rows = cursor.fetchall()
        except Exception:
            sample_rows = []

        conn.close()
        return {
            "name": table_name,
            "columns": [
                {
                    "name": col[1],
                    "type": col[2],
                    "notnull": bool(col[3]),
                    "pk": bool(col[5]),
                }
                for col in columns
            ],
            "foreign_keys": [
                {
                    "column": fk[3],
                    "ref_table": fk[2],
                    "ref_column": fk[4],
                }
                for fk in foreign_keys
            ],
            "unique_indexes": unique_indexes,
            "sample_rows": sample_rows,
        }

    def _format_table_details(self, details: dict[str, Any]) -> str:
        """把单表信息格式化成适合提示词的文本。"""
        lines = [f"表：{details['name']}"]
        lines.append("字段：")
        for column in details["columns"]:
            pk_text = " (主键)" if column["pk"] else ""
            notnull_text = " NOT NULL" if column["notnull"] else ""
            lines.append(f"  - {column['name']}: {column['type']}{notnull_text}{pk_text}")

        if details["foreign_keys"]:
            lines.append("外键约束：")
            for fk in details["foreign_keys"]:
                lines.append(f"  - {fk['column']} -> {fk['ref_table']}.{fk['ref_column']}")

        if details["unique_indexes"]:
            lines.append("唯一约束/唯一索引：")
            for unique_columns in details["unique_indexes"]:
                lines.append(f"  - {', '.join(unique_columns)}")

        if details["sample_rows"]:
            lines.append("样例行：")
            for row in details["sample_rows"]:
                lines.append(f"  - {row}")

        return "\n".join(lines)

    def _select_tables(self, question: str, max_tables: int = 5) -> list[str]:
        """启发式选表：根据问题关键词匹配表名和列名，返回得分最高的表。

        不调用 LLM，纯字符串匹配，零成本。
        """
        table_names = self._get_table_names()
        if len(table_names) <= max_tables:
            return table_names

        # 预加载所有表的列名
        table_columns = {}
        for name in table_names:
            detail = self._get_table_details(name)
            table_columns[name] = [c["name"] for c in detail["columns"]]

        scored = []
        for name in table_names:
            score = 0
            # 表名命中 +10
            if name in question:
                score += 10
            # 列名命中 +3
            for col in table_columns[name]:
                if col in question:
                    score += 3
            scored.append((score, name))

        scored.sort(key=lambda x: -x[0])
        selected = [name for _, name in scored[:max_tables]]

        # 兜底：如果全部得分为 0，全返回
        if all(s == 0 for s, _ in scored[:max_tables]) and scored[0][0] == 0:
            logger.debug("[NL2SQL] 关键词未命中任何表，返回全部表")
            return table_names

        logger.debug(f"[NL2SQL] 启发式选表: {selected}")
        return selected

    def _build_full_schema(self, question: str = "") -> str:
        """构造 schema：先用关键词选表，再展开选中表的完整详情。"""
        if question:
            selected = self._select_tables(question)
        else:
            selected = self._get_table_names()
        if not selected:
            return ""
        parts = []
        for name in selected:
            detail = self._get_table_details(name)
            logger.debug(
                f"[NL2SQL] 表 {detail['name']} -> "
                f"字段{len(detail['columns'])}个, "
                f"外键{len(detail['foreign_keys'])}个, "
                f"样例行{len(detail['sample_rows'])}条"
            )
            parts.append(self._format_table_details(detail))
        return "\n\n".join(parts)

    # ------------------------------------------------------------------
    # SQL 生成 / 纠错 / 执行
    # ------------------------------------------------------------------

    def _clean_sql(self, sql: str) -> str:
        """清理SQL语句（移除代码块标记和多余前缀）"""
        sql = sql.strip()
        if sql.startswith("```sql"):
            sql = sql[6:]
        elif sql.startswith("```"):
            sql = sql[3:]

        prefixes = ["SQL：", "SQL:", "sql:", "sql："]
        for prefix in prefixes:
            if sql.startswith(prefix):
                sql = sql[len(prefix):]
                break

        if sql.endswith("```"):
            sql = sql[:-3]

        return sql.strip()

    def _generate_sql(self, question: str) -> str:
        """生成SQL语句：一次 LLM 调用，schema 直接包含所有表详情。"""
        schema = self._build_full_schema(question)
        self._cached_schema = schema  # 缓存，供纠错时复用
        prompt = get_few_shot_prompt(
            question=question,
            schema=schema,
            num_examples=self.num_examples
        )
        logger.debug(f"[NL2SQL] SQL 生成 Prompt 长度: {len(prompt)} 字符")
        sql = self._llm_to_str(self.llm.invoke(prompt)).strip()
        logger.debug(f"[NL2SQL] LLM 生成的原始 SQL: {self._preview(sql)}")
        return self._clean_sql(sql)

    def _correct_sql(self, question: str, original_sql: str, error_msg: str, attempt: int) -> str:
        """SQL 自动纠错（Reflection 模式）"""
        schema = getattr(self, '_cached_schema', '') or self._build_full_schema(question)
        prompt = get_sql_correction_prompt(
            question=question,
            schema=schema,
            original_sql=original_sql,
            error_msg=error_msg,
            attempt=attempt
        )
        corrected = self._llm_to_str(self.llm.invoke(prompt)).strip()
        return self._clean_sql(corrected)

    # 允许的 SQL 语句开头
    _ALLOWED_PREFIXES = ("SELECT", "EXPLAIN", "WITH")
    # 单次查询最大返回行数
    _MAX_ROWS = 1000
    # 查询超时（毫秒）
    _QUERY_TIMEOUT_MS = 5000

    @staticmethod
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
        if first_word not in SQLQueryAgent._ALLOWED_PREFIXES:
            return f"只允许 {', '.join(SQLQueryAgent._ALLOWED_PREFIXES)} 查询，收到: {first_word}"

        # 多语句注入检测
        stripped = cleaned.strip().rstrip(";").strip()
        if ";" in stripped:
            return "检测到多语句（分号分隔），拒绝执行。请只提交单条 SQL。"

        # 危险关键字黑名单
        cleaned_upper = cleaned.upper()
        dangerous = (
            "DROP", "DELETE", "UPDATE", "INSERT", "ALTER", "CREATE",
            "REPLACE", "TRUNCATE", "ATTACH", "DETACH", "PRAGMA",
        )
        for kw in dangerous:
            if re.search(rf'\b{kw}\b', cleaned_upper):
                return f"检测到危险关键字 '{kw}'，拒绝执行。"

        return None

    def _execute_sql_direct(self, sql: str) -> str:
        """直接通过 SQLite 只读连接执行 SQL（不经过 MCP 子进程）。"""
        err = self._validate_sql(sql)
        if err:
            return json.dumps({"error": err}, ensure_ascii=False)

        uri = f"file:{self.db_path}?mode=ro"
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
            conn.set_progress_handler(self._query_timeout_handler, 100000)
            cursor = conn.cursor()
            cursor.execute(sql)
            rows = cursor.fetchmany(self._MAX_ROWS + 1)

            truncated = len(rows) > self._MAX_ROWS
            rows = rows[: self._MAX_ROWS]

            if rows:
                result = [dict(row) for row in rows]
                output = {"data": result, "row_count": len(result)}
                if truncated:
                    output["truncated"] = True
                    output["notice"] = f"结果已截断，仅返回前 {self._MAX_ROWS} 行。请添加 LIMIT 或 WHERE 条件缩小范围。"
                return json.dumps(output, ensure_ascii=False, indent=2)
            else:
                return json.dumps({"data": [], "row_count": 0}, ensure_ascii=False)

        except sqlite3.OperationalError as e:
            if "超时" in str(e):
                return json.dumps({"error": f"查询执行超时（>{self._QUERY_TIMEOUT_MS}ms），请简化查询条件"}, ensure_ascii=False)
            return json.dumps({"error": f"SQL 执行错误: {e}"}, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"error": f"未知错误: {e}"}, ensure_ascii=False)
        finally:
            conn.close()

    def _mcp_execute(self, sql: str) -> str:
        """通过 MCP 执行 SQL，失败时自动降级为直连 SQLite。"""
        err = self._validate_sql(sql)
        if err:
            return json.dumps({"error": err}, ensure_ascii=False)

        if self._mcp_client:
            try:
                return self._mcp_client.execute_sql(sql)
            except Exception as e:
                logger.warning(f"[NL2SQL] MCP 调用失败，降级直连: {e}")

        return self._execute_sql_direct(sql)

    def query(self, question: str, max_retries: int = 3) -> Dict[str, Any]:
        """执行查询，失败时自动纠错并重试（Reflection 循环）

        流程：生成SQL → 执行 → [失败] → 错误反馈给LLM → 重新生成 → 最多重试 max_retries 次
        """
        result = {
            "sql": None,
            "data": None,
            "error": None,
            "retry_count": 0
        }

        logger.info(f"[NL2SQL] 开始处理: {question}")

        try:
            sql = self._generate_sql(question)
            result["sql"] = sql
            logger.info(f"[NL2SQL] 生成的 SQL: {sql}")

            if not sql:
                result["error"] = "未能生成有效的SQL"
                return result

            for attempt in range(max_retries):
                logger.info(f"[NL2SQL][EXEC] 执行 SQL，尝试 {attempt + 1}/{max_retries}")
                query_result = self._mcp_execute(sql)
                result_data = json.loads(query_result)

                if isinstance(result_data, dict) and "error" in result_data:
                    error_msg = result_data["error"]

                    if attempt < max_retries - 1:
                        logger.info(f"[SQL纠错] 第{attempt + 1}次执行失败: {error_msg}，正在让LLM自动修复...")
                        sql = self._correct_sql(question, sql, error_msg, attempt + 1)
                        result["sql"] = sql
                        result["retry_count"] = attempt + 1
                        logger.info(f"[SQL纠错] 修复后的 SQL: {sql}")
                    else:
                        result["error"] = f"SQL执行失败（已自动重试{attempt}次）: {error_msg}"
                else:
                    if isinstance(result_data, dict) and "data" in result_data:
                        result["data"] = query_result
                        row_count = result_data.get("row_count", len(result_data["data"]))
                    elif isinstance(result_data, list):
                        result["data"] = query_result
                        row_count = len(result_data)
                    else:
                        result["data"] = query_result
                        row_count = 1
                    logger.info(f"[NL2SQL][EXEC] 执行成功，结果行数: {row_count}")
                    if attempt > 0:
                        logger.info(f"[SQL纠错] 第{attempt}次修复后执行成功")
                    break

        except Exception as e:
            result["error"] = f"查询失败: {str(e)}"

        if result.get("error"):
            logger.info(f"[NL2SQL] 结束，失败: {result['error']}")
        else:
            logger.info(f"[NL2SQL] 结束，成功。重试次数: {result['retry_count']}")

        return result
