"""
主智能体

负责意图识别、任务路由、协调子智能体和结果汇总。
支持6种意图：simple_answer / sql_only / analysis_only / sql_and_analysis / web_search / search_and_sql
"""

import json
import time
import re
import threading
import queue
import copy
from typing import TypedDict, Sequence, Dict, Any, Optional, Annotated, Generator
from pathlib import Path

from langgraph.graph import StateGraph, END, add_messages
from langgraph.checkpoint.memory import MemorySaver
from langchain.messages import HumanMessage, AIMessage
from langchain_core.messages import BaseMessage
from langchain_core.language_models import BaseLLM

import sys
import logging
logger = logging.getLogger(__name__)
sys.path.append(str(Path(__file__).parent.parent))
from prompts import get_master_intent_prompt, get_summary_prompt
from agents.sql_agent import SQLQueryAgent
from agents.analysis_agent import DataAnalysisAgent
from agents.search_agent import WebSearchAgent
from agents.answer_sample_agent import AnswerSampleAgent
from memory.long_term_memory import LongTermMemory
from memory.memory_extractor import MemoryExtractor


class MasterAgentState(TypedDict):
    """主智能体状态定义"""
    messages: Annotated[Sequence[BaseMessage], add_messages]  # 对话消息列表，包含用户和AI的历史消息
    user_question: str  # 当前用户问题
    intent: Optional[str]  # 识别出的意图
    sql_result: Optional[Dict[str, Any]]  # SQL查询结果
    analysis_result: Optional[Dict[str, Any]]  # 数据分析结果
    search_result: Optional[Dict[str, Any]]  # 联网搜索结果
    final_answer: Optional[str]  # 最终回答结果
    error: Optional[str]  # 错误信息
    metadata: Dict[str, Any]  # 用于存储额外信息，如用户ID、线程ID、查询结果等


