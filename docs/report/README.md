# Report source

- `report.html` — report source (edit this, then rebuild)
- `architecture.dot` — diagram source (Graphviz); `architecture.png` / `.svg` are rendered from it
- `report.pdf` — accessible tagged PDF (PDF/UA-1): selectable text, semantic headings, alt text on the diagram

Rebuild:

```sh
dot -Tpng -Gdpi=150 architecture.dot -o architecture.png
python -c "from weasyprint import HTML; HTML('report.html', base_url='.').write_pdf('report.pdf', pdf_variant='pdf/ua-1')"
```
(`pip install weasyprint` is needed only for rebuilding the report.)
