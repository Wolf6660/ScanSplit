import io
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject


def fixture_pdf():
    """A4 cover plus a rotated A3 scanner page; text is synthetic, never user data."""
    writer = PdfWriter()
    font = writer._add_object(DictionaryObject({NameObject('/Type'): NameObject('/Font'),
        NameObject('/Subtype'): NameObject('/Type1'), NameObject('/BaseFont'): NameObject('/Helvetica')}))
    for width, height, rotation in [(595.2756,841.8898,0),(841.8898,1190.5512,90)]:
        page = writer.add_blank_page(width, height)
        page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F1'):font})})
        content = DecodedStreamObject()
        content.set_data(b'BT /F1 28 Tf 65 400 Td (ScanSplit Dokument 12345) Tj 0 55 Td (Deutscher OCR Test) Tj ET')
        page[NameObject('/Contents')] = writer._add_object(content)
        if rotation:
            page.rotate(rotation)
    buffer = io.BytesIO(); writer.write(buffer)
    return buffer.getvalue()
