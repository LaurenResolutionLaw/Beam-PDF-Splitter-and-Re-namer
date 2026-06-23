# Resolution Law Tools

A Streamlit web app for Resolution Law office tools.

The toolbox includes:

- **Beam PDF Splitter**, which splits PDFs into two-page chunks and renames each output file from the beam number found in the footer of the second page.
- **Affidavit PDF Splitter**, which splits affidavit PDFs into two-page chunks, reads the `OFN:` number from the bottom of each second page, and saves each output as `<number>W.pdf` such as `12942W.pdf`.
- **File Combiner**, which sorts uploaded files by account number (from an `Acct#####` token in the file name or from an account-number folder such as `16638/Images/...`) and merges each account into one combined PDF named `<account>final.pdf` — complaint letter first, then supporting documents. Excel and image files are converted to PDF pages before merging.

- **Document Sorter**, which takes a folder of files and sorts each one into legal subfolders (Origination, Check, Correspondence, Title, Legal, Bankruptcy, Payment History, Bill of Sale, Redacted BOS, Exhibit, Answer - Admitted, Answer - Partial Admission, Answer - Denial, Cease and Desist Request, Validation Request, Dispute, Complaint, Charge-Off Statement, Terms and Conditions, Consumer Notice of Account Transfer, Power of Attorney, Statement or Statement History, Judgment Copy, Affidavit of Indebtedness, Recorded Lien, Repo Docs, or Other). It matches semantically on both the file name and the file's contents (native PDF text, OCR for scans/images, plus Word/Excel/text), so a document named something similar still lands in the right place. Every suggestion can be overridden in a review table before downloading a ZIP organized into subfolders (with a `_sorting_report.csv` audit log).

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
