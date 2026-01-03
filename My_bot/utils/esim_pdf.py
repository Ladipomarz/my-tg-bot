import io
import datetime
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas


def build_esim_pdf_bytes(
    *,
    order_code: str,
    phone_number_masked: str,
    plan_name: str,
    plan_expires_str: str,
    email: str,
    activation_code: str,
    iccid: str,
    qr_link: str | None,
):
    """
    Returns BytesIO with a designed PDF.
    (Background colors are real since it's PDF.)
    """
    qr_link = (qr_link or "").strip()

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    W, H = letter

    # Background blocks (yellow top, teal bottom)
    c.setFillColorRGB(0.96, 0.73, 0.20)  # warm yellow
    c.rect(0, H * 0.50, W, H * 0.50, stroke=0, fill=1)

    c.setFillColorRGB(0.20, 0.73, 0.73)  # teal
    c.rect(0, 0, W, H * 0.50, stroke=0, fill=1)

    # Title
    c.setFillColorRGB(1, 1, 1)
    c.setFont("Helvetica-Bold", 22)
    c.drawCentredString(W / 2, H * 0.86, "Your Plan Information")

    # Plan info (top/yellow area)
    c.setFont("Helvetica", 14)
    y = H * 0.78
    line_gap = 26

    c.drawCentredString(W / 2, y, f"Phone Number: {phone_number_masked}")
    y -= line_gap
    c.drawCentredString(W / 2, y, f"Your Plan: {plan_name}")
    y -= line_gap
    c.drawCentredString(W / 2, y, "Auto Renew: Not Active")
    y -= line_gap

    # Highlight expires
    c.setFillColorRGB(0.11, 0.35, 0.75)  # blue highlight
    c.rect(W * 0.25, y - 8, W * 0.50, 26, stroke=0, fill=1)
    c.setFillColorRGB(1, 1, 1)
    c.setFont("Helvetica-Bold", 14)
    c.drawCentredString(W / 2, y, f"Plan Expires: {plan_expires_str}")

    # Bottom section header
    c.setFont("Helvetica-Bold", 20)
    c.drawCentredString(W / 2, H * 0.43, "Haven't scanned your QR Code?")

    c.setFont("Helvetica", 13)
    c.drawCentredString(W / 2, H * 0.39, "Let's do that now so you can start using your eSIM service.")

    # Steps
    c.setFont("Helvetica", 12)
    steps_y = H * 0.33
    c.drawCentredString(W / 2, steps_y, "1. Use the QR link below (if provided).")
    c.drawCentredString(W / 2, steps_y - 18, "2. Scan the QR code using the phone this service will be on.")
    c.drawCentredString(W / 2, steps_y - 36, "3. Follow the prompts to install and activate.")

    # QR Link box
    c.setFillColorRGB(1, 1, 1)
    c.setFont("Helvetica-Bold", 12)

    box_y = H * 0.18
    c.roundRect(W * 0.15, box_y, W * 0.70, 48, 10, stroke=1, fill=0)
    c.drawCentredString(W / 2, box_y + 30, "QR LINK")
    c.setFont("Helvetica", 10)
    c.drawCentredString(W / 2, box_y + 14, qr_link if qr_link else "N/A (QR may be sent as image in chat)")

    # Footer info (small)
    c.setFont("Helvetica", 10)
    c.drawString(36, 36, f"Order: {order_code}   •   Email: {email}")
    c.drawRightString(W - 36, 36, f"Generated: {datetime.datetime.utcnow().strftime('%m/%d/%Y')}")

    # Extra delivery details on next page
    c.showPage()
    c.setFont("Helvetica-Bold", 18)
    c.drawString(48, H - 72, "Delivery Details")

    c.setFont("Helvetica", 12)
    yy = H - 110
    c.drawString(48, yy, f"Order Code: {order_code}"); yy -= 20
    c.drawString(48, yy, f"Email: {email}"); yy -= 20
    c.drawString(48, yy, f"Activation Code: {activation_code}"); yy -= 20
    c.drawString(48, yy, f"ICCID: {iccid}"); yy -= 20
    c.drawString(48, yy, f"QR Link: {qr_link if qr_link else 'N/A'}"); yy -= 20

    c.save()
    buf.seek(0)
    return buf
