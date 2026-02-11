# Delivery note → Invoice workflow automation

A script that reads a delivery note PDF as an image, performs OCR + structuring using Google Vision API + Gemini API, and automatically generates an invoice PDF.

## Quick Start

### Start with minimal setup

```bash
# 0. Install system package (for PDF processing)
# Ubuntu/Debian:
sudo apt-get install poppler-utils
# macOS:
# brew install poppler

# 1. Install dependent packages
pip install -r requirements.txt

# 2. Environment variable settings
cp .env.example .env
# Edit .env file to set API key and spreadsheet ID

# 3. Google authentication settings
# Place credentials.json in the project root
# (see the Setup section for details)

# 4. Process invoices with CLI tools
python -m src.main input/your_pdf.pdf
````

### Launch web application (optional)

```bash
# Start backend API
cd backend-api
python main.py
or
uvicorn backend-api.main:app --reload --port 8000
# → API starts at http://localhost:8000

# Start front end (separate terminal)
cd frontend-react
npm install
npm run dev
# → Start the front end at http://localhost:5173
````

See the Setup section below for detailed setup instructions.

## Processing flow

````
[Delivery note PDF] → [Image conversion] → [Google Vision API] → [OCR result]
                                    ↓
[Gemini API] → [Structured data]
                                    ↓
[Company master] ←──────────────────── [Company information acquisition]
                                    ↓
[Delivery note DB] ←──────────────────────── [Save]
                                    ↓
[Invoice PDF] ←────────────────────── [PDF generation]
                                    ↓
[Billing Management Sheet] ←────────────────── [Save]
````

## Features

1. **Image-based OCR**: Treat PDF as an image and perform character recognition with Google Vision API
2. **Structuring by LLM**: Gemini API decomposes and structures each item from the extracted string (also extracts the deposit amount)
3. **Obtain company information**: Obtain postal code, address, and business division from Google Sheets company master
4. **Save delivery note DB**: Save the contents of the delivery note to Google Sheets (including the deposit amount)
5. **Invoice PDF generation**: Automatically generate invoice PDF in Japanese format
6. **Billing management record**: Recorded in sales summary sheet
7. **Billing history management**: Manage monthly billing history (optional)

## Setup

### 1. Installing dependent packages

```bash
pip install -r requirements.txt
````

### 2. System dependent package (for pdf2image)

```bash
# Ubuntu/Debian
sudo apt-get install poppler-utils

# macOS
brew install poppler

# Arch Linux
sudo pacman -S poppler
````

### 3. Japanese font
The project includes the IPAex Gothic font (`fonts/ipaexg.ttf`), so no additional installation is required.

If you want to use a custom font, set `PDF_FONT_PATH` in `.env`.

### 4. Get Google Gemini API key

