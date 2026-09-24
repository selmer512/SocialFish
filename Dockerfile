FROM docker.io/python:3.12-alpine

RUN apk add --no-cache bash ethtool gcc musl-dev nmap

WORKDIR /usr/src/app

RUN python -m pip install --upgrade pip
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD [ "python", "SocialFish.py" ]
