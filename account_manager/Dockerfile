FROM apify/actor-python:3.13

# Second, copy just requirements.txt into the Actor image,
# since it should be the only file that affects the dependency install in the next step,
# in order to speed up the build
ENV PYTHONUNBUFFERED=1
ENV DISPLAY=:99

WORKDIR /app

COPY . .

# Install Chrome, Xvfb, and required dependencies for virtual display
RUN apt-get update && apt-get install -y \
build-essential \
ca-certificates \
curl \
wget \
gnupg \
xvfb \
python3-tk \
python3-dev \
libx11-dev \
xauth \
x11-utils \
xfonts-base \
xfonts-75dpi \
xfonts-100dpi \
fonts-liberation \
libxkbcommon-x11-0 \
libxcb-xinerama0 \
libxcb-cursor0 \
&& ARCH="$(dpkg --print-architecture)" \
&& if [ "$ARCH" = "amd64" ]; then \
        wget -q -O- https://dl.google.com/linux/linux_signing_key.pub | gpg --dearmor -o /usr/share/keyrings/google-chrome-keyring.gpg; \
        echo "deb [arch=amd64 signed-by=/usr/share/keyrings/google-chrome-keyring.gpg] https://dl.google.com/linux/chrome/deb/ stable main" > /etc/apt/sources.list.d/google-chrome.list; \
        apt-get update && apt-get install -y google-chrome-stable; \
    else \
        apt-get install -y chromium chromium-driver; \
    fi \
&& rm -rf /var/lib/apt/lists/*

# Fix permissions for the SeleniumBase drivers directory
RUN chmod -R 755 /usr/local/lib/python3.13/

RUN echo "Python version:" \
    && python --version \
    && echo "Pip version:" \
    && pip --version \
    && echo "Installing dependencies:" \
    && pip install -r requirements.txt \
    && echo "All installed Python packages:" \
    && pip freeze

CMD ["python", "main.py"]