1. Generate an API key with [Google AI Studio](https://aistudio.google.com/app/apikey)
2. Set in `.env` file

### 5. Google Cloud settings

**Important**: If your organization policy blocks service account key creation, use **OAuth 2.0 authentication**. See `OAUTH_SETUP.md` for details.

#### Option A: OAuth 2.0 authentication (recommended)

1. Create a project with [Google Cloud Console](https://console.cloud.google.com/)
2. Enable Google Sheets API
3. Create an OAuth client ID (desktop app)
4. Place the downloaded JSON as `credentials.json` in the project root
5. Set `USE_OAUTH=true` in `.env`
6. Give your Google account editing permissions to the spreadsheet you use.

Details: see `OAUTH_SETUP.md`

#### Option B: Service account authentication

1. Create a project with [Google Cloud Console](https://console.cloud.google.com/)
2. Enable Google Sheets API
3. Create a service account and download the JSON key
4. Place the downloaded JSON as `credentials.json` in the project root
5. Set `USE_OAUTH=false` in `.env` (or omit the option)
6. Add the service account email address to the spreadsheet you use in the sharing settings

### 6. Setting environment variables
```bash
cp .env.example .env
````

Edit `.env`:

```env
# Gemini API (required)
GEMINI_API_KEY=your_gemini_api_key

# Google Sheets ID (XXXX part of /d/XXXXX/edit in the URL)
COMPANY_MASTER_SPREADSHEET_ID=your_spreadsheet_id
DELIVERY_DB_SPREADSHEET_ID=your_spreadsheet_id
BILLING_SPREADSHEET_ID=your_spreadsheet_id

# Company information
OWN_REGISTRATION_NUMBER=T1234567890123
OWN_COMPANY_NAME=Sample Co., Ltd.
...
````

### 7. Preparing the spreadsheet

#### Company Master (COMPANY_MASTER)
URL: https://docs.google.com/spreadsheets/d/1l3GPdd2BoyPC_PIe5yktocAHJ30C1f2YpfCSOw6Tj9U/edit

| Company name | Division | Postal code | Address | Building name |
|---------|---------|---------|------|---------|
| ABC Co., Ltd. | Sales Department | 100-0001 | Tokyo... | ABC Building 3F |

#### Delivery note DB (DELIVERY_DB)

| Date | Company name | Slip number | Product code | Product name | Quantity | Unit price | Amount | Subtotal | Consumption tax | Total | Deposit amount |
|------|---------|------------|------------|------|------|------|------|------|---------|------|---------|

#### Sales summary table (BILLING)
URL: https://docs.google.com/spreadsheets/d/1eBmP3GWRNE2QZ6I8e1n2tjR7J_pHsB9L/edit

| Counterparty | Last month's balance | Accrued last month | Consumption tax last month | Disappeared last month | Balance | Accrued | Consumption tax | Disappeared | Balance | Second half total |
|---------|---------|---------|------------|------------|---------|------|------|---------|------|------|---------|

#### Billing History Management (BILLING_HISTORY) -Options

| Year and month | Company name | Last billed amount | Paid amount | Balance carried forward | Sales amount | Consumption tax amount | Current billed amount | Update date and time |
|------|---------|-------------|----------|----------|---------|----------|-------------|----------|

## How to use

```bash
# Process all PDFs in the input directory
python -m src.main

# Process specific PDF
python -m src.main input/delivery_note.pdf

# Process multiple PDFs
python -m src.main input/note1.pdf input/note2.pdf

# DRY RUN (skip writing to Google Sheets, only generate PDF)
python -m src.main --dry-run
````

## Directory structure

````
advan-workflow/
├── credentials.json # Google API authentication file (need to be created)
├── .env # Environment variable (need to be created)
├── .env.example # Environment variable sample
├── requirements.txt # Dependency package
├── input/# Delivery note PDF location directory
├── output/# Output destination of generated invoice PDF
├── src/
│ ├── __init__.py
│ ├── config.py # configuration
│ ├── pdf_extractor.py # Data structure definition
│ ├── llm_extractor.py # LLM extraction module (Google Vision + Gemini API)
│ ├── sheets_client.py # Google Sheets cooperation
│ ├── invoice_generator.py # Generate invoice PDF
│ └── main.py # Main script
└── README.md
````

## How LLM extraction works

### 1. PDF → Image conversion

```python
from pdf2image import convert_from_path
images = convert_from_path(pdf_path, dpi=150)
````
### 2. OCR with Google Vision API

```python
vision_image = vision.Image(content=content)
response = vision_client.document_text_detection(image=vision_image)
text = response.full_text_annotation.text
````

### 3. Structured with Gemini API

```python
response = gemini_client.models.generate_content(
    model="gemini-2.5-flash",
    contents=f"{EXTRACTION_PROMPT}\n\n{text}"
)
````

### 4. Prompt for structuring

Have Gemini API extract the following items in JSON format:
-date: date
-company_name: Company name
-slip_number: slip number
-subtotal: subtotal
-tax: consumption tax
-total: total
-payment_received: Payment amount (additional)
-items: detail line (product code, product name, quantity, unit price, amount)

### 5. Parse JSON and convert it to data structure

```python
extracted = json.loads(response_text)
delivery_note = DeliveryNote(
    date=extracted["date"],
    company_name=extracted["company_name"],
    ...
)
````

## Notes

-Fees apply for using Google Vision API and Gemini API
-Image resolution set to 150dpi (for API cost optimization)
-Multi-page PDFs process each page individually and combine details
-Japanese font (IPAex Gothic) is included in the project

## Cost estimate

-Google Vision API: Document Text Detection $1.50/1,000 units (first 1,000 units/month free)
-Gemini 2.5 Flash: Free tier available (free within limits)
-1 PDF delivery note: Approximately $0.002~0.01 (based on Vision API)