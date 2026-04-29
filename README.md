# Etimad Tenders Daily Report Generator

This Python script scrapes daily tenders from the Etimad platform, generates a PDF report, and sends it via email.

## Features

- Scrapes tender data from Etimad website using Playwright
- Translates Arabic text to English
- Generates professional PDF reports with company branding
- Sends automated email notifications
- Scheduled daily execution via cron

## Prerequisites

- Python 3.10+
- Virtual environment (recommended)
- GitHub repository for CI/CD

## Installation

1. Clone the repository:
   ```bash
   git clone https://github.com/kamy100seo/bt_etmd_tndrs.git
   cd bt_etmd_tndrs
   ```

2. Create and activate virtual environment:
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   ```

3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   playwright install
   ```

4. Create `.env` file with your configuration:
   ```env
   TARGET_URL=https://etimad.sa/Tenders/Index
   SMTP_HOST=your-smtp-host
   SMTP_PORT=587
   SMTP_USER=your-email@example.com
   SMTP_PASS=your-password
   EMAIL_FROM=your-email@example.com
   EMAIL_TO=recipient@example.com
   REPORT_TITLE=Etimad Tenders - Daily Report
   COMPANY_NAME=Insight International Contracting Company (IICC)
   WEBSITE_LINK=www.iicc.sa
   LOGO_PATH=images/iicc_final_logo.jpeg
   ```

## Usage

### Manual Execution
```bash
python bt-etmd-tndrs.py
```

### Scheduled Execution
Use the provided shell script with cron:

```bash
# Edit crontab
crontab -e

# Add this line for daily execution at 10:30 AM
30 10 * * * /path/to/bt_etmd_tndrs/run_etimad_report.sh
```

## Project Structure

```
bt-etmd-tndrs/
├── bt-etmd-tndrs.py          # Main script
├── run_etimad_report.sh      # Cron execution script
├── requirements.txt           # Python dependencies
├── .env                       # Environment variables (not in repo)
├── .gitignore                 # Git ignore rules
├── images/
│   └── iicc_final_logo.jpeg   # Company logo
└── .github/
    └── workflows/
        └── ci.yml             # GitHub Actions CI/CD
```

## CI/CD

The project includes GitHub Actions workflow for:
- Code linting with flake8
- Python compilation checks
- Basic functionality tests
- Automated builds

## Dependencies

- `playwright`: Web scraping
- `beautifulsoup4`: HTML parsing
- `reportlab`: PDF generation
- `python-dotenv`: Environment management
- `deep-translator`: Arabic to English translation

## License

This project is proprietary. All rights reserved.