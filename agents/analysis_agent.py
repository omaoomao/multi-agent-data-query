"""
数据分析子智能体

负责对查询结果进行深度分析，生成洞察和建议，并自动生成 ECharts 图表配置。
支持 skill 增强：smart-chart（智能图表选择）和 report-export（PDF 报告导出）。
"""

import json
import os
from typing import Dict, Any, Optional, List
from pathlib import Path

from langchain_core.language_models import BaseLLM

import sys
import logging
logger = logging.getLogger(__name__)
sys.path.append(str(Path(__file__).parent.parent))
from prompts import get_analysis_prompt, get_chart_config_prompt
from agents.skill_loader import SkillLoader


class DataAnalysisAgent:
    """数据分析子智能体，支持文字分析、ECharts 图表可视化和 PDF 报告导出"""

    def __init__(self, llm: BaseLLM):
        self.llm = llm

        # 加载 skills
        self.skill_loader = SkillLoader()
        self._smart_chart_skill = self.skill_loader.get_content("smart-chart")
        self._report_export_skill = self.skill_loader.get_content("report-export")
        loaded = [n for n in ("smart-chart", "report-export") if self.skill_loader.get_content(n)]
        if loaded:
            logger.info(f"[Skills] DataAnalysisAgent 已加载 skills: {loaded}")
    
    @staticmethod
    def _llm_to_str(result) -> str:
        """安全地从 LLM 返回值中提取文本，清理思考标签"""
        from agents._utils import llm_to_str
        return llm_to_str(result)
    
    def _parse_data(self, data_str: str) -> Optional[Any]:
        """解析数据字符串，兼容新旧 MCP 返回格式。"""
        try:
            parsed = json.loads(data_str)
            # 新格式: {"data": [...], "row_count": N} → 解包为列表
            if isinstance(parsed, dict) and "data" in parsed:
                return parsed["data"]
            # 旧格式: 直接是列表或带 error 的字典
            return parsed
        except Exception:
            return None
    
    def _prepare_data_summary(self, data: Any) -> str:
        """准备数据摘要"""
        if isinstance(data, list):
            
            # 如果数据是列表，统计记录数并展示前几条记录，同时分析数值字段的基本统计信息
            if len(data) == 0:
                return "数据为空"
            
            summary = f"数据总数: {len(data)}条记录\n"
            summary += "数据示例:\n"
            for i, item in enumerate(data[:3]):
                summary += f"  记录{i+1}: {json.dumps(item, ensure_ascii=False)}\n"
            
            if len(data) > 0 and isinstance(data[0], dict):
                numeric_fields = [k for k, v in data[0].items() if isinstance(v, (int, float))]
                
                if numeric_fields:
                    summary += "\n数值字段统计:\n"
                    for field in numeric_fields:
                        values = [item[field] for item in data if field in item and isinstance(item[field], (int, float))]
                        if values:
                            summary += f"  {field}: 最小={min(values)}, 最大={max(values)}, 平均={sum(values)/len(values):.2f}\n"
            
            return summary
        
        elif isinstance(data, dict):
            # 如果数据是单条记录，直接展示内容
            return f"单条记录: {json.dumps(data, ensure_ascii=False)}"
        
        return str(data)
    
    def _should_generate_chart(self, data: Any) -> bool:
        """判断是否适合生成图表
        
        图表生成条件：
        - 列表数据
        - 至少2条记录
        - 包含数值字段
        """
        if not isinstance(data, list) or len(data) < 2:
            return False
        if not isinstance(data[0], dict):
            return False
        has_numeric = any(isinstance(v, (int, float)) for v in data[0].values())
        return has_numeric
    
    def _generate_chart_config(self, data: Any, data_summary: str, context: str = "") -> Optional[Dict]:
        """生成 ECharts 图表配置

        让 LLM 根据数据特征自动选择图表类型（柱状图/折线图/饼图）
        并生成完整的 ECharts option 配置对象。如果 smart-chart skill
        已加载，会将图表选择决策树和模板注入 prompt 以提升图表质量。

        Args:
            data: 解析后的数据
            data_summary: 数据摘要
            context: 上下文信息

        Returns:
            ECharts option 配置字典，或 None（生成失败时）
        """
        try:
            raw_data_str = json.dumps(data[:20], ensure_ascii=False)  # 最多传入20条数据
            prompt = get_chart_config_prompt(
                data_summary=data_summary,
                raw_data=raw_data_str,
                context=context
            )

            # 注入 smart-chart skill：图表选择决策树 + 模板 + 配色
            if self._smart_chart_skill:
                prompt = (
                    f"{prompt}\n\n"
                    f"=== 图表生成指南（请严格遵循）===\n"
                    f"{self._smart_chart_skill}"
                )
            
            chart_json_str = self._llm_to_str(self.llm.invoke(prompt)).strip()
            
            # 清理可能的代码块标记
            if chart_json_str.startswith("```json"):
                chart_json_str = chart_json_str[7:]
            elif chart_json_str.startswith("```"):
                chart_json_str = chart_json_str[3:]
            if chart_json_str.endswith("```"):
                chart_json_str = chart_json_str[:-3]
            chart_json_str = chart_json_str.strip()
            
            chart_config = json.loads(chart_json_str)
            
            # 基本校验：必须是dict且包含series
            if isinstance(chart_config, dict) and "series" in chart_config:
                return chart_config
            return None
            
        except Exception as e:
            logger.warning(f"[图表生成] 图表配置生成失败（不影响分析结果）: {e}")
            return None
    
    def analyze(self, data: str, context: str = "") -> Dict[str, Any]:
        """分析数据，同时生成文字分析和 ECharts 图表配置
        
        Args:
            data: JSON格式的数据字符串
            context: 上下文信息（如原始问题）
            
        Returns:
            {
                "analysis": 文字分析内容,
                "chart": ECharts option配置字典（无法生成时为None）,
                "error": 错误信息（成功时为None）
            }
        """
        result = {
            "analysis": None,
            "chart": None,
            "error": None
        }
        
        try:
            parsed_data = self._parse_data(data)
            
            if parsed_data is None:
                result["error"] = "无法解析数据"
                return result
            
            if isinstance(parsed_data, dict) and "error" in parsed_data:
                result["error"] = f"数据包含错误: {parsed_data['error']}"
                return result
            
            data_summary = self._prepare_data_summary(parsed_data)
            
            # 文字分析
            prompt = get_analysis_prompt(
                data_summary=data_summary,
                raw_data=data,
                context=context
            )
            # 从 LLM 返回值中提取文本，清理思考标签，并存储分析结果
            analysis = self._llm_to_str(self.llm.invoke(prompt))
            result["analysis"] = analysis
            
            # ECharts 图表配置（仅对适合可视化的数据生成）
            if self._should_generate_chart(parsed_data):
                chart_config = self._generate_chart_config(parsed_data, data_summary, context)
                result["chart"] = chart_config

        except Exception as e:
            result["error"] = f"分析失败: {str(e)}"

        return result

    def export_report(
        self,
        title: str,
        analysis_text: str = "",
        table_headers: list = None,
        table_rows: list = None,
        findings: list = None,
        sql_query: str = "",
        output_dir: str = "reports"
    ) -> Dict[str, Any]:
        """将分析结果导出为 PDF 报告。

        依赖 report-export skill 中的模板。需要安装 fpdf2：
            pip install fpdf2

        Args:
            title: 报告标题
            analysis_text: 分析正文
            table_headers: 数据表头
            table_rows: 数据行
            findings: 关键发现列表
            sql_query: 使用的 SQL 查询
            output_dir: 报告输出目录

        Returns:
            {"path": 文件路径} 或 {"error": 错误信息}
        """
        if not self._report_export_skill:
            return {"error": "report-export skill 未加载，无法导出报告"}

        try:
            from fpdf import FPDF
        except ImportError:
            return {"error": "缺少 fpdf2 依赖，请执行: pip install fpdf2"}

        try:
            os.makedirs(output_dir, exist_ok=True)
            from datetime import datetime
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_title = title[:20].replace(" ", "_").replace("/", "_")
            output_path = os.path.join(output_dir, f"{safe_title}_{timestamp}.pdf")

            # 让 LLM 基于 report-export skill 生成报告内容的结构化摘要
            skill_guide = self._report_export_skill[:3000]  # 控制长度
            summarize_prompt = f"""请根据以下分析内容，生成一份结构化报告摘要（用于PDF导出）。

标题：{title}
分析内容：
{analysis_text[:3000]}

请返回 JSON 格式（不要代码块）：
{{"subtitle":"副标题","findings":["发现1","发现2","发现3"],"summary":"一段总结（100字内）"}}

只返回JSON，不要解释。"""

            raw = self.llm.invoke(summarize_prompt)
            meta_str = self._llm_to_str(raw).strip()
            # 清理可能的代码块
            if meta_str.startswith("```"):
                meta_str = meta_str.split("\n", 1)[1] if "\n" in meta_str else meta_str[3:]
            if meta_str.endswith("```"):
                meta_str = meta_str[:-3]
            meta_str = meta_str.strip()

            try:
                meta = json.loads(meta_str)
            except Exception:
                meta = {"subtitle": "", "findings": findings or [], "summary": ""}

            # 使用 fpdf2 生成 PDF
            pdf = self._create_pdf_report(
                title=title,
                subtitle=meta.get("subtitle", ""),
                findings=meta.get("findings", findings or []),
                analysis_text=analysis_text,
                table_headers=table_headers,
                table_rows=table_rows,
                sql_query=sql_query,
            )

            pdf.output(output_path)
            logger.info(f"[Report] PDF 已生成: {output_path}")
            return {"path": output_path}

        except Exception as e:
            error_msg = f"PDF 导出失败: {str(e)}"
            logger.error(f"[Report] {error_msg}")
            return {"error": error_msg}

    @staticmethod
    def _create_pdf_report(
        title: str,
        subtitle: str = "",
        findings: list = None,
        analysis_text: str = "",
        table_headers: list = None,
        table_rows: list = None,
        sql_query: str = "",
    ):
        """创建 PDF 报告对象（基于 fpdf2）"""
        from fpdf import FPDF
        from datetime import datetime

        pdf = FPDF()
        pdf.set_auto_page_break(auto=True, margin=20)

        # 尝试加载中文字体
        font_name = "Helvetica"
        font_dir = os.path.join(os.path.dirname(__file__), "..", "skills", "report-export", "fonts")
        noto_regular = os.path.join(font_dir, "NotoSansSC-Regular.ttf")
        noto_bold = os.path.join(font_dir, "NotoSansSC-Bold.ttf")
        if os.path.exists(noto_regular):
            pdf.add_font("NotoSansSC", "", noto_regular, uni=True)
            if os.path.exists(noto_bold):
                pdf.add_font("NotoSansSC", "B", noto_bold, uni=True)
            font_name = "NotoSansSC"

        # --- 封面 ---
        pdf.add_page()
        pdf.ln(50)
        pdf.set_font(font_name, "B", 24)
        pdf.multi_cell(0, 12, title, align="C")
        if subtitle:
            pdf.ln(8)
            pdf.set_font(font_name, "", 13)
            pdf.set_text_color(108, 117, 125)
            pdf.multi_cell(0, 8, subtitle, align="C")
        pdf.ln(20)
        pdf.set_font(font_name, "", 10)
        pdf.set_text_color(108, 117, 125)
        gen_time = datetime.now().strftime("%Y-%m-%d %H:%M")
        pdf.cell(0, 8, f"Generated: {gen_time}", align="C", new_x="LMARGIN", new_y="NEXT")
        pdf.cell(0, 8, "Source: University Enrollment & Employment Database", align="C")

        # --- 关键发现 ---
        if findings:
            pdf.add_page()
            pdf.set_text_color(33, 37, 41)
            pdf.set_font(font_name, "B", 16)
            pdf.cell(0, 10, "Key Findings", new_x="LMARGIN", new_y="NEXT")
            pdf.ln(4)
            pdf.set_font(font_name, "", 11)
            for i, f in enumerate(findings, 1):
                pdf.set_font(font_name, "B", 11)
                pdf.cell(8, 7, f"{i}.")
                pdf.set_font(font_name, "", 11)
                pdf.multi_cell(0, 7, str(f))
                pdf.ln(2)

        # --- 数据表格 ---
        if table_headers and table_rows:
            pdf.add_page()
            pdf.set_text_color(33, 37, 41)
            pdf.set_font(font_name, "B", 16)
            pdf.cell(0, 10, "Data", new_x="LMARGIN", new_y="NEXT")
            pdf.ln(4)

            col_w = (pdf.w - 20) / len(table_headers)
            # 表头
            pdf.set_font(font_name, "B", 8)
            pdf.set_fill_color(0, 123, 255)
            pdf.set_text_color(255, 255, 255)
            for h in table_headers:
                pdf.cell(col_w, 7, str(h), border=1, fill=True, align="C")
            pdf.ln()
            # 数据行
            pdf.set_font(font_name, "", 8)
            pdf.set_text_color(33, 37, 41)
            for row_idx, row in enumerate(table_rows[:30]):  # 最多30行
                if pdf.get_y() > 260:
                    pdf.add_page()
                if row_idx % 2 == 0:
                    pdf.set_fill_color(248, 249, 250)
                else:
                    pdf.set_fill_color(255, 255, 255)
                if isinstance(row, dict):
                    vals = [str(row.get(h, ""))[:12] for h in table_headers]
                else:
                    vals = [str(v)[:12] for v in row]
                for v in vals:
                    pdf.cell(col_w, 6, v, border=1, fill=True, align="C")
                pdf.ln()

        # --- 分析 ---
        if analysis_text:
            pdf.add_page()
            pdf.set_text_color(33, 37, 41)
            pdf.set_font(font_name, "B", 16)
            pdf.cell(0, 10, "Analysis", new_x="LMARGIN", new_y="NEXT")
            pdf.ln(4)
            pdf.set_font(font_name, "", 10)
            pdf.multi_cell(0, 6, analysis_text)

        # --- 附录 ---
        if sql_query:
            pdf.ln(10)
            pdf.set_font(font_name, "B", 12)
            pdf.cell(0, 8, "Appendix: SQL Query", new_x="LMARGIN", new_y="NEXT")
            pdf.set_font(font_name, "", 9)
            pdf.set_fill_color(245, 245, 245)
            pdf.multi_cell(0, 5, sql_query, fill=True)

        return pdf
