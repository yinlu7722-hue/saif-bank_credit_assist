import re
import os

base_dir = r"C:\Users\Lawrence\Desktop\MBA\AI课\对公信贷流程智能化任务\testfile"

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, HRFlowable
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# Register Chinese fonts
font_paths = {
    'SimHei': r'C:\Windows\Fonts\simhei.ttf',
    'SimSun': r'C:\Windows\Fonts\simsun.ttc',
    'MicrosoftYaHei': r'C:\Windows\Fonts\msyh.ttc',
    'KaiTi': r'C:\Windows\Fonts\simkai.ttf',
}

for name, path in font_paths.items():
    try:
        pdfmetrics.registerFont(TTFont(name, path))
    except Exception as e:
        print(f"Font registration warning ({name}): {e}")

pdf_files = ["01_公司章程.md", "02_股权结构.md", "03_对赌协议.md", "04_资产负债表.md", "05_利润表.md", "06_现金流量表.md", "07_负债清单.md", "11_租赁合同.md"]

# Base font
FONT_NAME = 'SimHei'
FONT_NAME_B = 'SimHei'

# Create styles with Chinese font
styles = getSampleStyleSheet()
styles.add(ParagraphStyle(name='MyTitle', fontName=FONT_NAME, fontSize=18, spaceAfter=12, textColor=colors.HexColor('#333333'), leading=24))
styles.add(ParagraphStyle(name='MyH2', fontName=FONT_NAME, fontSize=14, spaceBefore=12, spaceAfter=6, textColor=colors.HexColor('#333333'), leading=20))
styles.add(ParagraphStyle(name='MyH3', fontName=FONT_NAME, fontSize=12, spaceBefore=10, spaceAfter=4, textColor=colors.HexColor('#555555'), leading=18))
styles.add(ParagraphStyle(name='MyH4', fontName=FONT_NAME, fontSize=10, spaceBefore=8, spaceAfter=3, textColor=colors.HexColor('#666666'), leading=15))
styles.add(ParagraphStyle(name='MyCode', fontName='Courier', fontSize=8, backgrounColor=colors.HexColor('#F5F5F5'), leftIndent=10, rightIndent=10, leading=12))
styles.add(ParagraphStyle(name='MyBullet', fontName=FONT_NAME, fontSize=10, leftIndent=20, leading=15))
styles.add(ParagraphStyle(name='MyNormal', fontName=FONT_NAME, fontSize=10, leading=15))

def parse_md_to_platypus(content):
    elements = []
    lines = content.strip().split('\n')
    i = 0

    while i < len(lines):
        line = lines[i].strip()

        if not line:
            i += 1
            continue

        if line.startswith('#'):
            level = len(line) - len(line.lstrip('#'))
            text = line.lstrip('#').strip()
            if level == 1:
                elements.append(Paragraph(text, styles['MyTitle']))
            elif level == 2:
                elements.append(Paragraph(text, styles['MyH2']))
            elif level == 3:
                elements.append(Paragraph(text, styles['MyH3']))
            else:
                elements.append(Paragraph(text, styles['MyH4']))
            elements.append(Spacer(1, 0.2*cm))
            i += 1

        elif line.startswith('---'):
            elements.append(HRFlowable(width="100%", thickness=1, color=colors.gray))
            elements.append(Spacer(1, 0.3*cm))
            i += 1

        elif line.startswith('|'):
            table_data = []
            while i < len(lines) and lines[i].strip().startswith('|'):
                row = lines[i].strip()
                if not re.match(r'^\|[\s\-:|]+\|$', row):
                    cells = [c.strip() for c in row.strip('|').split('|')]
                    table_data.append(cells)
                i += 1

            if len(table_data) > 1:
                col_count = len(table_data[0])
                page_width = A4[0] - 4*cm  # 2cm margin each side
                col_widths = [page_width / col_count] * col_count

                t = Table(table_data, colWidths=col_widths, repeatRows=1)
                t.setStyle(TableStyle([
                    ('FONTNAME', (0,0), (-1,-1), FONT_NAME),
                    ('FONTSIZE', (0,0), (-1,-1), 9),
                    ('GRID', (0,0), (-1,-1), 0.5, colors.gray),
                    ('TOPPADDING', (0,0), (-1,-1), 5),
                    ('BOTTOMPADDING', (0,0), (-1,-1), 5),
                    ('LEFTPADDING', (0,0), (-1,-1), 5),
                    ('RIGHTPADDING', (0,0), (-1,-1), 5),
                    ('FONTNAME', (0,0), (-1,0), FONT_NAME_B),
                    ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#E0E0E0')),
                    ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, colors.HexColor('#F5F5F5')]),
                    ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
                ]))
                elements.append(t)
                elements.append(Spacer(1, 0.3*cm))
            continue

        elif line.startswith('```'):
            code_lines = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith('```'):
                code_lines.append(lines[i])
                i += 1
            elements.append(Paragraph('\n'.join(code_lines), styles['MyCode']))
            elements.append(Spacer(1, 0.2*cm))
            i += 1

        elif line.startswith('- '):
            items = []
            while i < len(lines) and lines[i].strip().startswith('- '):
                items.append('<li>' + lines[i].strip()[2:] + '</li>')
                i += 1
            if items:
                elements.append(Paragraph('<ul>' + ''.join(items) + '</ul>', styles['MyBullet']))
                elements.append(Spacer(1, 0.2*cm))
            continue

        else:
            clean = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', line)
            clean = re.sub(r'\*(.+?)\*', r'<i>\1</i>', clean)
            elements.append(Paragraph(clean, styles['MyNormal']))
            elements.append(Spacer(1, 0.1*cm))
            i += 1

    return elements

for f in pdf_files:
    md_path = os.path.join(base_dir, f)
    pdf_path = md_path.replace('.md', '.pdf')

    try:
        with open(md_path, 'r', encoding='utf-8') as file:
            content = file.read()

        doc = SimpleDocTemplate(pdf_path, pagesize=A4, leftMargin=2*cm, rightMargin=2*cm, topMargin=2*cm, bottomMargin=2*cm)
        elements = parse_md_to_platypus(content)
        doc.build(elements)
        print(f"OK: {f} -> {os.path.basename(pdf_path)}")
    except Exception as e:
        print(f"ERROR: {f}: {e}")
        import traceback
        traceback.print_exc()

print("Done!")