class MasterAgent:
    """主智能体 - 协调SQL查询和数据分析子智能体"""
    
    @staticmethod
    def _llm_to_str(result) -> str:
        """安全地从 LLM 返回值中提取文本字符串"""
        from agents._utils import llm_to_str
        return llm_to_str(result)

    def _push_event(self, type_: str, **kwargs):
        """推送 SSE 事件到队列，供 stream_query 消费"""
        self._sse_queue.put({"type": type_, **kwargs})

    def _drain_events(self) -> Generator[str, None, None]:
        """排空事件队列，生成 SSE 格式字符串"""
        while True:
            try:
                event = self._sse_queue.get_nowait()
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
            except queue.Empty:
                break

    def _build_initial_state(self, question: str, thread_id: str, user_id: Optional[str]) -> Dict[str, Any]:
        """构建图的初始状态，保留上一轮的 sql_result / analysis_result / search_result"""
        state: Dict[str, Any] = {
            "messages": [HumanMessage(content=question)],
            "user_question": question,
            "intent": None,
            "final_answer": None,
            "error": None,
            "metadata": {"thread_id": thread_id, "user_id": user_id}
        }

        # 从 checkpointer 读取上一轮状态，保留非 None 的结果字段
        # 这样 analysis_only 意图可以复用上一轮的 sql_result
        config = {"configurable": {"thread_id": thread_id}}
        try:
            snapshot = self.graph.get_state(config)  # 从checkpointer 读取上一轮状态
            prev = snapshot.values
            for key in ("sql_result", "analysis_result", "search_result"):
                val = prev.get(key)
                if val is not None:
                    state[key] = val  # 保留上一轮结果
        except Exception:
            pass

        # 确保缺失的键有默认值
        for key in ("sql_result", "analysis_result", "search_result"):
            state.setdefault(key, None)

        return state

    def _save_transcript(self, messages: Sequence[BaseMessage], thread_id: str = "default", user_id: Optional[str] = None) -> Path:
        """将消息序列写入 JSONL 转录文件并返回路径
        
        用于日志记录和错误排查，保存完整的对话历史到磁盘。
        文件格式：.transcripts/transcript_{user_id}_{thread_id}_{timestamp}.jsonl
        
        Args:
            messages: 消息序列（HumanMessage/AIMessage）
            thread_id: 会话线程ID
            user_id: 用户ID
            
        Returns:
            转录文件的完整路径
        """
        # 确保转录目录存在
        self.transcript_dir.mkdir(parents=True, exist_ok=True)
        
        # 生成带用户ID和线程ID的文件名，便于追踪和检索
        timestamp = int(time.time())
        if user_id and user_id != "guest":
            filename = f"transcript_{user_id}_{thread_id}_{timestamp}.jsonl"
        else:
            filename = f"transcript_{thread_id}_{timestamp}.jsonl"
        
        ts_path = self.transcript_dir / filename
        
        try:
            with open(ts_path, "w", encoding="utf-8") as f:
                # 写入元数据头部（便于后续分析）
                metadata = {
                    "role": "system",
                    "content": "",
                    "metadata": {
                        "user_id": user_id,
                        "thread_id": thread_id,
                        "timestamp": timestamp,
                        "datetime": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(timestamp)),
                        "message_count": len(messages)
                    }
                }
                f.write(json.dumps(metadata, ensure_ascii=False) + "\n")
                
                # 逐条写入消息
                for idx, msg in enumerate(messages):
                    try:
                        if isinstance(msg, HumanMessage):
                            role = "user"
                            content = msg.content
                        elif isinstance(msg, AIMessage):
                            role = "assistant"
                            content = msg.content
                        else:
                            role = getattr(msg, "type", "unknown")
                            content = getattr(msg, "content", str(msg))
                        
                        # 处理 content 可能是列表的情况（如包含工具调用结果）
                        if isinstance(content, list):
                            content_str = json.dumps(content, ensure_ascii=False, default=str)
                        else:
                            content_str = str(content)
                        
                        log_entry = {
                            "role": role,
                            "content": content_str,
                            "index": idx
                        }
                        f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")
                        
                    except Exception as e:
                        # 单条消息失败不影响整体，记录错误并继续
                        error_entry = {
                            "role": "error",
                            "content": f"序列化消息失败: {str(e)}",
                            "index": idx
                        }
                        f.write(json.dumps(error_entry, ensure_ascii=False) + "\n")
                        logger.warning(f"[WARN] 转录消息 {idx} 失败: {e}")
            
            logger.info(f"[TRANSCRIPT] 对话已保存: {ts_path} user={user_id or 'anon'} thread={thread_id} msgs={len(messages)}")
            
        except Exception as e:
            logger.error(f"[ERROR] 写转录文件失败: {e}")
            import traceback
            traceback.print_exc()
        
        return ts_path

    def _invoke_llm_with_compact_check(self, prompt: str, state: Optional[MasterAgentState] = None):
        """调用 LLM 并检查模型是否请求手动压缩（[[COMPACT]]）。

        如果模型返回包含 [[COMPACT]] 的响应，会触发一次 auto_compact（基于 state 中的 messages）
        并在压缩后重新调用 LLM 一次以获得最终回答。
        """
        try:
            raw = self.llm.invoke(prompt)
            text = self._llm_to_str(raw)
            if "[[COMPACT]]" in text and state is not None:
                # 模型请求压缩，执行自动压缩并替换 checkpointer
                try:
                    msgs = list(state.get("messages", []))
                    thread_id = state.get("metadata", {}).get("thread_id", "default")
                    user_id = state.get("metadata", {}).get("user_id")
                    # 直接执行压缩并替换 checkpointer
                    self._compress_history_with_llm(msgs, state)
                except Exception as e:
                    logger.error(f"手动压缩触发失败: {e}")
                # 重新调用 LLM 一次以生成真实回答
                raw = self.llm.invoke(prompt)
            return raw
        except Exception:
            # 将异常抛出给调用方处理
            raise
    
    def __init__(self, llm: BaseLLM, db_path: str, num_examples: int = 3,
                short_term_max_tokens: int = 1000,
                tavily_api_key: str = "",
                chroma_path: str = "./data/chroma_db",
                max_knowledge_per_user: int = 100):
        """初始化主智能体

        Args:
            llm: 语言模型实例
            db_path: 数据库路径
            num_examples: Few-shot示例数量
            short_term_max_tokens: 短期记忆最大token数
            tavily_api_key: Tavily 搜索 API Key
            chroma_path: ChromaDB 向量数据库路径
            max_knowledge_per_user: 每用户知识条目上限
        """
        self.llm = llm
        self.db_path = db_path
        self.short_term_max_tokens = short_term_max_tokens

        # 初始化子智能体
        self.sql_agent = SQLQueryAgent(llm, db_path, num_examples)
        self.analysis_agent = DataAnalysisAgent(llm)
        self.search_agent = WebSearchAgent(llm, tavily_api_key=tavily_api_key)

        # 初始化短期记忆（MemorySaver）
        self.memory = MemorySaver()

        # 初始化长期记忆（LongTermMemory + ChromaDB）
        self.long_term_memory = LongTermMemory(
            chroma_path=chroma_path,
            max_knowledge_per_user=max_knowledge_per_user,
        )

        # 初始化记忆提取器
        self.memory_extractor = MemoryExtractor(llm)
        # 提取冷却追踪：{user_id: 上次提取时间戳}
        self._last_extraction_time: Dict[str, float] = {}
        # 提取冷却间隔（秒）
        self._extraction_cooldown = 300  # 5 分钟

        # 初始化闲聊/回答子智能体（AnswerSampleAgent）
        try:
            self.answer_agent = AnswerSampleAgent(
                self.llm,
                long_term_memory=self.long_term_memory,
            )
        except Exception as e:
            logger.error(f"初始化 AnswerSampleAgent 失败: {e}")
            self.answer_agent = None
        
        # SSE 事件队列（用于 stream_query 流式输出）
        self._sse_queue: queue.Queue = queue.Queue()
        # transcript 目录
        self.transcript_dir = Path(__file__).parent.parent / ".transcripts"
        self.transcript_dir.mkdir(exist_ok=True)
        
        # 构建工作流
        self.graph = self._build_graph()
    
    def _build_graph(self) -> StateGraph:
        """构建LangGraph状态图"""
        workflow = StateGraph(MasterAgentState)

        # 添加节点
        workflow.add_node("intent", self._intent_node)
        workflow.add_node("simple_answer", self._simple_answer_node)
        workflow.add_node("answer_sample", self._answer_sample_node)
        workflow.add_node("call_sql", self._call_sql_node)
        workflow.add_node("call_analysis", self._call_analysis_node)
        workflow.add_node("call_both", self._call_both_node)
        workflow.add_node("call_web_search", self._call_web_search_node)
        workflow.add_node("call_search_and_sql", self._call_search_and_sql_node)
        workflow.add_node("call_system_command", self._call_system_command_node)
        workflow.add_node("call_analysis_quick", self._call_analysis_quick_node)
        workflow.add_node("call_search_quick", self._call_search_quick_node)
        workflow.add_node("summarize", self._summarize_node)

        # 设置入口
        workflow.set_entry_point("intent")

        # 添加条件边 - 从意图识别到不同的处理节点
        workflow.add_conditional_edges(
            "intent",
            self._route_after_intent,
            {
                "simple_answer": "simple_answer",
                "answer_sample": "answer_sample",
                "sql_only": "call_sql",
                "analysis_only": "call_analysis",
                "sql_and_analysis": "call_both",
                "web_search": "call_web_search",
                "search_and_sql": "call_search_and_sql",
                "system_command": "call_system_command",
                "analysis_quick": "call_analysis_quick",
                "search_quick": "call_search_quick",
            }
        )

        # 添加边
        workflow.add_edge("simple_answer", END)
        workflow.add_edge("answer_sample", END)
        workflow.add_edge("call_sql", "summarize")
        workflow.add_edge("call_analysis", "summarize")
        workflow.add_edge("call_both", "summarize")
        workflow.add_edge("call_web_search", "summarize")
        workflow.add_edge("call_search_and_sql", "summarize")
        workflow.add_edge("call_system_command", "summarize")
        workflow.add_edge("call_analysis_quick", "summarize")
        workflow.add_edge("call_search_quick", "summarize")
        workflow.add_edge("summarize", END)

        # 使用MemorySaver作为checkpointer
        return workflow.compile(checkpointer=self.memory)
    
    def visualize(self, output_path: str = "graph.png"):
        """将工作流图保存为图片文件"""
        try:
            # draw_mermaid_png() 返回的是字节流 (bytes)
            png_data = self.graph.get_graph().draw_mermaid_png()
            with open(output_path, "wb") as f:
                f.write(png_data)
            logger.info(f"逻辑图已保存至: {output_path}")
        except Exception as e:
            logger.error(f"绘图失败: {e}")
            logger.info("提示：请确保已安装绘图依赖：pip install pygraphviz 或使用 draw_mermaid() 查看文本版")
    
    def _get_conversation_history(self, state: MasterAgentState) -> str:
        """获取对话历史摘要（三层递进式压缩）
        
        ===== 三层压缩策略详解 =====
        
        Layer 1 (微压缩)：轻量级占位符替换
          - 执行：_micro_compact(messages, keep_recent=6)
          - 作用：保留最近 6 个工具调用结果的完整内容
          - 之前的tool_result内容被替换为 [Previous: used xxx] 占位符
          - 好处：消息总数不变，但早期工具输出被大幅压缩
        
        Layer 2 (自动压缩)：基于 token 的 LLM 摘要  
          触发条件（缺一不可）：
            1. 消息数 > 11 条（快速路径）
            2. token 估算超过 short_term_max_tokens（核心条件）
          执行流程（见 _compress_history_with_llm）：
            a. 保存完整 transcript 到磁盘（日志记录）
            b. 取最近 50 条消息生成 prompt
            c. 调用 LLM 生成不超过 300 字的摘要
            d. 将摘要替换掉整个 messages，写回 checkpointer
        
        Layer 3 (手动压缩)：模型主动请求
          - 触发：模型返回 [[COMPACT]] 特殊标记（见 _invoke_llm_with_compact_check）
          - 行为：立即执行一次 Layer 2 压缩，然后 LLM 重试生成最终答案
        
        Args:
            state: 当前状态
            
        Returns:
            对话历史文本或压缩摘要
        """
        messages = list(state.get("messages", []))

        # 深拷贝原始 messages，用于 Layer 2 保存完整 transcript
        # 必须用 deepcopy，因为 _micro_compact 会原地修改 tool_result 的 content 字段
        original_messages = copy.deepcopy(messages)

        # ===== Layer 1：微压缩（占位符替换） =====
        # keep_recent=6 表示保留最近 6 个工具调用结果的完整内容
        # 更早期的 tool_result 被替换成占位符（如 [Previous: used read_file]）
        # 如果没有 tool_result，则回退到保留最近 6 条完整消息，其他长消息(>500字符)被截断
        messages = self._micro_compact(messages, keep_recent=6)

        if len(messages) <= 1:
            return ""

        # 构建原始历史文本（排除当前/最后一条消息）
        history_text = self._format_messages(messages[:-1])

        # ===== Layer 2 快速路径：消息数少则直接返回 =====
        # 当消息数 <= 11 时，通常 token 数不会很多，直接返回无需 Layer 2
        if len(messages) <= 11:
            return history_text

        # ===== Layer 2 核心条件：Token 超限检测 =====
        # 简单 token 估算（中文按 2 字/token，英文按 4 字/token）
        estimated_tokens = len(history_text) / 2.5

        # 如果 token 未超限，保持消息完整（不执行 LLM 压缩）
        if estimated_tokens <= self.short_term_max_tokens:
            return history_text

        # Token 超限 → 触发 Layer 2：保存完整 transcript（用截断前的原始消息）、LLM 摘要、回写 checkpointer
        return self._compress_history_with_llm(original_messages, state)
    
    def _format_messages(self, messages: Sequence[BaseMessage]) -> str:
        """格式化消息列表为文本
        
        Args:
            messages: 消息列表
            
        Returns:
            格式化的文本
        """
        history = []
        for msg in messages:
            if isinstance(msg, HumanMessage):
                history.append(f"用户: {msg.content}")
            elif isinstance(msg, AIMessage):
                history.append(f"助手: {msg.content}")
        
        return "\n".join(history) if history else ""
    
    def _compress_history_with_llm(self, history_text: str, state: Optional[MasterAgentState] = None) -> str:
        """Layer 2 自动压缩：基于 LLM 的对话历史摘要（三层策略中的第二层）
        
        ===== Layer 2 执行流程 =====
        
        1. 前置条件：
           - 消息数 > 11
           - token 估算 > short_term_max_tokens
           (由 _get_conversation_history 确保)
        
        2. 处理步骤：
           a) 保存完整 transcript 到磁盘
              - 目的：保留完整记录用于日志审计和错误排查
              - 文件位置：.transcripts/transcript_{user_id}_{thread_id}_{timestamp}.jsonl
           
           b) 提取最近 50 条消息
              - 避免 prompt 过长而导致超出上下文限制
              - 格式化为文本用于 LLM 总结
           
           c) LLM 生成摘要
              - 调用大模型生成不超过 300 字的摘要
              - 保留：关键事实、用户偏好、重要上下文
              - 移除：重复内容、冗长细节
           
           d) 写回 checkpointer
              - 将摘要替换掉整个 messages 列表
              - 对于后续会话，从 checkpointer 读取时将直接获得压缩摘要
              - 这实现了"记忆遗忘"的效果
        
        ===== Layer 3 集成点 =====
        
        - 此函数由 _invoke_llm_with_compact_check() 间接调用
        - 若模型返回 [[COMPACT]] 标记，LayerDetect 会主动触发本函数
        - 压缩完成后，LLM 会被重新调用以生成最终回答
        
        Args:
            history_text: 对话历史（通常是消息列表，为了兼容传入文本）
            state: 当前状态（包含用户ID、线程ID等元数据）
            
        Returns:
            压缩后的摘要文本（格式：[对话已压缩]\n元数据\ntranscript路径\n\n摘要内容）
        """
        # 保留最近 N 条消息不压缩，只摘要更早的消息
        KEEP_RECENT = 6

        try:
            # messages may be passed in instead of raw text
            if isinstance(history_text, list):
                messages = history_text

                # 获取元数据
                user_id = None
                thread_id = "default"
                if state is not None:
                    user_id = state.get("metadata", {}).get("user_id")
                    thread_id = state.get("metadata", {}).get("thread_id", "default")

                logger.info(f"[COMPRESS] 触发对话压缩 user={user_id or 'anon'} thread={thread_id} msgs={len(messages)}")

                # Layer 2: 保存完整 transcript 到磁盘（用于日志和错误排查）
                ts_path = self._save_transcript(messages, thread_id, user_id)
                logger.debug(f"[COMPRESS] 转录文件: {ts_path}")

                # 拆分：需要摘要的旧消息 + 保留完整的新消息
                if len(messages) > KEEP_RECENT:
                    to_summarize = messages[:-KEEP_RECENT]
                    keep_messages = messages[-KEEP_RECENT:]
                else:
                    # 消息太少，全部保留不摘要
                    to_summarize = []
                    keep_messages = messages

                logger.debug(f"[COMPRESS] 摘要 {len(to_summarize)} 条，保留 {len(keep_messages)} 条完整")

                # 将需要摘要的消息格式化为文本（限前100条避免 prompt 过长）
                summarize_text = self._format_messages(to_summarize[:100]) if to_summarize else "（无早期对话）"

                prompt = f"""请总结以下对话历史，保留关键信息、用户偏好和重要上下文。完整对话已保存为：{ts_path}

{summarize_text}

总结要求：
1. 保留关键事实和数据（如查询的部门、员工、数据结果）
2. 提取用户关注点和偏好
3. 保留重要的上下文信息
4. 简洁但信息完整
5. 不超过300字

请在摘要开头包含一行简短的身份元数据，格式示例：user_id:<user_id> thread_id:<thread_id>（如果可用）

总结："""
            else:
                # 兼容旧接口：直接传入文本
                prompt = f"""请总结以下对话历史，保留关键信息、用户偏好和重要上下文：

{history_text}

总结要求：
1. 保留关键事实和数据（如查询的部门、员工、数据结果）
2. 提取用户关注点和偏好
3. 保留重要的上下文信息
4. 简洁但信息完整
5. 不超过300字

总结："""
                
                ts_path = None
            
            # 调用 LLM 生成摘要
            summary = self._llm_to_str(self.llm.invoke(prompt)).strip()
            logger.info(f"[COMPRESS] 摘要生成成功，长度: {len(summary)} 字符")

            # 显式注入最小身份元数据，便于后续恢复
            identity_line = ""
            if state is not None:
                uid = state.get("metadata", {}).get("user_id")
                tid = state.get("metadata", {}).get("thread_id", "default")
                if uid:
                    identity_line = f"user_id:{uid} thread_id:{tid}"
                else:
                    identity_line = f"thread_id:{tid}"

            compressed_content = f"[对话已压缩]\n{identity_line}\nTranscript: {ts_path}\n\n{summary}"

            # 将压缩摘要写入长期记忆，防止会话间信息丢失
            if state is not None:
                uid = state.get("metadata", {}).get("user_id")
                if uid:
                    try:
                        self.long_term_memory.save_knowledge(
                            uid,
                            "对话摘要",
                            summary[:500],
                            confidence=0.6,
                        )
                        logger.debug(f"[COMPRESS] 摘要已写入长期记忆 user={uid}")
                    except Exception as e:
                        logger.error(f"[COMPRESS] 摘要写入长期记忆失败: {e}")

            # 如果提供了 state，就将压缩后的消息写回 checkpointer
            # 关键：摘要 + 保留的最近消息，而不是只写摘要
            if state is not None:
                try:
                    cfg = {"configurable": {"thread_id": state.get("metadata", {}).get("thread_id", "default")}}
                    summary_msg = HumanMessage(content=compressed_content)
                    new_msgs = [summary_msg] + list(keep_messages)
                    # 把压缩后的消息写回 LangGraph 的 checkpointer（as_node 使用 summarize 保持一致）
                    self.graph.update_state(cfg, {"messages": new_msgs}, as_node="summarize")
                    logger.info(f"[COMPRESS] 压缩摘要已写回 checkpointer（摘要1条 + 保留{len(keep_messages)}条）")
                except Exception as e:
                    logger.error(f"[ERROR] 回写压缩摘要到 checkpointer 失败: {e}")
                    import traceback
                    traceback.print_exc()

            return f"[对话历史总结]\n{summary}"
            
        except Exception as e:
            logger.error(f"[ERROR] 压缩对话历史失败: {e}")
            import traceback
            traceback.print_exc()
            
            # 如果压缩失败，返回最近的部分对话作为降级方案
            if isinstance(history_text, list):
                recent_msgs = history_text[-20:]
                fallback_text = self._format_messages(recent_msgs)
                logger.warning(f"[WARN] 使用降级方案：返回最近 {len(recent_msgs)} 条消息")
                return fallback_text
            else:
                lines = history_text.split("\n")
                recent_lines = lines[-20:] if len(lines) > 20 else lines
                fallback_text = "\n".join(recent_lines)
                logger.warning(f"[WARN] 使用降级方案：返回最近 {len(recent_lines)} 行")
                return fallback_text

    def _micro_compact(self, messages: Sequence[BaseMessage], keep_recent: int = 6) -> Sequence[BaseMessage]:
        """对旧的对话消息进行轻量压缩：把早期消息替换为简短占位符。

        Args:
            messages: 原始消息序列
            keep_recent: 保留最近完整消息数量

        Returns:
            新的消息序列（副本）
        """
        # 实现 learn-claude 风格的 micro_compact：
        # 1) 优先识别消息中以 tool_result 形式存在的工具输出，替换旧的 tool_result 为占位符（保留最近 keep_recent 个）
        # 2) 如果没有发现 tool_result，则回退到按整条消息替换的策略
        msgs = list(messages)

        # 收集所有 tool_result 条目 (msg_index, part_index, part_dict)
        tool_results = []
        for msg_idx, msg in enumerate(msgs):
            content = getattr(msg, "content", None)
            if isinstance(content, list):
                for part_idx, part in enumerate(content):
                    if isinstance(part, dict) and part.get("type") == "tool_result":
                        tool_results.append((msg_idx, part_idx, part))

        # 如果找到了 tool_result，则按 tool_result 做轻量压缩
        if tool_results:
            if len(tool_results) <= keep_recent:
                return msgs

            # 尝试从之前的 assistant 消息中构建 tool_use_id -> tool_name 的映射（若可用）
            tool_name_map = {}
            for m in msgs:
                if isinstance(m, AIMessage):
                    c = getattr(m, "content", None)
                    if isinstance(c, list):
                        for blk in c:
                            if isinstance(blk, dict) and blk.get("type") == "tool_use":
                                tool_name_map[blk.get("id")] = blk.get("name")

            to_clear = tool_results[:-keep_recent]
            for msg_idx, part_idx, part in to_clear:
                content = part.get("content", "")
                # 跳过短内容
                if not isinstance(content, str) or len(content) <= 100:
                    continue
                tool_id = part.get("tool_use_id", "")
                tool_name = tool_name_map.get(tool_id, "unknown")
                # 保留 read_file 输出（参考资料）
                if tool_name == "read_file":
                    continue
                placeholder = f"[Previous: used {tool_name}]" if tool_name != "unknown" else "[Previous: tool_result]"
                part["content"] = placeholder
            return msgs

        # 回退策略：只压缩长内容消息（>500字符），短消息保持原样
        if len(msgs) <= keep_recent + 1:
            return msgs

        cutoff = max(0, len(msgs) - keep_recent)
        new_msgs = []
        for i, m in enumerate(msgs):
            if i < cutoff:
                try:
                    text = m.content if hasattr(m, "content") else str(m)
                except Exception:
                    text = str(m)
                # 只压缩长内容（>500字符），短消息保留原文
                if len(text) > 500:
                    snippet = text[:200] + "..."
                    placeholder = f"[已压缩早期消息] {snippet}"
                    if isinstance(m, HumanMessage):
                        new_msgs.append(HumanMessage(content=placeholder))
                    elif isinstance(m, AIMessage):
                        new_msgs.append(AIMessage(content=placeholder))
                    else:
                        new_msgs.append(m)
                else:
                    new_msgs.append(m)
            else:
                new_msgs.append(m)
        return new_msgs
    
    def _format_long_term_context(
        self, 
        knowledge: list, 
        preferences: Dict[str, str]
    ) -> str:
        """格式化长期记忆上下文
        
        Args:
            knowledge: 用户知识列表
            preferences: 用户偏好字典
            
        Returns:
            格式化的上下文文本
        """
        context_parts = []
        
        # 添加用户偏好
        if preferences:
            pref_lines = [f"- {key}: {value}" for key, value in preferences.items()]
            context_parts.append("用户偏好：\n" + "\n".join(pref_lines))
        
        # 添加相关知识
        if knowledge:
            know_lines = [f"- {item['content']}" for item in knowledge[:3]]
            context_parts.append("相关背景：\n" + "\n".join(know_lines))
        
        return "\n\n".join(context_parts) if context_parts else ""
    
    def _intent_node(self, state: MasterAgentState) -> MasterAgentState:
        """意图识别节点（支持6种意图）"""
        question = state["user_question"]  # ← 读状态
        user_id = state["metadata"].get("user_id")

        self._push_event("status", message="正在识别问题意图...")
        logger.debug(f"[DEBUG MasterAgent] 意图识别节点: {question}")
        
        # 获取对话历史（短期记忆）
        conversation_history = self._get_conversation_history(state)
        logger.debug(f"[DEBUG] 对话历史长度: {len(conversation_history)} 字符")
        
        # 获取用户知识（长期记忆）
        user_context = ""
        if user_id:
            try:
                knowledge = self.long_term_memory.get_relevant_knowledge(user_id, question, top_k=3)
                preferences = self.long_term_memory.get_all_preferences(user_id)
                user_context = self._format_long_term_context(knowledge, preferences)
                logger.debug(f"[DEBUG] 用户上下文长度: {len(user_context)} 字符")
            except Exception as e:
                logger.error(f"[ERROR] 获取长期记忆失败: {e}")
        
        prompt = get_master_intent_prompt(question, conversation_history, user_context)
        logger.debug(f"[DEBUG] 意图识别 Prompt 长度: {len(prompt)} 字符")
        
        try:
            raw = self._invoke_llm_with_compact_check(prompt, state)
            response = self._llm_to_str(raw).strip()
            logger.debug(f"[DEBUG] LLM 原始返回: {repr(response)}")
            
            intent = response.lower().strip()  # 确保模型返回的结果是小写且没有多余空格
            logger.debug(f"[DEBUG] 处理后意图: {repr(intent)}")
            
            valid_intents = [
                "simple_answer", "sql_only", "analysis_only",
                "sql_and_analysis", "web_search", "search_and_sql",
                "answer_sample", "system_command",
                "analysis_quick", "search_quick"
            ]
            
            original_intent = intent
            if intent not in valid_intents:
                logger.debug(f"[DEBUG] 意图 '{intent}' 不在有效列表中，尝试子串匹配...")
                matched = None
                for valid_intent in valid_intents:
                    if valid_intent in intent:
                        matched = valid_intent
                        break
                intent = matched or "simple_answer"
                if matched:
                    logger.debug(f"[DEBUG] 子串匹配到: {matched}")
                else:
                    logger.warning(f"[WARN] 无法匹配有效意图 (原始: {original_intent})，降级为 simple_answer")
            
            state["intent"] = intent  # 修改状态
            state["metadata"]["intent_response"] = response
            logger.debug(f"[DEBUG] ✓ 最终意图: {intent} (原始: {original_intent})")
            self._push_event("intent", intent=intent)
            
        except Exception as e:
            error_msg = f"意图识别失败: {str(e)}"
            logger.error(f"[ERROR] {error_msg}")
            import traceback
            traceback.print_exc()
            state["error"] = error_msg
            state["intent"] = "simple_answer"
        
        return state
    
    def _route_after_intent(self, state: MasterAgentState) -> str:
        """意图识别后的路由（支持10种意图）"""
        intent = state.get("intent", "simple_answer")
        logger.debug(f"[DEBUG MasterAgent] 路由到: {intent}")

        # 如果需要搜索但搜索不可用，降级为 simple_answer
        if intent in ("web_search", "search_and_sql", "search_quick") and not self.search_agent.available:
            logger.warning("[WARN] 搜索智能体不可用，意图降级为 simple_answer")
            fallback_msg = (
                "联网搜索功能暂未启用。请配置 TAVILY_API_KEY 环境变量后重启系统。\n"
                "申请地址：https://tavily.com（免费账户即可）"
            )
            state["final_answer"] = fallback_msg
            self._push_event("error", message=fallback_msg)
            return "simple_answer"

        return intent
    
    def _simple_answer_node(self, state: MasterAgentState) -> MasterAgentState:
        """简单问答节点：直接用大模型生成答案"""
        question = state["user_question"]
        self._push_event("status", message="正在生成回答...")
        try:
            answer = self._llm_to_str(self.llm.invoke(question))
        except Exception as e:
            answer = f"智能问答出错：{e}"
        state["final_answer"] = answer
        state["messages"] = state["messages"] + [AIMessage(content=answer)]
        self._push_event("chunk", content=answer)
        self._push_event("done", answer=answer)
        return state

    def _answer_sample_node(self, state: MasterAgentState) -> MasterAgentState:
        """闲聊/开放式回答节点：使用 AnswerSampleAgent 生成回答"""
        question = state["user_question"]
        thread_id = state["metadata"].get("thread_id", "default")
        self._push_event("status", message="正在生成回答...")

        # 从 graph state 获取对话历史，传给 AnswerSampleAgent
        messages = list(state.get("messages", []))
        conversation_history = self._format_messages(messages[:-1]) if len(messages) > 1 else ""

        try:
            if getattr(self, 'answer_agent', None) is None:
                logger.warning("[WARN] AnswerSampleAgent 未初始化，回退到直接调用 LLM")
                answer = self._llm_to_str(self.llm.invoke(question))
            else:
                res = self.answer_agent.query(
                    question,
                    thread_id=thread_id,
                    conversation_history=conversation_history
                )
                if res.get("error"):
                    answer = f"回答生成失败：{res.get('error')}"
                    logger.error(f"[ERROR] {answer}")
                else:
                    answer = res.get("answer", "")
        except Exception as e:
            answer = f"回答生成异常：{str(e)}"
            logger.error(f"[ERROR] {answer}")

        state["final_answer"] = answer
        state["messages"] = list(state["messages"]) + [AIMessage(content=answer)]

        self._push_event("chunk", content=answer)
        self._push_event("done", answer=answer)
        return state

    def _call_analysis_quick_node(self, state: MasterAgentState) -> MasterAgentState:
        """快速分析节点：对已有数据做简单分析、对比、排序，不需要深度建模"""
        question = state["user_question"]
        self._push_event("status", message="正在快速分析...")

        sql_result = state.get("sql_result")
        if not sql_result or "data" not in sql_result:
            state["error"] = "没有找到可以分析的数据。请先进行数据查询。"
            state["analysis_result"] = {"error": "无可用数据"}
            self._push_event("error", message="没有可分析的数据，请先执行数据查询")
            return state

        try:
            # 快速分析使用简化提示词，不要求深度报告
            data = sql_result["data"]
            from prompts import get_analysis_prompt
            data_summary = str(data)[:1000] if data else "无数据"
            raw_data = str(data)[:3000] if data else "无数据"
            prompt = get_analysis_prompt(
                data_summary,
                raw_data,
                context=f"用户要求快速分析：{question}。请简洁回答，突出关键对比和排序结果，不需要长篇报告。"
            )
            raw = self._invoke_llm_with_compact_check(prompt, state)
            analysis_text = self._llm_to_str(raw)

            result = {"analysis": analysis_text, "chart": None}
            state["analysis_result"] = result
            state["metadata"]["analysis_result"] = result
            logger.info("[INFO] 快速分析完成")
        except Exception as e:
            state["error"] = f"快速分析失败: {str(e)}"
            state["analysis_result"] = {"error": str(e)}

        return state

    def _call_search_quick_node(self, state: MasterAgentState) -> MasterAgentState:
        """快速搜索节点：快速联网搜索即时信息，不需要深度整理"""
        question = state["user_question"]
        self._push_event("status", message="正在搜索...")

        try:
            result = self.search_agent.search(question)
            state["search_result"] = result
            state["metadata"]["search_result"] = result

            if result.get("error"):
                self._push_event("error", message=f"搜索出错: {result['error']}")
        except Exception as e:
            state["error"] = f"快速搜索失败: {str(e)}"
            state["search_result"] = {"error": str(e)}

        return state

    def _call_sql_node(self, state: MasterAgentState) -> MasterAgentState:
        """调用SQL查询子智能体"""
        question = state["user_question"]

        self._push_event("status", message="正在查询数据库...")
        try:
            result = self.sql_agent.query(question)
            state["sql_result"] = result
            state["metadata"]["sql_result"] = result

            if result.get("sql"):
                self._push_event("sql", sql=result["sql"], retry_count=result.get("retry_count", 0))
            if result.get("error"):
                self._push_event("error", message=f"数据库查询出错: {result['error']}")
        except Exception as e:
            state["error"] = f"SQL查询失败: {str(e)}"
            state["sql_result"] = {"error": str(e)}

        return state
    
    def _call_analysis_node(self, state: MasterAgentState) -> MasterAgentState:
        """调用数据分析子智能体"""
        question = state["user_question"]

        self._push_event("status", message="正在分析数据...")

        sql_result = state.get("sql_result")
        if not sql_result or "data" not in sql_result:
            state["error"] = "没有找到可以分析的数据。请先进行数据查询。"
            state["analysis_result"] = {"error": "无可用数据"}
            self._push_event("error", message="没有可分析的数据，请先执行数据查询")
            return state

        try:
            result = self.analysis_agent.analyze(sql_result["data"], question)
            state["analysis_result"] = result
            state["metadata"]["analysis_result"] = result
            if result.get("chart"):
                self._push_event("chart", config=result["chart"])
        except Exception as e:
            state["error"] = f"数据分析失败: {str(e)}"
            state["analysis_result"] = {"error": str(e)}

        return state
    
    def _call_both_node(self, state: MasterAgentState) -> MasterAgentState:
        """先调用SQL查询，再调用数据分析"""
        question = state["user_question"]

        try:
            self._push_event("status", message="正在查询数据库...")
            sql_result = self.sql_agent.query(question)
            state["sql_result"] = sql_result
            state["metadata"]["sql_result"] = sql_result

            if sql_result.get("sql"):
                self._push_event("sql", sql=sql_result["sql"], retry_count=sql_result.get("retry_count", 0))
            if sql_result.get("error"):
                state["error"] = f"SQL查询失败: {sql_result['error']}"
                self._push_event("error", message=f"数据库查询出错: {sql_result['error']}")
                return state

            if sql_result.get("data"):
                self._push_event("status", message="正在分析数据...")
                analysis_result = self.analysis_agent.analyze(sql_result["data"], question)
                state["analysis_result"] = analysis_result
                state["metadata"]["analysis_result"] = analysis_result
                if analysis_result.get("chart"):
                    self._push_event("chart", config=analysis_result["chart"])
                if analysis_result.get("error"):
                    state["error"] = f"数据分析失败: {analysis_result['error']}"
            else:
                state["error"] = "查询结果为空，无法进行分析"

        except Exception as e:
            state["error"] = f"执行失败: {str(e)}"

        return state
    
    def _call_web_search_node(self, state: MasterAgentState) -> MasterAgentState:
        """联网搜索节点（纯搜索模式）"""
        question = state["user_question"]

        self._push_event("status", message="正在联网搜索...")
        try:
            search_result = self.search_agent.search(question)
            state["search_result"] = search_result
            state["metadata"]["search_result"] = search_result

            if search_result.get("sources"):
                self._push_event("sources", sources=search_result["sources"])
            if search_result.get("error"):
                state["error"] = search_result["error"]
                self._push_event("error", message=search_result["error"])
        except Exception as e:
            state["error"] = f"联网搜索失败: {str(e)}"

        return state
    
    def _call_search_and_sql_node(self, state: MasterAgentState) -> MasterAgentState:
        """联网搜索 + 数据库查询联合分析节点"""
        question = state["user_question"]

        try:
            self._push_event("status", message="正在查询数据库...")
            sql_result = self.sql_agent.query(question)
            state["sql_result"] = sql_result
            state["metadata"]["sql_result"] = sql_result

            if sql_result.get("sql"):
                self._push_event("sql", sql=sql_result["sql"], retry_count=sql_result.get("retry_count", 0))

            self._push_event("status", message="正在联网搜索行业数据...")
            sql_data = sql_result.get("data", "{}") or "{}"
            search_result = self.search_agent.search_and_compare(question, sql_data)
            state["search_result"] = search_result
            state["metadata"]["search_result"] = search_result

            if search_result.get("sources"):
                self._push_event("sources", sources=search_result["sources"])
            if search_result.get("error") and not sql_result.get("error"):
                state["error"] = search_result["error"]
                self._push_event("error", message=search_result["error"])
        except Exception as e:
            state["error"] = f"联合分析失败: {str(e)}"

        return state
    
    def _call_system_command_node(self, state: MasterAgentState) -> MasterAgentState:
        """系统命令执行节点：处理文件系统操作和系统命令
        
        注意：出于安全考虑，仅允许执行安全的只读命令
        - 允许：ls/dir（列目录）、cat/type（读文件）、pwd/cd（查看路径）
        - 禁止：rm/del（删除）、写入文件、执行脚本等危险操作
        """
        import platform
        import subprocess
        import os
        
        question = state["user_question"]
        user_id = state["metadata"].get("user_id")
        
        # 检测当前操作系统
        current_os = platform.system()  # Windows / Linux / Darwin(Mac)
        is_windows = current_os == "Windows"

        logger.debug(f"[DEBUG MasterAgent] 系统命令节点: {question} os={current_os}")
        self._push_event("status", message="正在执行系统命令...")

        # 白名单 + 元字符校验
        _ALLOWED_PREFIXES_WIN = {
            "dir", "type", "cd", "pwd", "echo", "systeminfo",
            "tasklist", "wmic", "powershell", "where", "hostname",
            "ver", "findstr",
        }
        _ALLOWED_PREFIXES_UNIX = {
            "ls", "cat", "head", "tail", "wc", "grep", "find",
            "pwd", "echo", "date", "whoami", "uname", "df",
            "du", "free", "ps", "top", "hostname", "id",
        }
        _DANGEROUS_CHARS = (';', '&', '|', '`', '$', '>', '<', '\n')

        def _validate_command(cmd: str) -> Optional[str]:
            """校验命令安全性，返回错误消息（None 表示通过）"""
            allowed = _ALLOWED_PREFIXES_WIN if is_windows else _ALLOWED_PREFIXES_UNIX
            first_word = cmd.strip().lower().split()[0] if cmd.strip() else ""
            # 去掉 .exe 后缀匹配
            base = first_word.removesuffix(".exe")
            if base not in allowed:
                return f"命令 '{first_word}' 不在允许列表中。系统仅支持只读操作。"
            if any(ch in cmd for ch in _DANGEROUS_CHARS):
                return "检测到 shell 元字符（如 ; & | ` $），已阻止执行。"
            return None
        
        try:
            # 首先让LLM分析用户意图，提取需要执行的命令
            # 关键：明确告知LLM当前操作系统，让它生成对应的命令
            os_hint = "Windows系统" if is_windows else ("MacOS系统" if current_os == "Darwin" else "Linux系统")
            
            command_prompt = f"""你是一个系统命令助手，需要将用户的自然语言转换为安全的系统命令。

【重要】当前操作系统：{os_hint} ({current_os})
请根据操作系统生成对应的命令！

用户请求：{question}

请分析用户需求，如果需要执行系统命令，请返回一个JSON对象：
{{
    "command": "具体的命令",
    "explanation": "命令说明",
    "safe": true/false  // 是否安全
}}

【操作系统特定的命令示例】
- Windows系统：
  - 列目录：dir
  - 读文件：type filename.txt
  - 查看路径：cd
  - 读取文件前N行：powershell -Command "Get-Content filename.txt -TotalCount N"
  - 查找文件：dir /s /b filename
  
- Linux/Mac系统：
  - 列目录：ls -la
  - 读文件：cat filename.txt
  - 查看路径：pwd
  - 读取文件前N行：head -n N filename.txt
  - 查找文件：find . -name "filename"

【安全规则】
- ✅ 允许的只读命令：
  - Windows: dir, type, cd, pwd, echo, findstr, powershell (只读操作)
  - Linux/Mac: ls, cat, head, tail, wc, grep, find, pwd, cd, echo
- ❌ 禁止的命令：rm, del, mv, cp（写操作）, chmod, chown, sudo, exec, eval
- ❌ 禁止管道符组合复杂命令（Windows的 | 除外，用于简单过滤）
- ❌ 禁止重定向输出到文件（>, >>）
- ❌ 禁止执行脚本文件（.sh, .bat, .exe, .ps1）

如果请求不安全或无法理解，返回：
{{
    "command": "",
    "explanation": "无法执行该请求的原因",
    "safe": false
}}

只返回JSON，不要其他内容。"""
            
            raw = self._invoke_llm_with_compact_check(command_prompt, state)
            response_text = self._llm_to_str(raw).strip()

            # 解析LLM返回的JSON（可能包含在代码块中）
            json_match = re.search(r'\{[\s\S]*\}', response_text)
            if json_match:
                cmd_info = json.loads(json_match.group())
            else:
                cmd_info = json.loads(response_text)
            
            # 检查安全性
            if not cmd_info.get("safe", False):
                answer = f"⚠️ 无法执行该请求：{cmd_info.get('explanation', '安全限制')}"
                logger.warning(f"[WARN] 命令被拒绝: {cmd_info.get('explanation')}")
            elif not cmd_info.get("command"):
                answer = f"❓ 无法理解您的需求：{cmd_info.get('explanation', '请提供更清晰的指令')}"
                logger.warning(f"[WARN] 无有效命令: {cmd_info.get('explanation')}")
            else:
                # 执行命令
                command = cmd_info["command"]
                logger.debug(f"[DEBUG] 准备执行命令: {command}")

                err = _validate_command(command)
                if err:
                    answer = f"⚠️ {err}"
                    logger.error(f"[ERROR] 命令校验失败: {err}")
                else:
                    # 执行命令（设置超时5秒）
                    max_retries = 2  # 最多重试2次
                    retry_count = 0
                    last_error = ""
                    answer = None  # 初始化answer变量，避免作用域问题
                    
                    while retry_count <= max_retries:
                        try:
                            if retry_count > 0:
                                logger.debug(f"[DEBUG] 第{retry_count}次重试执行命令...")
                            
                            result = subprocess.run(
                                command,
                                shell=True,
                                capture_output=True,
                                text=True,
                                timeout=5,
                                cwd=os.getcwd()  # 在当前工作目录执行
                            )
                            
                            if result.returncode == 0:
                                output = result.stdout.strip()
                                if not output:
                                    output = "（命令执行成功，但无输出）"
                                
                                answer = f"✅ 命令执行结果：\n\n```\n{output}\n```\n\n💡 说明：{cmd_info.get('explanation', '')}"
                                logger.debug(f"[DEBUG] 命令执行成功，输出长度: {len(output)}")
                                break  # 成功则退出循环
                            else:
                                error_msg = result.stderr.strip()
                                last_error = error_msg
                                logger.error(f"[ERROR] 命令执行失败 (尝试{retry_count + 1}/{max_retries + 1}): {error_msg}")
                                
                                # 如果还有重试次数，让LLM生成替代命令
                                if retry_count < max_retries:
                                    retry_prompt = f"""上一个命令执行失败了，请提供一个替代命令。

原始请求：{question}
失败的命令：{command}
错误信息：{error_msg}
当前操作系统：{os_hint} ({current_os})

请分析错误原因，并提供一个能在{os_hint}上正常工作的替代命令。
返回JSON格式：
{{
    "command": "新的命令",
    "explanation": "为什么这个命令能解决问题"
}}

只返回JSON。"""
                                    
                                    raw_retry = self._invoke_llm_with_compact_check(retry_prompt, state)
                                    retry_text = self._llm_to_str(raw_retry).strip()
                                    
                                    # 解析重试命令
                                    json_match = re.search(r'\{[\s\S]*\}', retry_text)
                                    if json_match:
                                        retry_info = json.loads(json_match.group())
                                        new_cmd = retry_info.get("command", "")
                                        # 校验重试命令的安全性
                                        retry_err = _validate_command(new_cmd) if new_cmd else "空命令"
                                        if retry_err:
                                            answer = f"⚠️ 替代命令不安全：{retry_err}"
                                            logger.error(f"[ERROR] 重试命令校验失败: {retry_err}")
                                            break
                                        command = new_cmd
                                        logger.debug(f"[DEBUG] LLM建议的替代命令: {command}")
                                    else:
                                        logger.warning(f"[WARN] 无法解析LLM的重试建议")
                                        break
                                
                                retry_count += 1
                        
                        except subprocess.TimeoutExpired:
                            answer = "⏱️ 命令执行超时（超过5秒），已终止。"
                            logger.error(f"[ERROR] 命令执行超时")
                            break
                        except Exception as e:
                            answer = f"❌ 执行出错：{str(e)}"
                            logger.error(f"[ERROR] 执行异常: {e}")
                            break
                    
                    # 如果所有重试都失败（answer仍然为None）
                    if answer is None:
                        answer = f"❌ 命令执行失败（已尝试{max_retries + 1}次）：\n\n错误信息：{last_error}\n\n💡 建议：\n- 请检查文件名是否正确\n- 确认文件是否存在于当前目录\n- 可以尝试使用其他方式查看文件内容"
                        logger.error(f"[ERROR] 所有重试均失败")
        
        except Exception as e:
            answer = f"❌ 系统命令处理异常：{str(e)}"
            logger.error(f"[ERROR] {answer}")
            import traceback
            traceback.print_exc()
        
        state["final_answer"] = answer
        state["messages"] = list(state["messages"]) + [AIMessage(content=answer)]

        logger.debug(f"[DEBUG] ✓ 系统命令节点完成，回答长度: {len(answer)}")
        self._push_event("chunk", content=answer)
        self._push_event("done", answer=answer)

        return state

    def _summarize_node(self, state: MasterAgentState) -> MasterAgentState:
        """汇总结果节点 — 流式 LLM 输出，通过事件队列推送 token"""
        question = state["user_question"]
        intent = state.get("intent", "sql_only")

        self._push_event("status", message="正在生成回答...")

        # 预设回答已经生成（如降级处理 / simple_answer / answer_sample）
        if state.get("final_answer"):
            state["messages"] = list(state["messages"]) + [AIMessage(content=state["final_answer"])]
            self._push_event("chunk", content=state["final_answer"])
            self._push_event("done", answer=state["final_answer"])
            return state

        if state.get("error"):
            state["final_answer"] = f"抱歉，处理过程中出现错误：{state['error']}"
            state["messages"] = list(state["messages"]) + [AIMessage(content=state["final_answer"])]
            self._push_event("chunk", content=state["final_answer"])
            self._push_event("done", answer=state["final_answer"])
            return state

        sql_result = state.get("sql_result")
        analysis_result = state.get("analysis_result")
        search_result = state.get("search_result")

        # 联网搜索相关意图：搜索智能体已生成完整回答
        if intent in ("web_search", "search_and_sql") and search_result:
            if search_result.get("error"):
                answer = f"搜索出错：{search_result['error']}"
            else:
                answer = search_result.get("answer", "未能获取搜索结果")
                sources = search_result.get("sources", [])
                if sources:
                    answer += "\n\n**参考来源：**\n" + "\n".join(
                        f"- {url}" for url in sources[:5]
                    )
            state["final_answer"] = answer
            state["messages"] = list(state["messages"]) + [AIMessage(content=answer)]
            self._push_event("chunk", content=answer)
            self._push_event("done", answer=answer)
            return state

        # 数据库查询/分析相关意图
        sql_data = None
        analysis_data = None

        if sql_result:
            if sql_result.get("error"):
                err = f"查询出错：{sql_result['error']}"
                state["final_answer"] = err
                state["messages"] = list(state["messages"]) + [AIMessage(content=err)]
                self._push_event("error", message=err)
                self._push_event("done", answer=err)
                return state
            sql_data = sql_result.get("data")

        if analysis_result:
            if analysis_result.get("error"):
                err = f"分析出错：{analysis_result['error']}"
                state["final_answer"] = err
                state["messages"] = list(state["messages"]) + [AIMessage(content=err)]
                self._push_event("error", message=err)
                self._push_event("done", answer=err)
                return state
            analysis_data = analysis_result.get("analysis")
            if analysis_result.get("chart"):
                state["metadata"]["chart"] = analysis_result["chart"]

        # 流式生成汇总回答
        try:
            prompt = get_summary_prompt(
                question=question,
                sql_result=sql_data,
                analysis_result=analysis_data
            )

            final_answer = ""
            in_think = False
            think_buffer = ""
            for chunk in self.llm.stream(prompt):
                chunk_text = (
                    chunk.content if hasattr(chunk, "content")
                    else chunk.text if hasattr(chunk, "text")
                    else str(chunk)
                )

                # 过滤 <think>...</think> 思考内容
                think_buffer += chunk_text
                if "<think>" in think_buffer and not in_think:
                    in_think = True
                if in_think:
                    if "</think>" in think_buffer:
                        cleaned = re.sub(r"<think>[\s\S]*?</think>", "", think_buffer).strip()
                        if cleaned:
                            final_answer += cleaned
                            self._push_event("chunk", content=cleaned)
                        think_buffer = ""
                        in_think = False
                    continue

                think_buffer = ""
                final_answer += chunk_text
                self._push_event("chunk", content=chunk_text)

            state["final_answer"] = final_answer
            state["messages"] = list(state["messages"]) + [AIMessage(content=final_answer)]
            self._push_event("done", answer=final_answer)

        except Exception as e:
            err_msg = f"生成回答时出错：{str(e)}"
            state["final_answer"] = err_msg
            self._push_event("error", message=err_msg)
            self._push_event("done", answer=err_msg)

        # 检测导出意图：用户要求导出 PDF 报告
        export_keywords = ("导出", "生成报告", "下载报告", "pdf", "PDF", "打印报告", "导出报告")
        if any(kw in question for kw in export_keywords):
            self._push_event("status", message="正在生成 PDF 报告...")
            try:
                report_result = self.analysis_agent.export_report(
                    title=question[:30],
                    analysis_text=analysis_data or "",
                    table_headers=list(sql_data[0].keys()) if sql_data and isinstance(sql_data[0], dict) else None,
                    table_rows=sql_data if sql_data else None,
                    sql_query=state.get("sql_result", {}).get("sql", "") if state.get("sql_result") else "",
                )
                if report_result.get("path"):
                    report_msg = f"\n\nPDF 报告已生成：{report_result['path']}"
                    state["final_answer"] = (state.get("final_answer") or "") + report_msg
                    self._push_event("report", path=report_result["path"])
                elif report_result.get("error"):
                    err_msg = f"\n\n报告导出失败：{report_result['error']}"
                    state["final_answer"] = (state.get("final_answer") or "") + err_msg
                    self._push_event("error", message=report_result["error"])
            except Exception as e:
                logger.error(f"[Report] 导出异常: {e}")

        return state
    
    def query(self, question: str, thread_id: str = "default", user_id: Optional[str] = None) -> str:
        """执行查询
        
        Args:
            question: 用户问题
            thread_id: 线程ID，用于区分不同的会话
            user_id: 用户ID，用于长期记忆
            
        Returns:
            回答结果
        """
        initial_state = self._build_initial_state(question, thread_id, user_id)
        
        # 使用checkpointer保存会话状态
        config = {"configurable": {"thread_id": thread_id}}
        
        final_state = self.graph.invoke(initial_state, config)
        
        answer = final_state.get("final_answer", "抱歉，无法处理你的问题。")
        
        # 获取完整的对话历史（已经包含了当前的问题和回答）
        all_messages = list(final_state["messages"])
        
        logger.info(f"[记忆] 当前会话共有 {len(all_messages)} 条消息")
        
        # 自动提取并保存长期记忆
        if user_id:
            self._extract_and_save_memory(all_messages, user_id)
        
        return answer

    def compact(self, thread_id: str = "default", user_id: Optional[str] = None, focus: Optional[str] = None) -> str:
        """对指定会话执行手动压缩（Layer3 compact tool 风格）。

        会将当前 checkpointer 中的 messages 保存为 transcript，调用 LLM 生成摘要，
        并将压缩摘要写回 checkpointer（替换活动 messages）。返回生成的摘要文本。
        """
        config = {"configurable": {"thread_id": thread_id}}
        try:
            snapshot = self.graph.get_state(config)
            msgs = list(snapshot.values.get("messages", []))
        except Exception:
            msgs = []

        temp_state: MasterAgentState = {
            "messages": msgs,
            "user_question": "",
            "intent": None,
            "sql_result": None,
            "analysis_result": None,
            "search_result": None,
            "final_answer": None,
            "error": None,
            "metadata": {"thread_id": thread_id, "user_id": user_id}
        }

        return self._compress_history_with_llm(msgs, temp_state)
    
    def list_transcripts(self, user_id: Optional[str] = None, thread_id: Optional[str] = None, limit: int = 20) -> list:
        """列出转录文件
        
        Args:
            user_id: 过滤特定用户的转录
            thread_id: 过滤特定线程的转录
            limit: 返回的最大数量
            
        Returns:
            转录文件信息列表
        """
        if not self.transcript_dir.exists():
            return []
        
        transcripts = []
        for file in sorted(self.transcript_dir.glob("transcript_*.jsonl"), reverse=True):
            filename = file.name
            
            # 解析文件名提取元数据
            parts = filename.replace("transcript_", "").replace(".jsonl", "").split("_")
            
            # 尝试提取用户ID和线程ID
            file_user_id = None
            file_thread_id = None
            
            if len(parts) >= 3:
                # 格式：user_id_thread_id_timestamp
                file_user_id = parts[0]
                file_thread_id = parts[1]
            elif len(parts) == 2:
                # 格式：thread_id_timestamp
                file_thread_id = parts[0]
            
            # 应用过滤器
            if user_id and file_user_id != user_id:
                continue
            if thread_id and file_thread_id != thread_id:
                continue
            
            # 读取文件头部获取更多信息
            try:
                with open(file, 'r', encoding='utf-8') as f:
                    first_line = f.readline()
                    metadata = json.loads(first_line)
                    file_metadata = metadata.get('metadata', {})
                    
                    transcripts.append({
                        "file": str(file),
                        "filename": filename,
                        "user_id": file_user_id or file_metadata.get('user_id'),
                        "thread_id": file_thread_id or file_metadata.get('thread_id'),
                        "timestamp": file_metadata.get('timestamp'),
                        "datetime": file_metadata.get('datetime'),
                        "message_count": file_metadata.get('message_count', 0)
                    })
            except Exception as e:
                logger.warning(f"[WARN] 读取转录文件失败 {filename}: {e}")
        
        return transcripts[:limit]
    
    def get_transcript(self, filepath: str) -> list:
        """读取转录文件内容
        
        Args:
            filepath: 转录文件路径
            
        Returns:
            消息列表
        """
        messages = []
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                for line_num, line in enumerate(f, 1):
                    try:
                        entry = json.loads(line.strip())
                        messages.append(entry)
                    except Exception as e:
                        logger.warning(f"[WARN] 解析第 {line_num} 行失败: {e}")
        except Exception as e:
            logger.error(f"[ERROR] 读取转录文件失败: {e}")
        
        return messages

    def _extract_and_save_memory(self, messages: Sequence[BaseMessage], user_id: str):
        """自动提取并保存长期记忆。

        设计原则：
        - 攒够上下文再提取（>= 10 条有效消息），不每次请求都提取
        - 时间冷却（同用户 5 分钟内不重复提取）
        - 单次 LLM 调用同时出偏好 + 知识
        - 传入已有知识让 LLM 避免重复提取
        """
        import time

        try:
            # 1. 过滤有效消息：只要 Human/AI 的文本对话，跳过工具调用等
            dialog_messages = [
                m for m in messages
                if isinstance(m, (HumanMessage, AIMessage))
                and hasattr(m, "content")
                and isinstance(m.content, str)
                and len(m.content.strip()) > 5
            ]

            # 2. 消息量门槛：攒够 10 条有效对话再提取
            if len(dialog_messages) < 10:
                return

            # 3. 时间冷却：同用户 5 分钟内不重复提取
            now = time.time()
            last_time = self._last_extraction_time.get(user_id, 0)
            if now - last_time < self._extraction_cooldown:
                logger.debug(f"[LTM] 用户 {user_id} 提取冷却中，跳过")
                return

            # 4. 拉取已有知识（让 LLM 避免重复提取）
            try:
                existing = self.long_term_memory.get_all_knowledge(user_id, limit=30)
                existing_contents = [item["content"] for item in existing]
            except Exception:
                existing_contents = []

            # 5. 取足够多的上下文（最多 30 条），给 LLM 足够信息
            recent = dialog_messages[-30:]

            # 6. 单次 LLM 调用，同时提取偏好和知识
            result = self.memory_extractor.extract_all(recent, existing_contents)

            # 7. 持久化偏好
            for key, value in result.get("preferences", {}).items():
                self.long_term_memory.save_preference(user_id, key, str(value))

            # 8. 持久化知识（ChromaDB 层面还会再做一次去重兜底）
            saved_count = 0
            for knowledge in result.get("knowledge", []):
                ok = self.long_term_memory.save_knowledge(
                    user_id,
                    knowledge.get("category", "其他"),
                    knowledge.get("content", ""),
                    knowledge.get("confidence", 0.8),
                )
                if ok:
                    saved_count += 1

            # 9. 更新冷却时间
            self._last_extraction_time[user_id] = now
            logger.info(
                f"[LTM] 提取完成 user={user_id}: "
                f"{len(result.get('preferences', {}))} 偏好, "
                f"{saved_count}/{len(result.get('knowledge', []))} 新知识 "
                f"(来自 {len(recent)} 条对话)"
            )

        except Exception as e:
            logger.error(f"提取记忆失败: {e}")

    def extract_session_memory(self, user_id: str, thread_id: str = "default"):
        """会话结束时触发：从当前线程的所有消息中提取长期记忆。

        跳过冷却检查，确保会话结束时一定提取。

        Args:
            user_id: 用户 ID
            thread_id: 线程 ID
        """
        import time

        if not user_id:
            return

        try:
            config = {"configurable": {"thread_id": thread_id}}
            snapshot = self.graph.get_state(config)
            all_messages = list(snapshot.values.get("messages", []))

            if not all_messages:
                logger.debug(f"[LTM] 会话 {thread_id} 无消息，跳过提取")
                return

            # 过滤有效消息
            dialog_messages = [
                m for m in all_messages
                if isinstance(m, (HumanMessage, AIMessage))
                and hasattr(m, "content")
                and isinstance(m.content, str)
                and len(m.content.strip()) > 5
            ]

            if len(dialog_messages) < 4:
                logger.debug(f"[LTM] 有效消息不足 ({len(dialog_messages)})，跳过提取")
                return

            # 拉取已有知识
            try:
                existing = self.long_term_memory.get_all_knowledge(user_id, limit=30)
                existing_contents = [item["content"] for item in existing]
            except Exception:
                existing_contents = []

            # 单次 LLM 调用
            recent = dialog_messages[-30:]
            result = self.memory_extractor.extract_all(recent, existing_contents)

            # 持久化
            for key, value in result.get("preferences", {}).items():
                self.long_term_memory.save_preference(user_id, key, str(value))

            saved_count = 0
            for knowledge in result.get("knowledge", []):
                if self.long_term_memory.save_knowledge(
                    user_id,
                    knowledge.get("category", "其他"),
                    knowledge.get("content", ""),
                    knowledge.get("confidence", 0.8),
                ):
                    saved_count += 1

            # 更新冷却时间
            self._last_extraction_time[user_id] = time.time()
            logger.info(
                f"[LTM] 会话结束提取完成 user={user_id} thread={thread_id}: "
                f"{len(result.get('preferences', {}))} 偏好, "
                f"{saved_count} 新知识"
            )

        except Exception as e:
            logger.error(f"会话结束提取失败: {e}")

    def stream_query(
        self,
        question: str,
        thread_id: str = "default",
        user_id: Optional[str] = None
    ) -> Generator[str, None, None]:
        """流式查询 — 通过 LangGraph graph 执行，事件队列驱动 SSE 输出

        图节点在后台线程运行，主线程持续从事件队列消费并 yield SSE 字符串。
        所有意图路由、子智能体调用、汇总生成均由 graph 节点完成。

        Yields:
            SSE 格式字符串：data: {...}\\n\\n
        """
        config = {"configurable": {"thread_id": thread_id}}
        initial_state = self._build_initial_state(question, thread_id, user_id)

        # 后台线程执行 LangGraph
        graph_error = None
        def run_graph():
            nonlocal graph_error
            try:
                self.graph.invoke(initial_state, config)
            except Exception as e:
                graph_error = e
                self._push_event("error", message=f"处理失败: {e}")
                self._push_event("done", answer="")

        graph_thread = threading.Thread(target=run_graph, daemon=True)
        graph_thread.start()

        # 主线程：持续排空事件队列，yield SSE
        final_answer = ""
        while True:
            try:
                event = self._sse_queue.get(timeout=0.5)
                if event.get("type") == "done":
                    final_answer = event.get("answer", final_answer)
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
            except queue.Empty:
                if not graph_thread.is_alive():
                    # 线程已结束，排空剩余事件
                    for sse_str in self._drain_events():
                        yield sse_str
                    break

        # 后处理：保存转录 + 提取记忆
        try:
            snapshot = self.graph.get_state(config)
            all_msgs = list(snapshot.values.get("messages", []))
            logger.info(f"[stream_query] 完成 user={user_id or 'anon'} thread={thread_id} "
                        f"answer_len={len(final_answer)} msgs={len(all_msgs)}")

            ts_path = self._save_transcript(all_msgs, thread_id, user_id)
            logger.debug(f"[stream_query] 转录已保存: {ts_path}")

            if user_id:
                self._extract_and_save_memory(all_msgs, user_id)
                logger.debug("[stream_query] 长期记忆已更新")
        except Exception as e:
            logger.error(f"[ERROR] 保存对话历史失败（不影响本次回答）: {e}")
