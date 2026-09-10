"""
SiliconDreams — LangChain ReAct Agent
======================================
查询路由 + 工具调用 + 强制计算规则

核心规则:
- 任何涉及数字比较/比率的问题，必须先调用 financial_calculator
- 禁止 LLM 自行心算
"""

from __future__ import annotations

import logging
from typing import Optional

from langchain.agents import AgentExecutor, create_react_agent
from langchain.tools import Tool
from langchain.prompts import PromptTemplate
from langchain_openai import ChatOpenAI

from config import LLMConfig

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════
# ReAct Prompt 模板（含强制计算规则）
# ═══════════════════════════════════════════════════

REACT_PROMPT = PromptTemplate.from_template("""You are SiliconDreams, an AI investment research analyst specializing in electronics/semiconductors.

Core capabilities:
1. Precisely retrieve data from financial reports (tables, figures, ratios)
2. Analyze business impact with semiconductor technology expertise
3. Generate structured industry research reports

## Financial Calculation Rules (MANDATORY)
- Any question involving numerical comparison, ratio calculation, or growth rates MUST call the financial_calculator tool first
- NEVER perform manual mental calculations on financial data
- After calculation, explain results in natural language

## Available Tools
{tools}

## Tool Names
{tool_names}

## Workflow
Use ReAct pattern: Thought -> Action -> Observation -> ... -> Final Answer

Thought: Analyze user intent, determine which tools are needed
Action: Call tool (JSON format)
Observation: Observe tool output
... (repeat until sufficient information is gathered)
Final Answer: Provide final answer in Markdown format

## Citation Rules
- When citing financial report data, mark with [source pN]
- Include formulas and calculation steps with financial results

## Question
{input}

## Agent Scratchpad
{agent_scratchpad}""")


# ═══════════════════════════════════════════════════
# Agent 构建器
# ═══════════════════════════════════════════════════

class SiliconDreamsAgent:
    """
    行研 Agent 管理器。

    用法:
        agent = SiliconDreamsAgent()
        response = agent.run("台积电2024年毛利率同比变化？")
    """

    def __init__(self):
        self._tools = self._build_tools()
        self._llm = self._build_llm()
        self._agent = self._build_agent()

    def _build_llm(self):
        """创建 LangChain 兼容的 DeepSeek LLM"""
        return ChatOpenAI(
            model=LLMConfig.model,
            api_key=LLMConfig.api_key,
            base_url=LLMConfig.api_base,
            temperature=LLMConfig.temperature,
            max_tokens=LLMConfig.max_tokens,
            streaming=False,  # Agent 内部调用不用流式
        )

    def _build_tools(self) -> list[Tool]:
        """组装 Agent 工具集"""
        tools = []

        # 1. RAG 检索
        try:
            from src.tools.search import create_search_tool
            tools.append(create_search_tool())
        except Exception as e:
            logger.warning(f"search 工具加载失败: {e}")

        # 2. 财务计算器（核心）
        try:
            from src.tools.calculator import create_calculator_tool
            tools.append(create_calculator_tool())
        except Exception as e:
            logger.warning(f"calculator 工具加载失败: {e}")

        # 3. 技术趋势分析
        try:
            from src.tools.analyze import create_analyze_tool
            tools.append(create_analyze_tool())
        except Exception as e:
            logger.warning(f"analyze 工具加载失败: {e}")

        # 4. 公司对比
        try:
            from src.tools.compare import create_compare_tool
            tools.append(create_compare_tool())
        except Exception as e:
            logger.warning(f"compare 工具加载失败: {e}")

        return tools

    def _build_agent(self) -> AgentExecutor:
        """构建 ReAct Agent"""
        react_agent = create_react_agent(
            llm=self._llm,
            tools=self._tools,
            prompt=REACT_PROMPT,
        )
        return AgentExecutor(
            agent=react_agent,
            tools=self._tools,
            verbose=LLMConfig.verbose if hasattr(LLMConfig, 'verbose') else False,
            max_iterations=6,
            handle_parsing_errors=True,
            return_intermediate_steps=False,
        )

    def run(self, query: str) -> str:
        """
        执行 Agent 查询。

        Args:
            query: 用户问题

        Returns:
            Agent 最终回答
        """
        try:
            result = self._agent.invoke({"input": query})
            return result.get("output", "[Agent returned no result]")
        except Exception as e:
            logger.error(f"Agent 执行失败: {e}")
            return (
                f"Analysis error: {e}\n\n"
                "Please try rephrasing your question, or check whether relevant data exists in the knowledge base."
            )

    # ── 查询路由 ────────────────────────────────────

    @staticmethod
    def route_query(query: str) -> str:
        """
        Determine user intent, return route label.

        Returns:
            "finance" | "technology" | "compare" | "general"
        """
        finance_keywords = [
            "revenue", "gross margin", "net margin", "ROE", "profit", "cost",
            "YoY", "QoQ", "growth rate", "assets", "liabilities", "cash flow",
            "financial", "earnings", "quarterly", "annual report",
            "营收", "毛利率", "净利率", "利润", "成本",
            "同比", "环比", "增长率", "资产", "负债", "现金流",
            "财务", "报表", "季度", "年报",
        ]
        tech_keywords = [
            "process", "technology", "node", "architecture", "3nm", "5nm", "7nm",
            "packaging", "lithography", "EUV", "EDA", "chip design", "HBM",
            "AI chip", "silicon carbide", "SiC", "GaN", "semiconductor",
            "制程", "技术", "工艺", "架构",
            "封装", "光刻", "芯片设计",
            "第三代半导体",
        ]
        compare_keywords = [
            "compare", "comparison", "versus", "vs", "better", "difference",
            "competition", "landscape", "peer",
            "对比", "比较", "区别", "优劣", "竞争", "格局",
            "孰优", "谁更强", "哪个好",
        ]

        has_finance = any(kw.lower() in query.lower() for kw in finance_keywords)
        has_tech = any(kw.lower() in query.lower() for kw in tech_keywords)
        has_compare = any(kw.lower() in query.lower() for kw in compare_keywords)

        if has_compare:
            return "compare"
        elif has_finance and not has_tech:
            return "finance"
        elif has_tech:
            return "technology"
        else:
            return "general"


# ── 便捷函数 ──────────────────────────────────────────

_agent_instance: Optional[SiliconDreamsAgent] = None


def get_agent() -> SiliconDreamsAgent:
    """获取 Agent 单例"""
    global _agent_instance
    if _agent_instance is None:
        _agent_instance = SiliconDreamsAgent()
    return _agent_instance
