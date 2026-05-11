"""
记忆提取器

从对话历史中自动提取用户偏好和知识。
支持单次 LLM 调用同时提取偏好+知识，并利用已有知识避免重复提取。
"""

import json
from typing import List, Dict, Any, Optional
from langchain.messages import HumanMessage, AIMessage
from langchain_core.messages import BaseMessage
from langchain_core.language_models import BaseLLM


import logging
logger = logging.getLogger(__name__)


class MemoryExtractor:
    """从对话中提取长期记忆"""

    def __init__(self, llm: BaseLLM):
        self.llm = llm

    @staticmethod
    def _llm_to_str(result) -> str:
        """安全地从 LLM 返回值中提取文本，清理思考标签"""
        from agents._utils import llm_to_str
        return llm_to_str(result)

    @staticmethod
    def _parse_json_response(response: str) -> Any:
        """从 LLM 响应中安全解析 JSON"""
        text = response.strip()
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            text = text.split("```")[1].split("```")[0].strip()
        return json.loads(text)

    def extract_all(
        self,
        messages: List[BaseMessage],
        existing_knowledge: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """单次 LLM 调用同时提取偏好和知识。

        Args:
            messages: 对话消息列表（建议传整个会话，最多 30 条）
            existing_knowledge: 已有的知识内容列表，用于提示 LLM 不要重复

        Returns:
            {"preferences": {key: value}, "knowledge": [{category, content, confidence}]}
        """
        if len(messages) < 4:
            return {"preferences": {}, "knowledge": []}

        conversation_text = self._format_conversation(messages)

        # 已有知识上下文（让 LLM 避免重复提取）
        existing_block = ""
        if existing_knowledge:
            items = "\n".join(f"  - {c}" for c in existing_knowledge[:30])
            existing_block = f"""
以下是你已经记录的知识，不要重复提取这些内容：
{items}

只提取上面没有提到的【新】信息。如果没有新信息，对应字段返回空。
"""

        prompt = f"""分析以下完整会话，提取长期记忆信息。{existing_block}

对话内容：
{conversation_text}

请返回以下 JSON 格式（只返回 JSON，不要其他文字）：
{{
    "preferences": {{
        "key1": "value1",
        "key2": "value2"
    }},
    "knowledge": [
        {{
            "category": "分类",
            "content": "具体知识点描述",
            "confidence": 0.8
        }}
    ]
}}

提取规则：
1. preferences：用户的交互偏好、关注领域、常用查询方向等，key 自由定义，不限枚举
2. knowledge：值得跨会话记住的业务事实、用户习惯、关键数据结论等
3. confidence（0-1）：该信息在对话中的明确程度
4. 如果没有值得提取的信息，preferences 返回 {{}}，knowledge 返回 []
5. 知识描述要具体完整，不要写模糊的概括（如 "用户关注数据"）
"""

        try:
            response = self._llm_to_str(self.llm.invoke(prompt)).strip()
            result = self._parse_json_response(response)

            preferences = result.get("preferences", {})
            knowledge = result.get("knowledge", [])

            # 校验格式
            if not isinstance(preferences, dict):
                preferences = {}
            if not isinstance(knowledge, list):
                knowledge = []
            # 过滤无效条目
            knowledge = [
                k for k in knowledge
                if isinstance(k, dict) and k.get("content", "").strip()
            ]

            logger.info(
                f"[Extractor] 提取完成: {len(preferences)} 条偏好, {len(knowledge)} 条知识"
            )
            return {"preferences": preferences, "knowledge": knowledge}

        except Exception as e:
            logger.error(f"提取记忆失败: {e}")
            return {"preferences": {}, "knowledge": []}

    # ------------------------------------------------------------------
    # 保留旧接口向后兼容（内部委托给 extract_all）
    # ------------------------------------------------------------------

    def extract_preferences_from_conversation(
        self,
        messages: List[BaseMessage],
        user_id: str,
    ) -> Dict[str, Any]:
        """从对话中提取用户偏好（兼容旧接口）"""
        result = self.extract_all(messages)
        return result["preferences"]

    def extract_knowledge_from_conversation(
        self,
        messages: List[BaseMessage],
        user_id: str,
    ) -> List[Dict[str, Any]]:
        """从对话中提取用户知识点（兼容旧接口）"""
        result = self.extract_all(messages)
        return result["knowledge"]

    # ------------------------------------------------------------------
    # 工具方法
    # ------------------------------------------------------------------

    def _format_conversation(self, messages: List[BaseMessage]) -> str:
        """格式化对话历史为文本"""
        lines = []
        for msg in messages:
            if isinstance(msg, HumanMessage):
                content = msg.content[:500] if len(msg.content) > 500 else msg.content
                lines.append(f"用户: {content}")
            elif isinstance(msg, AIMessage):
                content = msg.content[:500] if len(msg.content) > 500 else msg.content
                lines.append(f"助手: {content}")
        return "\n".join(lines)

    def should_extract(self, messages: List[BaseMessage], threshold: int = 10) -> bool:
        """判断是否应该提取记忆

        Args:
            messages: 消息列表
            threshold: 消息数量阈值（默认 10，攒够上下文再提取）

        Returns:
            是否应该提取
        """
        return len(messages) >= threshold
