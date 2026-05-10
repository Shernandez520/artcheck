#!/bin/bash
python /app/inject_ga.py
exec streamlit run app_with_embroidery.py \
     --server.port=${PORT:-8501} \
     --server.address=0.0.0.0 \
     --server.headless=true \
     --server.maxUploadSize=50 \
     --server.enableCORS=false \
     --server.enableXsrfProtection=false \
     --browser.gatherUsageStats=false
