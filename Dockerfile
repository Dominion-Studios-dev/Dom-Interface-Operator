FROM gcc:latest

WORKDIR /app

# 1. Install system dependencies (Asio and Boost headers for Crow)
RUN apt-get update && apt-get install -y \
    libasio-dev \
    libboost-all-dev \
    nlohmann-json3-dev \
    wget \
    && rm -rf /var/lib/apt/lists/*

# 2. Download crow.h directly inside the cloud container 
RUN wget https://github.com/CrowCpp/Crow/releases/download/v1.0+5/crow_all.h -O crow.h

# 3. Copy your main.cpp file
COPY . .

# 4. Compile main.cpp ensuring it links pthread for multithreading
RUN g++ -O3 main.cpp -lpthread -o main

CMD ["./main"]