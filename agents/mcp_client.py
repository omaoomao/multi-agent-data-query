"""MCP SQL Client — 通过 stdio 与 MCP SQL Server 通信。

提供异步 (MCPSQLClient) 和同步 (SyncMCPSQLClient) 两种接口。
同步接口对 LangChain / LangGraph 等同步代码更友好。
"""

import asyncio
import atexit
import json
import logging
import sys
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class MCPSQLClient:
    """异步 MCP SQL 客户端，通过 stdio 启动并调用 mcp_sql_server.py。"""

    def __init__(self, db_path: str = "./data/school_demo.db"):
        self.db_path = str(Path(db_path).resolve())
        self._session = None
        self._client_ctx = None

    async def connect(self):
        """启动 MCP 服务器子进程并建立会话。"""
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        server_script = str(Path(__file__).parent.parent / "mcp_sql_server.py")
        server_params = StdioServerParameters(
            command=sys.executable,
            args=[server_script],
        )

        self._client_ctx = stdio_client(server_params)
        read, write = await self._client_ctx.__aenter__()
        self._session = ClientSession(read, write)
        await self._session.__aenter__()
        await self._session.initialize()
        logger.info("[MCP] SQL 客户端已连接")

    async def execute_sql(self, sql: str) -> str:
        """调用 MCP 服务器的 execute_sql 工具。"""
        if not self._session:
            raise RuntimeError("MCP 客户端未连接，请先调用 connect()")

        result = await self._session.call_tool(
            "execute_sql", {"sql": sql, "db_path": self.db_path}
        )
        if result.content:
            return result.content[0].text
        return json.dumps(
            {"error": "MCP 服务器返回空结果"}, ensure_ascii=False
        )

    async def close(self):
        """关闭连接和子进程。"""
        try:
            if self._session:
                await self._session.__aexit__(None, None, None)
            if self._client_ctx:
                await self._client_ctx.__aexit__(None, None, None)
        except Exception:
            pass
        logger.info("[MCP] SQL 客户端已断开")


class SyncMCPSQLClient:
    """同步 MCP SQL 客户端 — 用独立事件循环桥接 async 接口。"""

    def __init__(self, db_path: str = "./data/school_demo.db"):
        self._client = MCPSQLClient(db_path)
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def connect(self):
        self._loop = asyncio.new_event_loop()
        try:
            self._loop.run_until_complete(self._client.connect())
        except Exception:
            self._loop.close()
            self._loop = None
            raise
        atexit.register(self.close)

    def execute_sql(self, sql: str) -> str:
        if not self._loop:
            raise RuntimeError("MCP 客户端未连接")
        return self._loop.run_until_complete(self._client.execute_sql(sql))

    def close(self):
        if self._loop and self._loop.is_running():
            return  # 正在运行中无法关闭，跳过
        if self._loop:
            try:
                self._loop.run_until_complete(self._client.close())
            except Exception:
                pass
            try:
                self._loop.close()
            except Exception:
                pass
            self._loop = None
