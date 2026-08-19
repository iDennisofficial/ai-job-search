# Docker image for the DeepSeek ai-job-search runner.
#
# Base image ships a full TeX Live distribution (lualatex + xelatex +
# fontspec + moderncv), which is everything the CV/cover-letter compile
# steps need. We layer Python, Bun, and poppler-utils on top.
FROM texlive/texlive:latest

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1

# Python + PDF inspection tools + curl/unzip for the Bun installer.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        python3 \
        python3-pip \
        python3-venv \
        ca-certificates \
        curl \
        unzip \
        poppler-utils \
    && rm -rf /var/lib/apt/lists/*

# Bun — needed to run the job-portal search CLIs. linkedin-search and
# freehire-search have zero runtime dependencies, so the `bun` binary alone
# is enough (no per-CLI `bun install` required).
RUN curl -fsSL https://bun.sh/install | bash
ENV PATH="/root/.bun/bin:${PATH}"

WORKDIR /app

# Python dependencies in an isolated venv (avoids pip's system-package
# restrictions across different base-image versions).
COPY requirements.txt ./
RUN python3 -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir -r requirements.txt
ENV PATH="/opt/venv/bin:${PATH}"

# Copy the project.
COPY . .

# The DeepSeek API key is supplied at runtime — never baked into the image.
ENV DEEPSEEK_API_KEY=""

ENTRYPOINT ["python", "deepseek_runner.py"]
CMD ["--help"]
