"""
SiliconDreams — 术语知识图谱管理
==================================
- 加载本地 JSON 术语字典
- 查询注入：检测用户问题中的术语 → 注入定义+商业影响到 Prompt
"""

import json
import logging
from pathlib import Path
from typing import Optional, Union, Tuple, List, Dict

from config import TERMINOLOGY_FILE

logger = logging.getLogger(__name__)


class TerminologyManager:
    """
    半导体术语管理器（单例）。

    用法:
        tm = TerminologyManager()
        matches = tm.find_terms("3nm制程对毛利率的影响")
        context = tm.build_context("3nm制程对毛利率的影响")
    """

    _instance: Optional["TerminologyManager"] = None
    _terms: dict = {}
    _aliases: dict = {}  # 别名映射（同义词→标准术语名）

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if not self._terms:
            self._load()

    def _load(self):
        """从 JSON 文件加载术语库"""
        filepath = Path(TERMINOLOGY_FILE)
        if not filepath.exists():
            logger.warning(f"术语文件不存在: {filepath}")
            return

        with open(filepath, "r") as f:
            data = json.load(f)

        self._terms = data.get("terms", {})
        self._build_aliases()
        logger.info(f"📚 术语库加载完成: {len(self._terms)} 条")

    def _build_aliases(self):
        """构建别名索引（英文名→中文标准名）"""
        for name, info in self._terms.items():
            en = info.get("name_en", "")
            if en:
                self._aliases[en.lower()] = name
            # 常见英文缩写
            if name in ["HBM", "GPU", "ASIC", "NPU", "SoC", "MCU", "EDA", "TSV",
                         "GaN", "SiC", "IGBT", "MOSFET", "DRAM", "CIS", "CPO",
                         "ROE", "CAPEX", "EBITDA", "DDR5"]:
                self._aliases[name.lower()] = name

    # ── 查找 ────────────────────────────────────────

    def find_terms(self, query: str) -> list[dict]:
        """
        在用户查询中检测已知术语。

        Args:
            query: 用户问题文本

        Returns:
            匹配到的术语列表 [{name, name_en, definition, business_impact, ...}]
        """
        matched = []
        seen = set()

        # 1. 精确匹配术语名（中文）
        for name, info in self._terms.items():
            if name in query and name not in seen:
                seen.add(name)
                matched.append({"name": name, **info})

        # 2. 匹配英文名/缩写
        for alias, std_name in self._aliases.items():
            if alias.lower() in query.lower() and std_name not in seen:
                seen.add(std_name)
                if std_name in self._terms:
                    matched.append({"name": std_name, **self._terms[std_name]})

        # 3. 部分匹配（术语在查询中出现子串）
        for name, info in self._terms.items():
            if len(name) >= 3 and name in query and name not in seen:
                seen.add(name)
                matched.append({"name": name, **info})

        return matched

    # ── 构建上下文 ──────────────────────────────────

    def build_context(
        self, query: str, max_terms: int = 5, return_refs: bool = False
    ) -> Union[str, Tuple[str, List[Dict]]]:
        """
        为 RAG/LM Prompt 构建术语增强上下文。

        Args:
            query: 用户问题
            max_terms: 最多注入的术语数
            return_refs: 若 True，返回 (context_str, term_refs) 以支持引用溯源

        Returns:
            术语上下文文本（可直接拼接入 Prompt），或 (context_str, refs)
        """
        matches = self.find_terms(query)

        if not matches:
            return ("", []) if return_refs else ""

        # 去重并按术语名称长度降序（优先展示更具体的术语）
        unique = {}
        for m in matches:
            if m["name"] not in unique:
                unique[m["name"]] = m

        sorted_terms = sorted(unique.values(), key=lambda x: len(x["name"]), reverse=True)
        selected = sorted_terms[:max_terms]

        parts = ["## 半导体行业术语参考\n"]
        refs = []  # for citation tracking

        for t in selected:
            # Assign a citation key so the LLM can reference this term
            parts.append(f"### {t['name']} ({t.get('name_en', '')})")
            parts.append(f"- **定义**: {t.get('definition', 'N/A')}")
            parts.append(f"- **技术代际**: {t.get('generation', 'N/A')}")
            if t.get("business_impact"):
                parts.append(f"- **商业影响**: {t['business_impact']}")
            if t.get("related_terms"):
                parts.append(f"- **关联概念**: {', '.join(t['related_terms'][:8])}")
            parts.append("")

            if return_refs:
                refs.append({"name": t["name"], "name_en": t.get("name_en", "")})

        context = "\n".join(parts)

        if return_refs:
            return context, refs
        return context

    # ── 获取单个术语 ───────────────────────────────

    def get_term(self, name: str) -> Optional[dict]:
        """按名称获取单个术语"""
        return self._terms.get(name)

    def list_all(self) -> list[str]:
        """列出所有术语名"""
        return sorted(self._terms.keys())

    def stats(self) -> dict:
        """获取术语库统计信息"""
        return {
            "total_terms": len(self._terms),
            "aliases": len(self._aliases),
        }


# ── 便捷函数 ──────────────────────────────────────────

def get_terminology() -> TerminologyManager:
    return TerminologyManager()
