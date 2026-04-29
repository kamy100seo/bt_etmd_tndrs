#!/usr/bin/env python3
import os
import re
import smtplib
import ssl
import asyncio
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

# Load .env from current directory
dotenv_path = os.path.join(os.path.dirname(__file__), '.env')
load_dotenv(dotenv_path)

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
MAX_ROWS = int(os.environ.get("MAX_ROWS", "6"))

COMPANY_NAME = os.environ.get("COMPANY_NAME", "")
LOGO_PATH = os.environ.get("LOGO_PATH")
FOOTER_TEXT = os.environ.get(
    "FOOTER_TEXT",
    "",
)

# Initialize translator
def clean_text(text):
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip()


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


def get_text_from_selectors(card, selectors):
    for selector in selectors:
        node = card.select_one(selector)
        if node and node.text.strip():
            return clean_text(node.text)
    return ""


def arabic_digits_to_ascii(text):
    if not text:
        return text
    trans = str.maketrans('٠١٢٣٤٥٦٧٨٩', '0123456789')
    return text.translate(trans)


def parse_date(value):
    if not value:
        return None
    text = arabic_digits_to_ascii(clean_text(value)).replace('/', '-').replace('.', '-').replace('\u200f', '').strip()
    patterns = [
        '%Y-%m-%d',
        '%d-%m-%Y',
        '%d %b %Y',
        '%d %B %Y',
        '%d %b, %Y',
        '%d %B, %Y',
        '%Y-%m-%d %H:%M',
        '%d-%m-%Y %H:%M',
    ]
    for pattern in patterns:
        try:
            return datetime.strptime(text, pattern)
        except Exception:
            continue
    return None


def sort_rows(rows):
    def sort_key(row):
        pub_date = parse_date(row[6])
        return pub_date or datetime.min

    return sorted(rows, key=sort_key, reverse=True)


def is_heading_row(values):
    normalized = [clean_text(str(v)).lower() for v in values if v]
    headings = {
        'tender title',
        'procuring entity',
        'sub-entity',
        'sub-entity / dept',
        'type',
        'activity',
        'ref no.',
        'publication',
        'inquiry deadline',
        'submission deadline',
        'opening',
        'doc price',
        'procuring agency',
    }
    return any(value in headings for value in normalized)


translator = GoogleTranslator(source='ar', target='en')


def translate_arabic_to_english(text):
    """Translate Arabic text to English using Google Translate."""
    if not text or not any('\u0600' <= char <= '\u06FF' for char in text):
        return text  # Return as-is if no Arabic characters
    
    try:
        translated = translator.translate(text)
        return translated
    except Exception as e:
        print(f"Translation error for '{text}': {e}")
        return text  # Return original text if translation fails


def translate_rows(rows):
    """Translate all Arabic text in the rows to English."""
    translated_rows = []
    for row in rows:
        translated_row = []
        for cell in row:
            translated_cell = translate_arabic_to_english(cell)
            translated_row.append(translated_cell)
        translated_rows.append(translated_row)
    return translated_rows


def fetch_rows():
    """Scrape Etimad tenders using Playwright (handles JavaScript rendering)."""
    if not TARGET_URL:
        raise RuntimeError("TARGET_URL is not set")

    # Run async function in sync context
    return asyncio.run(_fetch_rows_async())


