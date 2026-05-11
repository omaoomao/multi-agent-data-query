"""
智能体模块

包含主智能体和子智能体的实现。
"""

__all__ = ['MasterAgent', 'SQLQueryAgent', 'DataAnalysisAgent', 'WebSearchAgent', 'AnswerSampleAgent']


def __getattr__(name):
	if name == 'MasterAgent':
		from .master_agent import MasterAgent
		return MasterAgent
	if name == 'SQLQueryAgent':
		from .sql_agent import SQLQueryAgent
		return SQLQueryAgent
	if name == 'DataAnalysisAgent':
		from .analysis_agent import DataAnalysisAgent
		return DataAnalysisAgent
	if name == 'WebSearchAgent':
		from .search_agent import WebSearchAgent
		return WebSearchAgent
	if name == 'AnswerSampleAgent':
		from .answer_sample_agent import AnswerSampleAgent
		return AnswerSampleAgent
	raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

