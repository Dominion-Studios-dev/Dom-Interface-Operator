FROM gcc:latest
WORKDIR /app
RUN apt-get update && apt-get install -y \
    libasio-dev \
    libboost-dev \
    nlohmann-json3-dev \
    wget \
    python3 \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*
RUN wget https://github.com/CrowCpp/Crow/releases/download/v1.0%2B5/crow_all.h -O crow.h
COPY . .
RUN g++ -O3 main.cpp -lpthread -o main
CMD ["./main"]