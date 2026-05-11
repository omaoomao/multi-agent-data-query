"""
LangGraph智能问答Agent - 多智能体版本

基于LangGraph工作流的自然语言数据库查询和分析系统。
支持一主两从的多智能体架构：
- 主智能体：MasterAgent（意图识别、路由、汇总）
- 子智能体1：SQLQueryAgent（数据库查询）
- 子智能体2：DataAnalysisAgent（数据分析）

支持长短期记忆：
- 短期记忆：MemorySaver（会话内对话历史）
- 长期记忆：LongTermMemory（跨会话用户偏好和知识）
"""

import os
import uuid
import sqlite3
import logging
from typing import Dict, Any
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

from langchain_openai import ChatOpenAI
from langchain_core.language_models import BaseLLM, BaseChatModel
import yaml

from agents import MasterAgent

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
import dotenv

dotenv.load_dotenv()
console = Console()


class MultiAgentSystem:
    """多智能体系统 - 主入口类"""
    
    def __init__(self, config_path: str = "config/config.yaml"):
        """初始化多智能体系统
        
        Args:
            config_path: 配置文件路径
        """
        self.config = self._load_config(config_path)
        self.llm = self._init_llm()
        self.db_path = self.config["database"]["path"]
        self._ensure_business_database()
        self.db_path = str(self._resolve_path(self.db_path))
        
        # 记忆配置
        memory_config = self.config.get("memory", {})
        short_term_max_tokens = memory_config.get("short_term_max_tokens", 1000)
        chroma_path = memory_config.get("chroma_path", "./data/chroma_db")
        max_knowledge_per_user = memory_config.get("max_knowledge_per_user", 100)

        # 联网搜索配置
        search_config = self.config.get("search", {})
        tavily_api_key = search_config.get("tavily_api_key", "")

        # 初始化主智能体（内部会初始化三个子智能体：SQL、Analysis、Search）
        self.master_agent = MasterAgent(
            llm=self.llm,
            db_path=self.db_path,
            num_examples=self.config["nl2sql"]["num_examples"],  # 3 Few-shot示例数量
            short_term_max_tokens=short_term_max_tokens,  # 短期记忆最大Token数
            tavily_api_key=tavily_api_key,  # 联网搜索API Key
            chroma_path=chroma_path,  # ChromaDB 向量数据库路径
            max_knowledge_per_user=max_knowledge_per_user,  # 每用户知识上限
        )
        
        # 用户登录状态
        self.user_id = None  # 当前登录用户
        self.session_id = None  # 当前会话ID

    def _resolve_path(self, db_path: str) -> Path:
        """将相对数据库路径解析为项目根目录下的绝对路径。"""
        path_obj = Path(db_path)
        if path_obj.is_absolute():
            return path_obj
        return (Path(__file__).parent / path_obj).resolve()

    def _ensure_business_database(self) -> None:
        """确保业务数据库存在，便于直接运行 agent.py。"""
        db_abs_path = self._resolve_path(self.db_path)
        if db_abs_path.exists():
            return

        db_abs_path.parent.mkdir(parents=True, exist_ok=True)

        # 学校场景默认库不存在时，自动执行初始化脚本。
        if db_abs_path.name == "school_demo.db":
            try:
                from data.init_school_db import main as init_school_db_main
                init_school_db_main()
                console.print(f"[green]已自动初始化业务数据库: {db_abs_path}[/green]")
                return
            except Exception as e:
                console.print(f"[yellow]自动初始化 school_demo.db 失败，将创建空库: {e}[/yellow]")

        # 兜底：创建空 SQLite 文件，防止路径不存在导致启动失败。
        conn = sqlite3.connect(db_abs_path)
        conn.close()
        console.print(f"[yellow]已创建空业务数据库文件: {db_abs_path}[/yellow]")
    
    def _load_config(self, config_path: str) -> Dict[str, Any]:
        """加载配置文件"""
        with open(config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)  # 加载YAML配置文件
        
        # 替换环境变量
        def replace_env_vars(obj):
            #   递归替换配置中的环境变量（格式：${ENV_VAR}）
            if isinstance(obj, dict):
                # 如果是字典，递归处理每个键值对
                return {k: replace_env_vars(v) for k, v in obj.items()}
            if isinstance(obj, str) and obj.startswith("${") and obj.endswith("}"):
                # 如果是字符串且符合环境变量格式，替换为环境变量值
                return os.getenv(obj[2:-1], obj)
            return obj
        
        return replace_env_vars(config)
    
    def _init_llm(self) -> BaseChatModel:
        """初始化语言模型
        
        使用 OpenAI 兼容接口连接 DashScope，支持所有通义千问模型
        （qwen-turbo-latest / qwen-plus-latest / qwen-max-latest / qwen3.5-plus 等）
        """
        # 根据配置选择LLM提供商，目前仅支持DashScope
        # TODO: 后续可以添加对其他LLM提供商的支持，如OpenAI、Azure、Anthropic等
        llm_config = self.config["llm"]
        
        # 根据配置初始化LLM实例，支持不同模型和参数
        if llm_config["provider"] == "dashscope":
            base_url = llm_config.get(
                "base_url",
                "https://dashscope.aliyuncs.com/compatible-mode/v1"
            )
            # 返回一个ChatOpenAI实例，配置参数包括模型名称、API Key、基础URL、温度和最大Token数，启用流式输出
            return ChatOpenAI(
                model=llm_config["model"],
                api_key=llm_config["api_key"],
                base_url=base_url,
                temperature=llm_config["temperature"],
                max_tokens=llm_config["max_tokens"],
                streaming=True,
            )
        else:
            raise ValueError(f"Unsupported LLM provider: {llm_config['provider']}")
    
    def login(self, user_id: str) -> bool:
        """用户登录
        
        Args:
            user_id: 用户ID
            
        Returns:
            是否登录成功
        """
        try:
            # 设置当前用户ID和会话ID
            self.user_id = user_id
            self.session_id = str(uuid.uuid4())  # 生成新的会话ID
            
            # 更新长期记忆中的用户活跃时间
            self.master_agent.long_term_memory.update_user_activity(user_id)
            
            return True
        except Exception as e:
            console.print(f"[red]登录失败: {e}[/red]")
            return False
    
    def query(self, question: str) -> str:
        """执行查询（阻塞式，返回完整回答）
        
        Args:
            question: 用户问题
        
        Returns:
            回答结果
        """
        logger.debug("=" * 80)
        logger.debug(f"[MultiAgentSystem] 收到查询请求: {question}")
        logger.debug(f"[MultiAgentSystem] 用户ID: {self.user_id}, 会话ID: {self.session_id}")

        if not self.user_id:
            logger.warning("用户未登录")
            return "请先登录。您可以输入任意用户ID开始使用。"

        thread_id = f"{self.user_id}_{self.session_id}"
        logger.debug(f"Thread ID: {thread_id}")

        # 调用主智能体的查询方法，传入用户问题、线程ID和用户ID，返回回答结果
        answer = self.master_agent.query(
            question,
            thread_id=thread_id,
            user_id=self.user_id
        )

        logger.debug(f"[MultiAgentSystem] 查询完成，回答长度: {len(answer)} 字符")
        
        return answer
    
    def stream_query(self, question: str):
        """流式查询，返回 SSE 事件生成器
        
        Args:
            question: 用户问题
            
        Yields:
            SSE 格式字符串
        """
        if not self.user_id:
            import json
            yield f"data: {json.dumps({'type': 'chunk', 'content': '请先登录。'}, ensure_ascii=False)}\n\n"
            yield f"data: {json.dumps({'type': 'done', 'answer': '请先登录。'})}\n\n"
            return
        
        thread_id = f"{self.user_id}_{self.session_id}"
        logger.debug(f"开始流式查询，线程ID: {thread_id}")
        
        yield from self.master_agent.stream_query(
            question,
            thread_id=thread_id,
            user_id=self.user_id
        )
    
    def set_thread_id(self, thread_id: str):
        """设置会话线程ID（保留兼容性）
        
        Args:
            thread_id: 线程ID
        """
        # 已废弃，现在使用 user_id + session_id 自动生成
        console.print("[yellow]提示：thread_id现在由user_id和session_id自动生成[/yellow]")
    
    def new_session(self):
        """开始新会话（保留当前用户，旧会话结束时提取长期记忆）"""
        if self.user_id:
            # 旧会话结束时提取长期记忆
            if self.session_id:
                try:
                    old_thread_id = f"{self.user_id}_{self.session_id}"
                    self.master_agent.extract_session_memory(self.user_id, old_thread_id)
                except Exception as e:
                    logger.warning(f"新会话时提取旧记忆失败（不影响功能）: {e}")
            # 生成新的会话ID
            self.session_id = str(uuid.uuid4())
            console.print(f"[green]已开始新会话: {self.session_id[:8]}...[/green]")
        else:
            console.print("[yellow]请先登录[/yellow]")
    
    def get_user_info(self) -> Dict[str, Any]:
        """获取当前用户信息"""
        if not self.user_id:
            return {"logged_in": False}
        
        profile = self.master_agent.long_term_memory.get_user_profile(self.user_id)
        preferences = self.master_agent.long_term_memory.get_all_preferences(self.user_id)
        
        return {
            "logged_in": True,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "profile": profile,
            "preferences": preferences
        }

