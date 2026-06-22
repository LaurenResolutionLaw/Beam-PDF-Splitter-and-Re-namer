# Resolution Law Tools

A Streamlit web app for Resolution Law office tools.

The toolbox includes:

- **Beam PDF Splitter**, which splits PDFs into two-page chunks and renames each output file from the beam number found in the footer of the second page.
- **Affidavit PDF Splitter**, which splits affidavit PDFs into two-page chunks, reads the `OFN:` number from the bottom of each second page, and saves each output as `<number>W.pdf` such as `12942W.pdf`.
- **File Combiner**, which sorts uploaded files by account number (from an `Acct#####` token in the file name or from an account-number folder such as `16638/Images/...`) and merges each account into one combined PDF named `<account>final.pdf` — complaint letter first, then supporting documents. Excel and image files are converted to PDF pages before merging.

The app is built as an expandable toolbox, so more tools can be added later.

## Files For Streamlit

- `app.py` - main Streamlit app
- `requirements.txt` - Python package dependencies
- `packages.txt` - system package dependency for Tesseract OCR

## Deploy On Streamlit Community Cloud

1. Push this repo to GitHub.
2. Go to Streamlit Community Cloud.
3. Create a new app from this repo.
4. Set the main file path to:

```text
app.py
```

## OCR

Native PDFs can usually be read directly. Scanned PDFs need OCR.

`packages.txt` installs:

```text
tesseract-ocr
```

`requirements.txt` installs:

```text
streamlit
PyMuPDF
Pillow
pytesseract
```
