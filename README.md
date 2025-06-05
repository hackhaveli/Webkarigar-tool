# Website Scraper for Global and German Sites

This tool is designed to scrape information from a list of websites, including those in German, extracting key business details like email addresses, logos, services, and business names.

## Features

- **CSV Processing**: Reads a CSV file with website URLs and updates it with scraped data
- **Data Extraction**:
  - Email addresses (including from contact pages)
  - Company logos (with enhanced detection algorithms)
  - Business names (from multiple sources)
  - Services offered (with German keyword recognition)
- **German Site Support**: Optimized for handling German websites with proper encoding
- **Concurrent Processing**: Processes multiple websites simultaneously for efficiency
- **Modern UI**: Web interface with real-time progress monitoring
- **Download Results**: Export scraped data to CSV for further analysis
- **Error Handling**: Robust error handling for various website structures

## New Improvements

- **Enhanced Logo Detection**: More accurate logo detection using multiple methods and scoring
- **Better Email Finding**: Now checks contact pages and uses improved regex patterns
- **Improved Service Extraction**: Better detection of services with German-specific keywords
- **Reliable CSV Upload**: Now handles various CSV formats, including malformed files
- **Single URL Addition**: Add individual URLs directly from the web interface
- **Download Functionality**: Download the scraped results as a CSV file
- **Modern UI Enhancements**: Responsive design with tooltips and improved visual design
- **Error Resilience**: Retries on failed requests with intelligent backoff

## Requirements

- Python 3.7+
- Required Python packages (see `requirements.txt`):
  - requests
  - beautifulsoup4
  - pandas
  - flask
  - tqdm

## Installation

1. Clone this repository or download the files
2. Install the required packages:

```bash
pip install -r requirements.txt
```

## Usage

### Command-line Usage

To use the scraper directly from the command line:

```bash
python scraper.py
```

This will read `leads.csv` in the current directory and update it with scraped data.

### Web Interface

For a more user-friendly experience, use the web interface:

```bash
python app.py
```

Then open your browser and navigate to `http://localhost:5000`

### Using the Web Interface

1. **Upload CSV**: Upload a CSV file with a column named 'url' containing the website URLs
   - The system will automatically normalize URLs (adding https:// where needed)
   - You can also add individual URLs using the "Add Single URL" function

2. **Configure Scraping**: Adjust the number of concurrent workers using the slider
   - Lower values (1-5): More reliable, less server load, slower
   - Higher values (10-20): Faster, but may cause timeouts or server blocks

3. **Start Scraping**: Click the "Start Scraping" button to begin the process
   - The status panel will show real-time progress
   - Results will appear in the table as they are completed

4. **Download Results**: Use the "Download CSV" button to save the scraped data
   - You can also clear all scraped data while keeping URLs using the "Clear Scraped Data" button

## CSV Format

Your CSV file should have a column named `url` containing the website URLs. Example:

```
url
https://www.example.com
https://www.beispiel.de
```

After scraping, the CSV will be updated with additional columns:
- `business_name`: The identified name of the business
- `email`: Contact email addresses found
- `logo`: URL to the website's logo
- `services`: List of services offered
- `error`: Any errors encountered during scraping

## German Website Support

The scraper includes specific features for handling German websites:

- Proper encoding for German characters (umlauts)
- Recognition of German service keywords ("Leistung", "Angebot", "Dienstleistung")
- Handling of German website structures and layouts

## Customization

### Adjusting Concurrent Workers

The default number of concurrent workers is 5. You can adjust this based on your system capabilities:

```python
scraper = WebsiteScraper('leads.csv', max_workers=10)
```

### Timeout Settings

Adjust the timeout for each website request:

```python
scraper = WebsiteScraper('leads.csv', timeout=60)  # 60 seconds timeout
```

## Troubleshooting

- **Connection errors**: Check your internet connection and firewall settings
- **Scraping failures**: Some websites may block scraping attempts; the system now uses retries with backoff
- **Encoding issues**: The scraper now automatically handles encoding for special characters
- **CSV upload problems**: The improved system can handle various CSV formats and validates content

## License

This project is open-source and available under the MIT License. 