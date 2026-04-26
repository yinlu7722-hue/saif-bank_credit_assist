import re
import os
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, HRFlowable

base_dir = r"C:\Users\Lawrence\Desktop\MBA\AI课\对公信贷流程智能化任务\testfile"

# Files to convert to PDF
pdf_files = ["01_公司章程.md", "02_股权结构.md", "03_对赌协议.md", "04_资产负债表.md", "05_利润表.md", "06_现金流量表.md", "07_负债清单.md", "11_租赁合同.md"]

# Files to convert to PNG
png_files = ["15_营业执照.md", "16_法人身份证.md"]

def parse_markdown_to_platypus(md_content, styles):
    """Convert markdown content to ReportLab Platypus elements"""
    elements = []
    lines = md_content.strip().split('\n')
    i = 0

    while i < len(lines):
        line = lines[i].strip()

        if not line:
            i += 1
            continue

        # Headers
        if line.startswith('####'):
            elements.append(Paragraph(line[4:].strip(), styles['MyH4']))
        elif line.startswith('###'):
            elements.append(Paragraph(line[3:].strip(), styles['MyH3']))
        elif line.startswith('##'):
            elements.append(Paragraph(line[2:].strip(), styles['MyH2']))
            elements.append(Spacer(1, 0.3*cm))
        elif line.startswith('#'):
            elements.append(Paragraph(line[1:].strip(), styles['MyTitle']))
            elements.append(Spacer(1, 0.2*cm))

        # Horizontal rule
        elif line.startswith('---'):
            elements.append(HRFlowable(width="100%", thickness=1, color=colors.gray))
            elements.append(Spacer(1, 0.3*cm))

        # Table
        elif line.startswith('|'):
            table_data = []

            while i < len(lines) and lines[i].strip().startswith('|'):
                row_text = lines[i].strip()
                if re.match(r'^\|[\s\-:|]+\|$', row_text):
                    i += 1
                    continue

                cells = [c.strip() for c in row_text.strip('|').split('|')]
                table_data.append(cells)
                i += 1

            if table_data and len(table_data) > 1:
                header_row = table_data[0]
                data_rows = table_data[1:]

                all_rows = [header_row] + data_rows
                col_count = len(header_row)
                col_width = (A4[0] - 4*cm) / col_count
                col_widths = [col_width] * col_count

                table = Table(all_rows, colWidths=col_widths, repeatRows=1)

                row_bg_colors = []
                for idx in range(len(all_rows)):
                    if idx == 0:
                        row_bg_colors.append(colors.HexColor('#E0E0E0'))
                    elif idx % 2 == 0:
                        row_bg_colors.append(colors.HexColor('#F5F5F5'))
                    else:
                        row_bg_colors.append(colors.white)

                table_style = TableStyle([
                    ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
                    ('FONTSIZE', (0, 0), (-1, -1), 9),
                    ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                    ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                    ('GRID', (0, 0), (-1, -1), 0.5, colors.gray),
                    ('ROWBACKGROUNDS', (0, 0), (-1, -1), row_bg_colors),
                    ('TOPPADDING', (0, 0), (-1, -1), 6),
                    ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
                    ('LEFTPADDING', (0, 0), (-1, -1), 8),
                    ('RIGHTPADDING', (0, 0), (-1, -1), 8),
                ])

                table_style.add('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold')

                table.setStyle(table_style)
                elements.append(table)
                elements.append(Spacer(1, 0.4*cm))

        # Code block
        elif line.startswith('```'):
            code_lines = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith('```'):
                code_lines.append(lines[i])
                i += 1
            code_text = '\n'.join(code_lines)
            elements.append(Paragraph(f'<pre>{code_text}</pre>', styles['MyCode']))
            elements.append(Spacer(1, 0.3*cm))
            i += 1

        # Bullet list
        elif line.startswith('- '):
            items = []
            while i < len(lines) and lines[i].strip().startswith('- '):
                text = lines[i].strip()[2:].strip()
                items.append(f'<li>{text}</li>')
                i += 1
            if items:
                elements.append(Paragraph(f'<ul>{"".join(items)}</ul>', styles['MyBullet']))
                elements.append(Spacer(1, 0.2*cm))

        # Regular paragraph
        else:
            clean_line = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', line)
            clean_line = re.sub(r'\*(.+?)\*', r'<i>\1</i>', clean_line)
            clean_line = re.sub(r'`(.+?)`', r'<tt>\1</tt>', clean_line)

            elements.append(Paragraph(clean_line, styles['Normal']))
            elements.append(Spacer(1, 0.15*cm))
            i += 1

    return elements

