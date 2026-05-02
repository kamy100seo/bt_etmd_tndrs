#!/usr/bin/env python3
import os
import re
import smtplib
import ssl
import asyncio
import json
import shutil
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
from email.mime.text import MIMEText
from datetime import datetime

from bs4 import BeautifulSoup
from playwright.async_api import async_playwright
from reportlab.lib.pagesizes import A4, landscape
from reportlab.platypus import (
    SimpleDocTemplate,
    Table,
    TableStyle,
    Paragraph,
    Image,
    Spacer,
)
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from dotenv import load_dotenv
from deep_translator import GoogleTranslator

# Load environment variables from .env if present
load_dotenv()

# Keywords for relevant services
RELEVANT_KEYWORDS = {
    'accommodation': ['accommodation', 'hotel', 'resort', 'lodging', 'housing', 'apartment', 'villa', 'guesthouse'],
    'catering': ['catering', 'food', 'restaurant', 'meal', 'dining', 'kitchen', 'cook', 'chef'],
    'construction': ['construction', 'building', 'contractor', 'renovation', 'repair', 'maintenance', 'infrastructure', 'civil', 'engineering'],
    'it_software': ['software', 'it', 'development', 'programming', 'ai', 'artificial intelligence', 'e-commerce', 'website', 'app', 'digital', 'tech'],
    'logistics': ['logistics', 'transportation', 'rental', 'machinery', 'heavy duty', 'equipment', 'vehicle', 'truck', 'crane'],
    'recruitment': ['recruitment', 'manpower', 'staff', 'personnel', 'hr', 'human resources', 'employment', 'hiring'],
    'travel_tourism': ['travel', 'tourism', 'hajj', 'umrah', 'pilgrimage', 'tour', 'agency', 'booking'],
    'textile': ['textile', 'fabric', 'manufacturing', 'garment', 'cloth', 'home textile', 'bedding', 'curtain']
}

# Configuration from environment
TARGET_URL = os.environ.get(
    "TARGET_URL",
    "https://tenders.etimad.sa/Tender/AllTendersForVisitor?PageNumber=1",
)
SMTP_HOST = os.environ.get("SMTP_HOST")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER")
SMTP_PASS = os.environ.get("SMTP_PASS")
EMAIL_FROM = os.environ.get("EMAIL_FROM", SMTP_USER)
EMAIL_TO = os.environ.get("EMAIL_TO")

REPORT_TITLE = os.environ.get("REPORT_TITLE", "Etimad Tenders – Daily Report")
MAX_ROWS = int(os.environ.get("MAX_ROWS", "50"))

COMPANY_NAME = os.environ.get("COMPANY_NAME", "")
LOGO_PATH = os.environ.get("LOGO_PATH")
FOOTER_TEXT = os.environ.get(
    "FOOTER_TEXT",
    "",
)


def clean_text(text):
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip()


def is_relevant_tender(row):
    """Check if a tender row is relevant based on keywords in title and activity."""
    title = row[0].lower() if row[0] else ""
    activity = row[4].lower() if len(row) > 4 and row[4] else ""
    text = title + " " + activity
    
    for category, keywords in RELEVANT_KEYWORDS.items():
        if any(keyword in text for keyword in keywords):
            return True
    return False


def get_text_by_label(card, label_patterns):
    element = card.find(
        string=lambda t: any(pattern in t for pattern in label_patterns)
        if t is not None else False
    )
    if element:
        for candidate in [element.find_next('span'), element.find_next('div'), element.find_next('p'), element.next_sibling, element.parent.next_sibling]:
            if candidate and getattr(candidate, 'text', '').strip():
                return clean_text(candidate.text)

        parent_text = clean_text(element.parent.get_text(separator=' ', strip=True))
        label_text = next((pattern for pattern in label_patterns if pattern in parent_text), '')
        return clean_text(parent_text.replace(label_text, ''))
    return ""


async def fetch_rows():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        await page.goto(TARGET_URL)
        await page.wait_for_load_state('networkidle')
        
        # Wait for the table to load
        await page.wait_for_selector('table', timeout=30000)
        
        # Extract table rows
        rows = []
        table_rows = await page.query_selector_all('table tbody tr')
        
        for tr in table_rows[:MAX_ROWS]:
            cells = await tr.query_selector_all('td')
            row_data = []
            for cell in cells:
                text = await cell.inner_text()
                row_data.append(clean_text(text))
            if row_data:
                rows.append(row_data)
        
        await browser.close()
        return rows