def main():
    console.print(Panel.fit(
        "[cyan]LangGraph 多智能体数据查询系统 v2.1[/cyan]\n"
        "主智能体 + SQL查询 + 数据分析 + Web前端\n"
        "智能路由 · 深度分析 · 长短期记忆",
        border_style="cyan"
    ))
    console.print()
    
    if not os.getenv("DASHSCOPE_API_KEY"):
        console.print("[red]错误：未设置 DASHSCOPE_API_KEY 环境变量[/red]")
        return
    
    # 初始化系统
    agent = MultiAgentSystem()
    
    # 用户登录
    console.print("[bold cyan]欢迎使用智能数据查询系统！[/bold cyan]")
    user_id = Prompt.ask("[cyan]请输入用户ID（用于保存您的偏好和记忆）[/cyan]", default="guest")
    
    if agent.login(user_id):
        console.print(f"[green]欢迎 {user_id}！系统已就绪[/green]")
        console.print(f"[dim]会话ID: {agent.session_id[:8]}...[/dim]\n")
    else:
        console.print("[red]登录失败，程序退出[/red]")
        return
    
    # 显示帮助信息
    console.print("[dim]特殊命令：")
    console.print("[dim]  - 输入 'new' 开始新会话（清空短期记忆）")
    console.print("[dim]  - 输入 'info' 查看用户信息")
    console.print("[dim]  - 输入 'exit' 或 'quit' 退出系统[/dim]\n")
    

    
    
    while True:
        question = Prompt.ask("[cyan]请输入问题[/cyan]")
        
        # 处理特殊命令
        if question.lower() in ['exit', 'quit', 'q']:
            console.print("\n[yellow]再见！您的偏好和记忆已保存。[/yellow]")
            break
        
        if question.lower() == 'new':
            # 开始新会话，生成新的session_id，保留当前user_id不变，提示用户已开始新会话
            agent.new_session()
            continue
        
        if question.lower() == 'info':
            # 获取当前用户信息，包括用户ID、会话ID、偏好等，并以面板形式展示
            user_info = agent.get_user_info()
            console.print(Panel(
                f"[cyan]用户信息[/cyan]\n"
                f"用户ID: {user_info.get('user_id')}\n"
                f"会话ID: {user_info.get('session_id', '')[:8]}...\n"
                f"偏好: {user_info.get('preferences', {})}",
                border_style="blue"
            ))
            continue
        
        if not question.strip():
            continue
        
        # 执行查询
        answer = agent.query(question)
        console.print(Panel(answer, title="回答", border_style="green"))
        console.print()

    # agent.master_agent.visualize("master_agent_workflow.png")


if __name__ == "__main__":
    main()
