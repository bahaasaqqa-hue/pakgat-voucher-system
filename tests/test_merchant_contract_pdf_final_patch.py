from __future__ import annotations

import zipfile
from pathlib import Path

from app import merchant_contract_pdf_final_patch as final_patch


def test_inject_page_break_markers_between_three_sections():
    html = '<section class="page">A</section>\n<section class="page">B</section>\n<section class="page">C</section>'
    marked = final_patch._inject_page_break_markers(html)
    assert marked.count('[[PAKGAT_PAGE_BREAK_2]]') == 1
    assert marked.count('[[PAKGAT_PAGE_BREAK_3]]') == 1


def test_patch_odt_replaces_markers_with_real_page_break_style(tmp_path: Path):
    source = tmp_path / 'source.odt'
    target = tmp_path / 'target.odt'
    content = '''<?xml version="1.0" encoding="UTF-8"?>
<office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0" xmlns:fo="urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0"><office:automatic-styles></office:automatic-styles><office:body><office:text><text:p>[[PAKGAT_PAGE_BREAK_2]]</text:p><text:p>[[PAKGAT_PAGE_BREAK_3]]</text:p></office:text></office:body></office:document-content>'''
    with zipfile.ZipFile(source, 'w') as z:
        z.writestr('mimetype', b'application/vnd.oasis.opendocument.text', compress_type=zipfile.ZIP_STORED)
        z.writestr('content.xml', content.encode('utf-8'))

    final_patch._patch_odt_page_breaks(source, target)

    with zipfile.ZipFile(target) as z:
        patched = z.read('content.xml').decode('utf-8')
    assert '[[PAKGAT_PAGE_BREAK_' not in patched
    assert 'fo:break-before="page"' in patched
    assert patched.count('text:style-name="PakgatPageBreak"') == 2