def translate_rows(rows):
    translator = GoogleTranslator(source='auto', target='en')
    translated_rows = []
    for row in rows:
        translated_row = []
        for cell in row:
            if cell:
                try:
                    translated_cell = translator.translate(cell)
                    translated_row.append(translated_cell)
                except:
                    translated_row.append(cell)
            else:
                translated_row.append(cell)
        translated_rows.append(translated_row)
    return translated_rows


def draw_page_header(canvas_obj, doc):
    """Draw the company logo and name in the page header."""
    width, height = doc.pagesize
    top_y = height - 16 * mm

    logo_width = 55 * mm
    logo_height = 24 * mm
    if LOGO_PATH and os.path.exists(LOGO_PATH):
        try:
            canvas_obj.drawImage(
                LOGO_PATH,
                doc.leftMargin,
                top_y - logo_height,
                width=logo_width,
                height=logo_height,
                preserveAspectRatio=True,
                mask='auto',
            )
        except Exception:
            pass

    if COMPANY_NAME:
        company_text = COMPANY_NAME.strip()
        url_match = re.search(r'(https?://[^\s,]+|www\.[^\s,]+)', company_text)
        if url_match:
            url_text = url_match.group(1)
            href = url_text if url_text.startswith('http') else f'https://{url_text}'
            company_text = company_text.replace(url_text, f'<a href="{href}">{url_text}</a>')

        company_style = ParagraphStyle(
            'company_header',
            parent=getSampleStyleSheet()["Normal"],
            fontName='Helvetica-Bold',
            fontSize=18,
            leading=20,
            textColor=colors.red,
            alignment=1,
        )

        company_para = Paragraph(company_text, company_style)
        company_width, company_height = company_para.wrap(doc.width, 30 * mm)
        company_para.drawOn(canvas_obj, doc.leftMargin, top_y - company_height + 2 * mm)

    # Add page number in header
    page_num = canvas_obj.getPageNumber()
    canvas_obj.setFont("Helvetica", 10)
    canvas_obj.setFillColor(colors.red)
    canvas_obj.drawRightString(width - doc.rightMargin, height - 12 * mm, f"Page {page_num}")
    canvas_obj.setFillColor(colors.black)  # Reset color


def add_footer(canvas_obj, doc):
    """Draw red separator line and footer text on each page."""
    width, _ = doc.pagesize
    line_y = 15 * mm

    if FOOTER_TEXT:
        canvas_obj.setStrokeColor(colors.red)
        canvas_obj.setLineWidth(0.5)
        canvas_obj.line(0, line_y, width, line_y)

        footer_style = getSampleStyleSheet()["Normal"].clone('footer')
        footer_style.alignment = 1
        footer_style.textColor = colors.red
        footer_style.fontName = "Helvetica"
        footer_style.fontSize = 9
        footer_style.leading = 11

        footer_para = Paragraph(FOOTER_TEXT, footer_style)
        footer_width, footer_height = footer_para.wrap(doc.width, 30 * mm)
        footer_para.drawOn(canvas_obj, doc.leftMargin, line_y - footer_height - 4 * mm)


