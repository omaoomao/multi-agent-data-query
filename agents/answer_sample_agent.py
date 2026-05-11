"""
AnswerSampleAgent - 使用 DashScope 原生 tool_use 的 Agent Loop

核心设计：
- 使用 llm.bind_tools(TOOLS) 绑定工具到 LLM
- 模型通过 tool_calls 结构化返回工具调用（不再用文本正则）
- 使用 SystemMessage / HumanMessage / AIMessage / ToolMessage 管理对话

接口:
- __init__(llm, long_term_memory=None)
- query(question, thread_id='default', conversation_history='') -> Dict[str, Any]
"""

import logging
from typing import Dict, Any

from langchain_core.messages import SystemMessage, HumanMessage, AIMessage, ToolMessage
from agents.tools import TOOLS, TOOL_DISPATCH

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """你是一个有用的助手，可以使用工具来帮助用户解决问题。

行为准则：
1. 执行系统命令前，先检测操作系统类型（Windows/Linux/Mac）
2. 根据系统类型选择合适的命令
3. 基于工具返回的实际数据给出简洁明了的回答
4. 如果工具执行失败，告诉用户失败原因和建议
5. 已有充分信息时直接回答，不再调用工具"""


class AnswerSampleAgent:
    """使用原生 tool_use 的 Agent：LLM → Tool Dispatch → Loop"""

    def __init__(self, llm, long_term_memory=None):
        self.llm = llm
        self.long_term_memory = long_term_memory
        self.llm_with_tools = llm.bind_tools(TOOLS)

    def query(self, question: str, thread_id: str = "default", conversation_history: str = "", max_loops: int = 15) -> Dict[str, Any]:
        """执行查询，模型自主决定工具调用。

        conversation_history: 由 MasterAgent 从 graph state 格式化的对话历史文本。
        """
        logger.debug(f"[AnswerSampleAgent] 开始处理: {question[:80]}")

        try:
            messages = [SystemMessage(content=SYSTEM_PROMPT)]
            if conversation_history:
                messages.append(HumanMessage(content=f"对话历史:\n{conversation_history}"))
            messages.append(HumanMessage(content=question))

            consecutive_failures = 0
            last_tool_command = None

            for loop_count in range(max_loops):
                logger.debug(f"[AnswerSampleAgent] Loop {loop_count + 1}/{max_loops}")

                # 检查连续失败
                if consecutive_failures >= 3:
                    logger.warning(f"连续失败 {consecutive_failures} 次，强制结束")
                    return {
                        "answer": "抱歉，我在尝试获取信息时遇到了问题。可能您的系统不支持相关命令，或存在权限限制。请尝试手动操作或换个问题。",
                        "error": None,
                    }

                # 调用 LLM（已绑定工具）
                try:
                    response = self.llm_with_tools.invoke(messages)
                except Exception as e:
                    logger.error(f"LLM 调用失败: {e}")
                    return {"answer": None, "error": str(e)}

                # 检查模型是否要调用工具
                if response.tool_calls:
                    messages.append(response)  # 将 AI message（含 tool_calls）加入历史

                    for tool_call in response.tool_calls:
                        tool_name = tool_call["name"]
                        tool_args = tool_call["args"]
                        tool_id = tool_call["id"]

                        logger.debug(f"[AnswerSampleAgent] 工具调用: {tool_name}({tool_args})")

                        # 检测重复失败命令
                        if tool_name == "run_bash":
                            current_command = tool_args.get("command", "")
                            if current_command == last_tool_command:
                                consecutive_failures += 1
                                logger.warning(f"重复命令，连续失败: {consecutive_failures}")
                            else:
                                consecutive_failures = 0
                            last_tool_command = current_command

                        # 执行工具
                        if tool_name in TOOL_DISPATCH:
                            try:
                                tool_result = TOOL_DISPATCH[tool_name].invoke(tool_args)
                                logger.debug(f"[AnswerSampleAgent] 工具结果长度: {len(tool_result)}")

                                # 检查错误结果
                                if tool_result.startswith("Error:") or "不是内部或外部命令" in tool_result:
                                    consecutive_failures += 1
                                elif tool_name != "run_bash":
                                    consecutive_failures = 0
                            except Exception as e:
                                tool_result = f"Tool execution error: {e}"
                                logger.error(f"工具执行失败: {e}")
                                consecutive_failures += 1
                        else:
                            tool_result = f"Unknown tool: {tool_name}"
                            logger.warning(f"未知工具: {tool_name}")
                            consecutive_failures += 1

                        # 将工具结果作为 ToolMessage 加入历史
                        messages.append(ToolMessage(content=str(tool_result), tool_call_id=tool_id))

                    continue  # 继续循环，让模型基于工具结果决定下一步
                else:
                    # 没有工具调用 → 最终回答
                    logger.debug(f"[AnswerSampleAgent] 最终回答，长度: {len(response.content)}")
                    return {"answer": response.content, "error": None}

            # 达到最大循环次数
            logger.warning(f"达到最大循环次数 ({max_loops})")
            return {"answer": "抱歉，经过多次尝试未能完成任务。请换个方式提问。", "error": None}

        except Exception as e:
            logger.exception("AnswerSampleAgent 异常")
            return {"answer": None, "error": str(e)}
