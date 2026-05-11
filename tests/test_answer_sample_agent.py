import pytest
import importlib.util
import pathlib

from langchain_core.messages import AIMessage

# Import AnswerSampleAgent directly from file to avoid importing package-level side-effects
agent_path = pathlib.Path(__file__).parent.parent / "agents" / "answer_sample_agent.py"
spec = importlib.util.spec_from_file_location("answer_sample_agent", str(agent_path))
answer_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(answer_mod)
AnswerSampleAgent = answer_mod.AnswerSampleAgent


class DummyLLM:
    """LLM stub with preset AIMessage responses."""
    def __init__(self, responses):
        self._responses = list(responses)
        self.invocation_calls = []

    def invoke(self, messages):
        self.invocation_calls.append(messages)
        if self._responses:
            return self._responses.pop(0)
        return AIMessage(content="DUMMY_DEFAULT")

    def bind_tools(self, tools):
        """Return self — tool binding is a no-op for testing."""
        return self


def test_instantiation():
    """Test basic instantiation with bind_tools."""
    llm = DummyLLM([AIMessage(content="Hello")])
    agent = AnswerSampleAgent(llm)
    assert agent is not None
    assert agent.llm_with_tools is llm  # bind_tools returns self


def test_query_simple_response():
    """Test simple non-tool query returns AIMessage content."""
    llm = DummyLLM([AIMessage(content="This is a helpful response.")])
    agent = AnswerSampleAgent(llm)
    res = agent.query("What is the meaning of life?")
    assert res["error"] is None
    assert res["answer"] == "This is a helpful response."


def test_tool_call_native():
    """Test native tool_calls from AIMessage are dispatched correctly."""
    tool_call_msg = AIMessage(
        content="",
        tool_calls=[{
            "name": "run_bash",
            "args": {"command": "echo hello"},
            "id": "call_1",
        }],
    )
    final_msg = AIMessage(content="The command returned: hello")
    llm = DummyLLM([tool_call_msg, final_msg])
    agent = AnswerSampleAgent(llm)
    res = agent.query("Run a command for me")
    assert res["error"] is None
    assert res["answer"] == "The command returned: hello"
    # Should have 2 LLM calls: tool call + final response
    assert len(llm.invocation_calls) == 2


def test_multiple_tool_calls():
    """Test agent can make multiple tool calls in sequence."""
    first_call = AIMessage(
        content="",
        tool_calls=[{"name": "run_bash", "args": {"command": "echo step1"}, "id": "call_1"}],
    )
    second_call = AIMessage(
        content="",
        tool_calls=[{"name": "run_bash", "args": {"command": "echo step2"}, "id": "call_2"}],
    )
    final_msg = AIMessage(content="Both commands completed.")
    llm = DummyLLM([first_call, second_call, final_msg])
    agent = AnswerSampleAgent(llm)
    res = agent.query("Run multiple commands")
    assert res["error"] is None
    assert res["answer"] == "Both commands completed."
    assert len(llm.invocation_calls) == 3


def test_unknown_tool():
    """Test unknown tool returns error message in ToolMessage."""
    tool_call_msg = AIMessage(
        content="",
        tool_calls=[{"name": "nonexistent_tool", "args": {}, "id": "call_1"}],
    )
    final_msg = AIMessage(content="Done.")
    llm = DummyLLM([tool_call_msg, final_msg])
    agent = AnswerSampleAgent(llm)
    res = agent.query("Do something")
    assert res["error"] is None
    # The ToolMessage should have been sent with "Unknown tool" content
    # Check that messages list grew (SystemMessage + HumanMessage + AIMessage + ToolMessage + HumanMessage + AIMessage)
    assert len(llm.invocation_calls[1]) >= 4  # Second call should have tool result messages


def test_llm_error():
    """Test LLM exception returns error dict."""
    class ErrorLLM:
        def invoke(self, messages):
            raise RuntimeError("API error")
        def bind_tools(self, tools):
            return self

    agent = AnswerSampleAgent(ErrorLLM())
    res = agent.query("Hello")
    assert res["error"] is not None
    assert "API error" in res["error"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
