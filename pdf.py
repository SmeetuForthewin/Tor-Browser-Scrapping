#!/usr/bin/env python3

import psycopg2
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Image,
    PageBreak
)
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.enums import TA_LEFT, TA_JUSTIFY
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfgen import canvas
from datetime import datetime
from io import BytesIO
import os


# ───────── DATABASE CONFIG ─────────
DB_NAME = "tordb"
DB_USER = "postgres"
DB_PASS = "postgres"
DB_HOST = "localhost"
DB_PORT = "5432"

OUTPUT_FILE = "darkweb_report.pdf"


# ───────── CONNECT DB ─────────
conn = psycopg2.connect(
    dbname=DB_NAME,
    user=DB_USER,
    password=DB_PASS,
    host=DB_HOST,
    port=DB_PORT
)
cur = conn.cursor()


# ───────── FETCH ARTICLES ─────────
cur.execute("""
SELECT id, keyword, title, url, scraped_at
FROM darkweb_articles
ORDER BY scraped_at DESC;
""")

articles = cur.fetchall()

if not articles:
    print("No articles found.")
    exit()


# ───────── PDF SETUP ─────────
PAGE_W, PAGE_H = A4
ML = 18 * mm
MR = 18 * mm
MT = 20 * mm
MB = 20 * mm

doc = SimpleDocTemplate(
    OUTPUT_FILE,
    pagesize=A4,
    leftMargin=ML,
    rightMargin=MR,
    topMargin=MT,
    bottomMargin=MB
)

elements = []


# ───────── STYLES ─────────
styles = {}

styles["title"] = ParagraphStyle(
    "Title",
    fontName="Helvetica-Bold",
    fontSize=18,
    textColor=colors.HexColor("#1C4D8D"),
    spaceAfter=10,
)

styles["meta"] = ParagraphStyle(
    "Meta",
    fontName="Helvetica",
    fontSize=9,
    textColor=colors.grey,
    spaceAfter=12,
)

styles["heading"] = ParagraphStyle(
    "Heading",
    fontName="Helvetica-Bold",
    fontSize=13,
    textColor=colors.HexColor("#0f172a"),
    spaceBefore=8,
    spaceAfter=4,
)

styles["paragraph"] = ParagraphStyle(
    "Paragraph",
    fontName="Helvetica",
    fontSize=11,
    leading=16,
    alignment=TA_JUSTIFY,
    spaceAfter=6,
)


def safe(text):
    if not text:
        return ""
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


# ───────── BUILD DOCUMENT ─────────
for article in articles:

    article_id, keyword, title, url, scraped_at = article

    # Title
    elements.append(Paragraph(safe(title), styles["title"]))

    # Metadata
    elements.append(
        Paragraph(
            f"Keyword: {keyword} | "
            f"Scraped: {scraped_at.strftime('%Y-%m-%d %H:%M')}",
            styles["meta"]
        )
    )

    elements.append(Spacer(1, 10))

    # Fetch blocks
    cur.execute("""
    SELECT block_type, text_content, image_id
    FROM darkweb_blocks
    WHERE article_id = %s
    ORDER BY block_order;
    """, (article_id,))

    blocks = cur.fetchall()

    for block_type, text_content, image_id in blocks:

        if block_type == "heading":
            elements.append(
                Paragraph(safe(text_content), styles["heading"])
            )

        elif block_type == "text":
            elements.append(
                Paragraph(safe(text_content), styles["paragraph"])
            )

        elif block_type == "image" and image_id:

            cur.execute("""
            SELECT image_path
            FROM darkweb_images
            WHERE id = %s;
            """, (image_id,))

            img_row = cur.fetchone()

            if img_row:
                img_path = img_row[0]

                if os.path.exists(img_path):
                    try:
                        img = Image(img_path)
                        img.drawWidth = 150 * mm
                        img.drawHeight = img.drawHeight * (150 * mm / img.drawWidth)
                        elements.append(Spacer(1, 8))
                        elements.append(img)
                        elements.append(Spacer(1, 10))
                    except:
                        continue

    elements.append(PageBreak())


# ───────── BUILD PDF ─────────
doc.build(elements)

cur.close()
conn.close()

print(f"\n[+] PDF Generated: {OUTPUT_FILE}")