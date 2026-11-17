# GST TAXORA (India)

An informational tool that finds GST rates and HSN/SAC codes from CBIC Central Tax (Rate) notifications.

## Run locally
    pip install -r requirements.txt
    streamlit run app.py

## Run the tests
    python -m pytest -q

## Data
`data/gst_seed.csv` holds the rate records. Each row shows its notification and its verification status.
Verify each row against the official CBIC notification before relying on any result.

## Disclaimer
This tool is for general information and educational purposes only. It is not legal or tax advice.