async def _fetch_rows_async():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        # Use a real browser user agent to avoid bot detection
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = await context.new_page()
        
        try:
            await page.goto(TARGET_URL, wait_until='load', timeout=60000)
            
            # Wait for the tender cards to actually appear
            await page.wait_for_selector('.card', state='attached', timeout=20000)
            
            content = await page.content()
            soup = BeautifulSoup(content, 'html.parser')
            
            # Find real tender cards only
            cards = soup.select('.tender-card')[:MAX_ROWS]
            formatted_rows = []

            for card in cards:
                title = card.select_one('h3 a, h3, .tender-name, [id*="tenderName"], .card-title, .title, .tender-title')
                title_text = clean_text(title.text) if title else ''
                if not title_text:
                    continue

                # Entity and sub-entity come from the same paragraph block
                entity_text = ''
                sub_entity_text = ''
                paragraph = card.select_one('p.pb-2')
                if paragraph:
                    parts = [clean_text(s) for s in paragraph.strings if clean_text(s)]
                    if parts:
                        entity_text = parts[0]
                    if len(parts) > 1:
                        sub_entity_text = parts[1]

                tender_type = get_text_from_selectors(
                    card,
                    ['span.badge', '.badge', '.tender-type', '.category', '.tender-category'],
                ) or get_text_by_label(card, ['نوع المنافسة', 'نوع', 'Type'])

                activity_text = get_text_from_selectors(card, ['.text-chart-indicator'])
                if not activity_text:
                    activity_text = get_text_by_label(card, ['النشاط الأساسي', 'Activity'])

                ref_val = get_text_by_label(card, ['الرقم المرجعي', 'Reference', 'Ref no', 'Ref.'])
                pub_date = get_text_by_label(card, ['تاريخ النشر', 'Publication'])
                inquiry_deadline = get_text_by_label(card, ['آخر موعد لإستلام الإستفسارات', 'Inquiry deadline', 'Inquiry'])
                submit_date = get_text_by_label(card, ['آخر موعد لتقديم العروض', 'Submission deadline', 'Submission'])
                opening_date = get_text_by_label(card, ['تاريخ ووقت فتح العروض', 'موعد فتح العروض', 'Opening'])
                price = get_text_by_label(card, ['قيمة وثائق المنافسة', 'قيمة كراسة الشروط', 'Doc price', 'Price', 'Document price'])

                row = [
                    title_text,
                    entity_text or 'N/A',
                    sub_entity_text or '',
                    tender_type or 'General',
                    activity_text or 'General',
                    ref_val,
                    pub_date,
                    inquiry_deadline,
                    submit_date,
                    opening_date,
                    price,
                ]

                formatted_rows.append(row)

            formatted_rows = sort_rows(formatted_rows)
            return formatted_rows

        finally:
            await browser.close()



def draw_page_header(canvas_obj: canvas.Canvas, doc):
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
            textColor=colors.black,
            alignment=0,
        )

        company_para = Paragraph(company_text, company_style)
        company_width, company_height = company_para.wrap(doc.width - logo_width - 40 * mm, 30 * mm)
        company_para.drawOn(canvas_obj, doc.leftMargin + logo_width + 12 * mm, top_y - company_height + 2 * mm)


def add_footer(canvas_obj: canvas.Canvas, doc):
    """Draw red separator line and footer text on each page."""
    width, _ = doc.pagesize
    line_y = 15 * mm

    if FOOTER_TEXT:
        canvas_obj.setStrokeColor(colors.red)
        canvas_obj.setLineWidth(0.3)
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
                ("ALIGN", (0, 1), (-1, -1), "LEFT"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 3),
                ("RIGHTPADDING", (0, 0), (-1, -1), 3),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("GRID", (0, 0), (-1, -1), 0.3, colors.red),
                ("BOX", (0, 0), (-1, -1), 0.3, colors.red),
                ("LINEABOVE", (0, 0), (-1, 0), 0.3, colors.white),
                ("LINEBELOW", (0, 0), (-1, 0), 0.3, colors.white),
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
    body = "Attached is today’s generated report in PDF format."

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


def main():
    print("🔄 Starting Etimad tenders scraper...")
    rows = fetch_rows()
    if not rows:
        print("❌ No rows scraped; aborting.")
        return

    print(f"✅ Scraped {len(rows)} tenders")
    
    # Translate Arabic text to English
    print("🌐 Translating to English...")
    rows = translate_rows(rows)
    print("✅ Translation complete")
    
    today = datetime.now().strftime("%Y%m%d")
    pdf_name = f"bt_etmd_tndrs_{today}.pdf"
    print(f"📄 Building PDF: {pdf_name}")
    build_pdf(rows, pdf_name)
    
    print(f"✉️ Sending email with PDF...")
    send_email(pdf_name)
    print(f"✅ Done! Report sent to {EMAIL_TO}")


if __name__ == "__main__":
    main()
