---
name: report-export
description: 将数据分析结果导出为 PDF 报告。当用户要求"导出报告"、"生成PDF"、"下载报告"、"打印分析结果"时使用此 skill。
---

# 数据分析报告导出

将查询和分析结果导出为结构化的 PDF 报告。适用于招生就业数据分析场景。

## 依赖

```python
# 首选方案：fpdf2（轻量、中文支持好）
pip install fpdf2

# 备选方案：reportlab（功能更强但更复杂）
pip install reportlab
```

## 报告结构模板

每份报告应包含以下部分：

```
1. 封面    - 报告标题、生成时间、数据来源说明
2. 摘要    - 核心发现（3-5条关键结论）
3. 数据表格 - 原始查询结果的格式化表格
4. 图表    - 如果分析中包含 ECharts 图表，导出为图片嵌入
5. 分析    - 详细分析文字
6. 附录    - SQL 查询语句、数据说明
```

## 代码模板：fpdf2 生成 PDF

```python
import os
import json
from datetime import datetime
from fpdf import FPDF


class AnalysisReport(FPDF):
    """招生就业数据分析报告生成器"""

    def __init__(self):
        super().__init__()
        # 注册中文字体（必须在 add_page 之前）
        font_dir = os.path.join(os.path.dirname(__file__), "fonts")
        noto_path = os.path.join(font_dir, "NotoSansSC-Regular.ttf")
        noto_bold_path = os.path.join(font_dir, "NotoSansSC-Bold.ttf")

        if os.path.exists(noto_path):
            self.add_font("NotoSansSC", "", noto_path, uni=True)
            if os.path.exists(noto_bold_path):
                self.add_font("NotoSansSC", "B", noto_bold_path, uni=True)
            self._font_name = "NotoSansSC"
        else:
            # 回退：尝试系统字体
            self._font_name = "Helvetica"

    def header(self):
        self.set_font(self._font_name, "B", 10)
        self.set_text_color(100, 100, 100)
        self.cell(0, 8, "高校招生与就业数据分析报告", align="R", new_x="LMARGIN", new_y="NEXT")
        self.line(10, self.get_y(), 200, self.get_y())
        self.ln(4)

    def footer(self):
        self.set_y(-15)
        self.set_font(self._font_name, "", 8)
        self.set_text_color(128, 128, 128)
        self.cell(0, 10, f"第 {self.page_no()}/{{nb}} 页", align="C")

    def add_cover(self, title: str, subtitle: str = ""):
        """添加封面"""
        self.add_page()
        self.ln(60)
        self.set_font(self._font_name, "B", 28)
        self.set_text_color(33, 37, 41)
        self.multi_cell(0, 15, title, align="C")
        self.ln(10)
        if subtitle:
            self.set_font(self._font_name, "", 14)
            self.set_text_color(108, 117, 125)
            self.multi_cell(0, 10, subtitle, align="C")
        self.ln(30)
        self.set_font(self._font_name, "", 11)
        self.set_text_color(108, 117, 125)
        gen_time = datetime.now().strftime("%Y年%m月%d日 %H:%M")
        self.cell(0, 8, f"生成时间：{gen_time}", align="C", new_x="LMARGIN", new_y="NEXT")
        self.cell(0, 8, "数据来源：高校招生与就业数据库", align="C", new_x="LMARGIN", new_y="NEXT")

    def add_section_title(self, title: str):
        """添加章节标题"""
        self.ln(8)
        self.set_font(self._font_name, "B", 16)
        self.set_text_color(33, 37, 41)
        self.cell(0, 10, title, new_x="LMARGIN", new_y="NEXT")
        self.set_draw_color(0, 123, 255)
        self.set_line_width(0.8)
        self.line(10, self.get_y(), 80, self.get_y())
        self.ln(6)

    def add_body_text(self, text: str):
        """添加正文"""
        self.set_font(self._font_name, "", 11)
        self.set_text_color(33, 37, 41)
        self.multi_cell(0, 7, text)
        self.ln(3)

    def add_data_table(self, headers: list, rows: list, col_widths: list = None):
        """添加数据表格

        Args:
            headers: 表头列表
            rows: 数据行列表（每行是列表或字典）
            col_widths: 列宽列表（None 则自动均分）
        """
        if not rows:
            self.add_body_text("（无数据）")
            return

        # 自动计算列宽
        if col_widths is None:
            available = self.w - 20  # 左右各留 10mm
            col_widths = [available / len(headers)] * len(headers)

        # 表头
        self.set_font(self._font_name, "B", 9)
        self.set_fill_color(0, 123, 255)
        self.set_text_color(255, 255, 255)
        for i, header in enumerate(headers):
            self.cell(col_widths[i], 8, str(header), border=1, fill=True, align="C")
        self.ln()

        # 数据行
        self.set_font(self._font_name, "", 9)
        self.set_text_color(33, 37, 41)
        for row_idx, row in enumerate(rows):
            if self.get_y() > 260:  # 页尾空间不足时换页
                self.add_page()
            # 斑马纹
            if row_idx % 2 == 0:
                self.set_fill_color(248, 249, 250)
            else:
                self.set_fill_color(255, 255, 255)

            if isinstance(row, dict):
                values = [str(row.get(h, "")) for h in headers]
            else:
                values = [str(v) for v in row]

            for i, val in enumerate(values):
                # 截断过长文本
                display = val[:15] + "..." if len(val) > 15 else val
                self.cell(col_widths[i], 7, display, border=1, fill=True, align="C")
            self.ln()
        self.ln(4)

    def add_chart_image(self, image_path: str, w: int = 160):
        """嵌入图表图片"""
        if os.path.exists(image_path):
            x = (self.w - w) / 2  # 居中
            self.image(image_path, x=x, w=w)
            self.ln(6)
        else:
            self.add_body_text("（图表生成失败）")

    def add_key_findings(self, findings: list):
        """添加关键发现列表"""
        self.set_font(self._font_name, "", 11)
        self.set_text_color(33, 37, 41)
        for i, finding in enumerate(findings, 1):
            self.set_font(self._font_name, "B", 11)
            self.cell(8, 7, f"{i}.")
            self.set_font(self._font_name, "", 11)
            self.multi_cell(0, 7, finding)
            self.ln(2)


def generate_report(
    title: str,
    subtitle: str = "",
    findings: list = None,
    analysis_text: str = "",
    table_headers: list = None,
    table_rows: list = None,
    chart_image_path: str = "",
    sql_query: str = "",
    output_path: str = "report.pdf"
) -> str:
    """一键生成分析报告

    Args:
        title: 报告标题
        subtitle: 副标题
        findings: 关键发现列表
        analysis_text: 分析正文
        table_headers: 表格表头
        table_rows: 表格数据
        chart_image_path: 图表图片路径
        sql_query: 使用的 SQL 查询
        output_path: 输出 PDF 路径

    Returns:
        生成的 PDF 文件路径
    """
    pdf = AnalysisReport()

    # 封面
    pdf.add_cover(title, subtitle)

    # 关键发现
    if findings:
        pdf.add_section_title("核心发现")
        pdf.add_key_findings(findings)

    # 数据表格
    if table_headers and table_rows:
        pdf.add_section_title("数据详情")
        pdf.add_data_table(table_headers, table_rows)

    # 图表
    if chart_image_path and os.path.exists(chart_image_path):
        pdf.add_section_title("数据可视化")
        pdf.add_chart_image(chart_image_path)

    # 分析
    if analysis_text:
        pdf.add_section_title("详细分析")
        pdf.add_body_text(analysis_text)

    # 附录
    if sql_query:
        pdf.add_section_title("附录：数据查询")
        pdf.set_font(pdf._font_name, "", 9)
        pdf.set_fill_color(245, 245, 245)
        pdf.multi_cell(0, 6, f"SQL: {sql_query}", fill=True)

    pdf.output(output_path)
    return output_path
```

## 使用方式

当用户要求导出报告时，按以下步骤操作：

1. **收集数据**：从最近的查询结果中提取 headers 和 rows
2. **提取关键发现**：从分析结果中提取 3-5 条核心结论
3. **生成图表图片**：如果有 ECharts 配置，用 pyecharts 渲染为 PNG
4. **调用 generate_report()** 生成 PDF
5. **告知用户文件路径**

## 注意事项

- 中文字体需要 NotoSansSC 字体文件，放在 `skills/report-export/fonts/` 目录下
- 如果没有字体文件，回退到 Helvetica（中文会显示为方块）
- 表格数据超过 20 行时建议分页或只展示前 20 行
- 图片建议宽度 160mm，居中显示