def build_pdf(rows, path):
    styles = getSampleStyleSheet()
    story = []

    # Title and timestamp
    title_style = ParagraphStyle(
        'reportTitle',
        parent=styles['Title'],
        alignment=1,
        fontName='Helvetica-Bold',
        fontSize=9,
        leading=11,
        spaceAfter=4 * mm,
    )
    story.append(Paragraph(REPORT_TITLE, title_style))

    timestamp_style = ParagraphStyle(
        'reportTimestamp',
        parent=styles['Normal'],
        alignment=1,
        fontName='Helvetica',
        fontSize=10,
        leading=12,
        textColor=colors.grey,
        spaceAfter=4 * mm,
    )
    story.append(
        Paragraph(
            datetime.now().strftime('Generated on %Y-%m-%d %H:%M'),
            timestamp_style,
        )
    )

    # Table header row (English only)
    headers = [
        "#",
        "Tender title",
        "Procuring entity",
        "Sub-entity / Dept",
        "Type",
        "Activity",
        "Ref no.",
        "Publication",
        "Inquiry deadline",
        "Submission deadline",
        "Opening",
        "Doc price",
    ]

    cell_style = styles["BodyText"]
    cell_style.fontSize = 6
    cell_style.leading = 8
    cell_style.spaceBefore = 0
    cell_style.spaceAfter = 0

    header_style = ParagraphStyle(
        'tableHeader',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=8,
        leading=10,
        textColor=colors.white,
        alignment=1,
    )

    wrapped_headers = []
    for header in headers:
        if header in ('Inquiry deadline', 'Submission deadline'):
            wrapped_headers.append(Paragraph(header.replace(' ', '<br/>', 1), header_style))
        elif ' / ' in header:
            wrapped_headers.append(Paragraph(header.replace(' / ', '<br/>/ '), header_style))
        else:
            wrapped_headers.append(Paragraph(header, header_style))
    data = [wrapped_headers]
    for i, row in enumerate(rows, start=1):
        data.append([Paragraph(str(i), cell_style)] + [Paragraph(str(cell or ""), cell_style) for cell in row])

    col_widths = [8*mm, 75*mm, 33*mm, 26*mm, 20*mm, 18*mm, 25*mm, 18*mm, 18*mm, 18*mm, 18*mm, 12*mm]
    table = Table(data, colWidths=col_widths, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.red),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, 0), 8),
                ("FONTSIZE", (0, 1), (-1, -1), 7),
                ("ALIGN", (0, 0), (-1, 0), "CENTER"),
                ("ALIGN", (0, 1), (0, -1), "CENTER"),
                ("ALIGN", (1, 1), (4, -1), "LEFT"),
                ("ALIGN", (5, 1), (-1, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 2),
                ("RIGHTPADDING", (0, 0), (-1, -1), 2),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("GRID", (0, 0), (-1, 0), 0.5, colors.white),
                ("GRID", (0, 1), (-1, -1), 0.5, colors.red),
                ("BOX", (0, 0), (-1, -1), 0.5, colors.red),
                ("LINEABOVE", (0, 0), (-1, 0), 0.5, colors.white),
                ("LINEBELOW", (0, 0), (-1, 0), 0.5, colors.white),
            ]
        )
    )

    story.append(table)

    doc = SimpleDocTemplate(
        path,
        pagesize=landscape(A4),
        rightMargin=15,
        leftMargin=15,
        topMargin=28 * mm,
        bottomMargin=24 * mm,  # space for footer
    )

    doc.build(
        story,
        onFirstPage=lambda canvas_obj, doc: (draw_page_header(canvas_obj, doc), add_footer(canvas_obj, doc)),
        onLaterPages=lambda canvas_obj, doc: (draw_page_header(canvas_obj, doc), add_footer(canvas_obj, doc)),
    )


def send_email(pdf_path):
    if not all([SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS, EMAIL_TO]):
        raise RuntimeError("SMTP or email variables missing. Check .env")

    now = datetime.now().strftime("%Y-%m-%d")
    subject = f"{REPORT_TITLE} – {now}"
    body = "Attached is today's generated report in PDF format."

    msg = MIMEMultipart()
    msg["From"] = EMAIL_FROM
    msg["To"] = EMAIL_TO
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    with open(pdf_path, "rb") as f:
        part = MIMEApplication(f.read(), _subtype="pdf")
        part.add_header(
            "Content-Disposition",
            "attachment",
            filename=os.path.basename(pdf_path),
        )
        msg.attach(part)

    context = ssl.create_default_context()
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.starttls(context=context)
        server.login(SMTP_USER, SMTP_PASS)
        server.send_message(msg)


if __name__ == "__main__":
    # Sample data for preview
    sample_rows = [
        ['Sample Tender 1', 'Entity 1', 'Dept 1', 'Type 1', 'Activity 1', 'Ref 1', '2024-01-01', '2024-01-02', '2024-01-03', '2024-01-04', '100 SAR'],
        ['Sample Tender 2', 'Entity 2', 'Dept 2', 'Type 2', 'Activity 2', 'Ref 2', '2024-01-01', '2024-01-02', '2024-01-03', '2024-01-04', '200 SAR'],
    ]
    build_pdf(sample_rows, 'preview_report.pdf')
    print('Preview PDF generated: preview_report.pdf')