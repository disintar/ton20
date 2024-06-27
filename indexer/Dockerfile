FROM python:3.9-bullseye
COPY requirements.txt /tmp/
RUN  python3.9 -m pip install --upgrade pip  &&  python3.9 -m pip install --no-cache-dir -r /tmp/requirements.txt
WORKDIR /code
COPY . /code/

