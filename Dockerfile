# Hosted demo: Streamlit + JDK. Java candidates run live; COBOL goldens are committed files.
FROM python:3.12-slim
RUN apt-get update \
 && apt-get install -y --no-install-recommends openjdk-21-jdk-headless \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY pyproject.toml ./
RUN pip install --no-cache-dir mcp==1.30.0 "streamlit>=1.40"
COPY core core
COPY adapters adapters
COPY tools tools
COPY mcp_server mcp_server
COPY app app
COPY docs docs
COPY profiles profiles
COPY legacy/LOANCALC.cbl legacy/LOANCALC.cbl
COPY data data
COPY modern modern
RUN rm -rf modern/*/build && useradd -m demo && chown -R demo /app
USER demo
ENV PORT=8501
EXPOSE 8501
CMD ["sh", "-c", "streamlit run app/streamlit_app.py --server.port=${PORT} --server.address=0.0.0.0 --server.headless=true --browser.gatherUsageStats=false"]