def convert_to_pdf(md_file):
    """Convert markdown file to PDF"""
    try:
        md_path = os.path.join(base_dir, md_file)
        pdf_file = md_file.replace('.md', '.pdf')
        pdf_path = os.path.join(base_dir, pdf_file)

        with open(md_path, 'r', encoding='utf-8') as f:
            md_content = f.read()

        doc = SimpleDocTemplate(
            pdf_path,
            pagesize=A4,
            leftMargin=2*cm,
            rightMargin=2*cm,
            topMargin=2*cm,
            bottomMargin=2*cm
        )

        styles = getSampleStyleSheet()

        styles.add(ParagraphStyle(
            name='MyTitle',
            parent=styles['Title'],
            fontSize=18,
            spaceAfter=12,
            textColor=colors.HexColor('#333333')
        ))
        styles.add(ParagraphStyle(
            name='MyH2',
            parent=styles['Heading2'],
            fontSize=14,
            spaceBefore=12,
            spaceAfter=6,
            textColor=colors.HexColor('#333333')
        ))
        styles.add(ParagraphStyle(
            name='MyH3',
            parent=styles['Heading3'],
            fontSize=12,
            spaceBefore=10,
            spaceAfter=4,
            textColor=colors.HexColor('#555555')
        ))
        styles.add(ParagraphStyle(
            name='MyH4',
            parent=styles['Heading4'],
            fontSize=10,
            spaceBefore=8,
            spaceAfter=3,
            textColor=colors.HexColor('#666666')
        ))
        styles.add(ParagraphStyle(
            name='MyCode',
            parent=styles['Normal'],
            fontSize=8,
            fontName='Courier',
            backgrounColor=colors.HexColor('#F5F5F5'),
            leftIndent=10,
            rightIndent=10,
            spaceBefore=6,
            spaceAfter=6
        ))
        styles.add(ParagraphStyle(
            name='MyBullet',
            parent=styles['Normal'],
            fontSize=10,
            leftIndent=20,
            bulletIndent=10
        ))

        elements = parse_markdown_to_platypus(md_content, styles)
        doc.build(elements)

        print(f"[OK] Created PDF: {pdf_file}")
        return True
    except Exception as e:
        print(f"[ERROR] Error converting {md_file}: {e}")
        import traceback
        traceback.print_exc()
        return False

def convert_to_image(md_file):
    """Convert markdown file to PNG image using PIL"""
    try:
        from PIL import Image, ImageDraw, ImageFont
        import textwrap

        md_path = os.path.join(base_dir, md_file)
        img_file = md_file.replace('.md', '.png')
        img_path = os.path.join(base_dir, img_file)

        with open(md_path, 'r', encoding='utf-8') as f:
            md_content = f.read()

        # Create a large white image
        img_width = 1200
        img_height = 1600
        img = Image.new('RGB', (img_width, img_height), 'white')
        draw = ImageDraw.Draw(img)

        # Try to use a font, fallback to default if not available
        try:
            font_title = ImageFont.truetype("msyh.ttc", 28)
            font_heading = ImageFont.truetype("msyh.ttc", 22)
            font_subheading = ImageFont.truetype("msyh.ttc", 18)
            font_normal = ImageFont.truetype("msyh.ttc", 14)
            font_small = ImageFont.truetype("msyh.ttc", 12)
            font_table = ImageFont.truetype("msyh.ttc", 11)
        except:
            font_title = ImageFont.load_default()
            font_heading = font_title
            font_subheading = font_title
            font_normal = font_title
            font_small = font_title
            font_table = font_title

        y_pos = 40
        left_margin = 40
        line_height = 24

        lines = md_content.strip().split('\n')

        for line in lines:
            line = line.strip()

            if not line:
                y_pos += line_height // 2
                continue

            if line.startswith('# ') and not line.startswith('##'):
                draw.text((left_margin, y_pos), line[2:], font=font_title, fill='black')
                y_pos += line_height * 2

            elif line.startswith('## ') and not line.startswith('###'):
                draw.text((left_margin, y_pos), line[3:], font=font_heading, fill='black')
                y_pos += line_height * 1.5

            elif line.startswith('### '):
                draw.text((left_margin, y_pos), line[4:], font=font_subheading, fill='black')
                y_pos += line_height * 1.3

            elif line.startswith('|'):
                cells = [c.strip() for c in line.strip('|').split('|')]
                x_pos = left_margin
                for cell in cells:
                    draw.text((x_pos, y_pos), cell[:20], font=font_table, fill='black')
                    x_pos += 150
                y_pos += line_height

            elif line.startswith('```'):
                pass

            elif line.startswith('- '):
                draw.text((left_margin + 20, y_pos), "- " + line[2:60], font=font_normal, fill='black')
                y_pos += line_height

            else:
                wrapped = textwrap.wrap(line, width=80)
                for wrapped_line in wrapped:
                    draw.text((left_margin, y_pos), wrapped_line[:100], font=font_normal, fill='black')
                    y_pos += line_height

            if y_pos > img_height - 100:
                break

        img.save(img_path, 'PNG')
        print(f"[OK] Created PNG: {img_file}")
        return True

    except ImportError:
        print(f"[ERROR] PIL not available for image conversion")
        return False
    except Exception as e:
        print(f"[ERROR] Error converting {md_file}: {e}")
        import traceback
        traceback.print_exc()
        return False

print("=" * 50)
print("Converting files...")
print("=" * 50)

# Convert PDFs
print("\n--- Converting to PDF ---")
for f in pdf_files:
    if os.path.exists(os.path.join(base_dir, f)):
        convert_to_pdf(f)
    else:
        print(f"[ERROR] File not found: {f}")

# Convert images
print("\n--- Converting to PNG ---")
for f in png_files:
    if os.path.exists(os.path.join(base_dir, f)):
        convert_to_image(f)
    else:
        print(f"[ERROR] File not found: {f}")

print("\n" + "=" * 50)
print("Conversion complete!")
print("=" * 50)
