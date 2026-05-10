#!/bin/bash
python /app/inject_ga.py
exec streamlit run app_with_embroidery.py \
     --server.port=8501 \
     --server.address=0.0.0.0 \
     --server.headless=true \
     --server.maxUploadSize=50 \
     --server.enableCORS=false \
     --server.enableXsrfProtection=false \
     --server.enableWebsocketCompression=false \
     --server.fileWatcherType=none \
     --browser.gatherUsageStats=false \
     --browser.serverAddress=www.artcheck.app \
     --browser.serverPort=443
